"""Dataset para una voz propia de Piper, en formato LJSpeech (voz de otra persona, con permiso, uso privado).

    .venv\\Scripts\\python.exe test\\manual\\preparar_voz.py --fuente <carpeta> --destino <carpeta>

1. Decodifica cada audio con PyAV, a mono: a su frecuencia para el dataset y a
   16 kHz para el VAD y Whisper.
2. Corta en frases con el Silero VAD de faster-whisper (silencios de al menos
   0,3 s, 0,15 s de margen). Une los tramos cortos y parte los largos en su
   silencio más largo, para que cada frase dure de 2 a 15 s.
3. Transcribe cada frase con faster-whisper small (data/models), en CPU int8,
   language="es", beam_size 5, sin el initial_prompt de Asia.
4. Marca "revisar" lo dudoso (ver REVIEW_RULES) y escribe en --destino:
   wavs/NNNN.wav (mono, 16 bits, a la frecuencia del audio), metadata.csv
   (id|texto, solo las aceptadas), revisar.csv (todas, con sus métricas y su
   origen) y resumen.txt.

Ni el audio ni el texto salen de --destino; en --fuente no se escribe nada.
"""
import argparse
import csv
import sys
import time
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from inventario_voz import MEDIA_EXTENSIONS, dbfs  # noqa: E402

VAD_RATE = 16000
VAD_FRAME = 512
MIN_SILENCE_MS = 300
PAD_MS = 150
MIN_S, MAX_S = 2.0, 15.0
SATURATED = 0.99

# Motivos de "revisar": la frase se escucha antes de entrar al dataset.
MIN_LOGPROB = -0.6
MAX_NO_SPEECH = 0.4
MAX_COMPRESSION = 2.4
MAX_SATURATED_PCT = 0.01

COLUMNS = ["id", "revisar", "motivos", "segundos", "texto", "avg_logprob", "no_speech_prob", "compression_ratio",
           "pico_dbfs", "rms_dbfs", "saturadas_pct", "origen", "inicio_s"]


@dataclass
class Phrase:
    id: str
    origen: str
    inicio_s: float
    segundos: float
    texto: str = ""
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    compression_ratio: float = 0.0
    pico_dbfs: float = -120.0
    rms_dbfs: float = -120.0
    saturadas_pct: float = 0.0
    motivos: list = field(default_factory=list)

    @property
    def revisar(self) -> bool:
        return bool(self.motivos)


# --- Audio ---------------------------------------------------------------------------

def decode_mono(path, rate=None):
    """(muestras float32 mono, hz) con PyAV; rate=None, a la frecuencia del archivo."""
    import av

    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        rate = rate or stream.rate or stream.codec_context.sample_rate
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        parts = []

        for frame in container.decode(stream):
            parts += [converted.to_ndarray().reshape(-1) for converted in resampler.resample(frame)]

        parts += [converted.to_ndarray().reshape(-1) for converted in resampler.resample(None)]
        return (np.concatenate(parts) if parts else np.zeros(0)).astype(np.float32), rate


def silero_segments(audio16):
    """[(inicio, fin)] en muestras a 16 kHz: silencios de al menos 0,3 s y 0,15 s de margen."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(threshold=0.5, min_silence_duration_ms=MIN_SILENCE_MS, speech_pad_ms=PAD_MS)
    return [(segment["start"], segment["end"]) for segment in get_speech_timestamps(audio16, options)]


def silero_probabilities(audio16):
    """La probabilidad de voz de cada tramo de 512 muestras a 16 kHz (el mismo modelo)."""
    from faster_whisper.vad import get_vad_model

    padded = np.pad(audio16, (0, (-len(audio16)) % VAD_FRAME))
    return np.asarray(get_vad_model()(padded)).reshape(-1)


# --- Frases de 2 a 15 s ------------------------------------------------------------

def merge_short(segments, min_samples, max_samples):
    """Une cada tramo de menos de min_samples con los siguientes, sin pasar de max_samples."""
    merged = []

    for start, end in segments:
        if merged and merged[-1][1] - merged[-1][0] < min_samples and end - merged[-1][0] <= max_samples:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    # Un último tramo corto se une al anterior si cabe.
    if len(merged) > 1 and merged[-1][1] - merged[-1][0] < min_samples and merged[-1][1] - merged[-2][0] <= max_samples:
        merged[-2:] = [(merged[-2][0], merged[-1][1])]

    return merged


def split_long(segment, probabilities, min_samples, max_samples, threshold=0.5):
    """Parte un tramo largo en su silencio más largo (o el tramo menos seguro de ser voz),
    dejando al menos min_samples a cada lado, hasta que cada parte quepa en max_samples."""
    start, end = segment

    if end - start <= max_samples:
        return [segment]

    first = (start + min_samples) // VAD_FRAME
    last = (end - min_samples) // VAD_FRAME
    window = probabilities[first:last + 1]

    if len(window) == 0:
        middle = (start + end) // 2
    else:
        quiet = window < threshold
        best, best_len, run_start = None, 0, None

        for index, silent in enumerate(np.append(quiet, False)):
            if silent and run_start is None:
                run_start = index
            elif not silent and run_start is not None:
                if index - run_start > best_len:
                    best, best_len = (run_start + index) // 2, index - run_start
                run_start = None

        cut = best if best is not None else int(np.argmin(window))
        middle = (first + cut) * VAD_FRAME + VAD_FRAME // 2

    return (split_long((start, middle), probabilities, min_samples, max_samples, threshold)
            + split_long((middle, end), probabilities, min_samples, max_samples, threshold))


def phrases_of(audio16, segments=silero_segments, probabilities=silero_probabilities):
    """[(inicio, fin)] en muestras a 16 kHz, de 2 a 15 s siempre que se pueda."""
    found = segments(audio16)

    if not found:
        return []

    min_samples, max_samples = int(MIN_S * VAD_RATE), int(MAX_S * VAD_RATE)
    merged = merge_short(found, min_samples, max_samples)
    probs = probabilities(audio16) if any(end - start > max_samples for start, end in merged) else None
    return [part for piece in merged for part in split_long(piece, probs, min_samples, max_samples)]


# --- Whisper -------------------------------------------------------------------------

class WhisperTranscriber:
    """faster-whisper (small por defecto) en CPU int8, sin el vocabulario de Asia.
    model: el nombre de data/models/faster-whisper-<model> ("large-v3-turbo")."""

    def __init__(self, model="small"):
        from config.settings_manager import SettingsManager
        from core.voice import voice_settings
        from core.voice.stt import FasterWhisperSTT

        config = {**voice_settings(SettingsManager()), "stt_model": model, "stt_compute_type": "int8"}
        self.model = FasterWhisperSTT(config).load()

    def __call__(self, audio16):
        """(texto, avg_logprob, no_speech_prob, compression_ratio) de una frase."""
        segments, _ = self.model.transcribe(
            audio16, language="es", beam_size=5, condition_on_previous_text=False, vad_filter=False,
            initial_prompt=None,
        )
        segments = list(segments)

        if not segments:
            return "", -10.0, 1.0, 0.0

        weights = [max(1, len(segment.tokens)) for segment in segments]
        logprob = float(np.average([segment.avg_logprob for segment in segments], weights=weights))
        return (" ".join(segment.text.strip() for segment in segments).strip(), logprob,
                max(segment.no_speech_prob for segment in segments), max(segment.compression_ratio for segment in segments))


# --- Revisar, guardar y resumir --------------------------------------------------------

def review_reasons(phrase: Phrase) -> list:
    words = phrase.texto.split()
    rules = [
        (phrase.avg_logprob < MIN_LOGPROB, f"avg_logprob < {MIN_LOGPROB}"),
        (phrase.no_speech_prob > MAX_NO_SPEECH, f"no_speech_prob > {MAX_NO_SPEECH}"),
        (phrase.compression_ratio > MAX_COMPRESSION, f"compression_ratio > {MAX_COMPRESSION}"),
        (phrase.saturadas_pct > MAX_SATURATED_PCT, f"saturación > {MAX_SATURATED_PCT} %"),
        (not words, "texto vacío"),
        (len(words) == 1, "una sola palabra"),
        (not MIN_S <= phrase.segundos <= MAX_S, f"fuera de {MIN_S:g}–{MAX_S:g} s"),
    ]
    return [reason for broken, reason in rules if broken]


def save_wav(path, samples, rate):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes())


def clean_text(text: str) -> str:
    """Una línea sin "|", que separa las columnas de metadata.csv."""
    return " ".join(text.replace("|", " ").split())


def prepare(source, destination, transcribe=None, decoder=decode_mono, segments=silero_segments,
            probabilities=silero_probabilities, log=print):
    """Escribe el dataset en destination y devuelve (frases, segundos de transcripción)."""
    source, destination = Path(source), Path(destination)
    files = sorted(path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS)
    wavs = destination / "wavs"
    wavs.mkdir(parents=True, exist_ok=True)
    transcribe = transcribe or WhisperTranscriber()
    phrases, whisper_s = [], 0.0

    for number, path in enumerate(files, 1):
        audio, rate = decoder(path)
        audio16, _ = decoder(path, VAD_RATE)
        found = phrases_of(audio16, segments, probabilities)
        log(f"[{number}/{len(files)}] {len(found)} frases", flush=True)

        for start, end in found:
            clip16 = audio16[start:end]
            clip = audio[int(start * rate / VAD_RATE):int(end * rate / VAD_RATE)]
            phrase = Phrase(id=f"{len(phrases) + 1:04d}", origen=path.relative_to(source).as_posix(),
                            inicio_s=round(start / VAD_RATE, 2), segundos=round(len(clip) / rate, 2))
            began = time.perf_counter()
            text, phrase.avg_logprob, phrase.no_speech_prob, phrase.compression_ratio = transcribe(clip16)
            whisper_s += time.perf_counter() - began
            phrase.texto = clean_text(text)
            magnitude = np.abs(clip)
            phrase.pico_dbfs = dbfs(float(magnitude.max())) if len(clip) else -120.0
            phrase.rms_dbfs = dbfs(float(np.sqrt(np.mean(clip.astype(np.float64) ** 2)))) if len(clip) else -120.0
            phrase.saturadas_pct = round(float(np.mean(magnitude >= SATURATED)) * 100, 4) if len(clip) else 0.0
            phrase.motivos = review_reasons(phrase)
            save_wav(wavs / f"{phrase.id}.wav", clip, rate)
            phrases.append(phrase)

    write_outputs(phrases, destination, whisper_s)
    return phrases, whisper_s


def write_outputs(phrases, destination, whisper_s):
    with open(destination / "metadata.csv", "w", newline="", encoding="utf-8") as out:
        out.writelines(f"{phrase.id}|{phrase.texto}\n" for phrase in phrases if not phrase.revisar)

    with open(destination / "revisar.csv", "w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=COLUMNS)
        writer.writeheader()

        for phrase in phrases:
            row = {key: value for key, value in asdict(phrase).items() if key in COLUMNS}
            writer.writerow({**row, "revisar": "sí" if phrase.revisar else "", "motivos": "; ".join(phrase.motivos)})

    (destination / "resumen.txt").write_text(summary(phrases, whisper_s) + "\n", encoding="utf-8")


def summary(phrases, whisper_s=0.0) -> str:
    accepted = [phrase for phrase in phrases if not phrase.revisar]
    reasons = {}

    for phrase in phrases:
        for reason in phrase.motivos:
            reasons[reason] = reasons.get(reason, 0) + 1

    lines = [
        f"Frases: {len(phrases)}; aceptadas {len(accepted)}, a revisar {len(phrases) - len(accepted)}.",
        f"Minutos aceptados: {sum(phrase.segundos for phrase in accepted) / 60:.1f} "
        f"de {sum(phrase.segundos for phrase in phrases) / 60:.1f}.",
        f"Transcripción: {whisper_s / 60:.1f} min.",
    ]
    lines += [f"  {reason}: {count}" for reason, count in sorted(reasons.items(), key=lambda item: -item[1])]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fuente", type=Path, required=True, help="carpeta con los audios (solo se lee)")
    parser.add_argument("--destino", type=Path, required=True, help="carpeta del dataset (wavs/, metadata.csv...)")
    args = parser.parse_args()

    if not args.fuente.is_dir():
        parser.error(f"no existe la carpeta {args.fuente}")

    # Nunca se pisa un dataset anterior (puede tener frases ya revisadas a mano).
    if (args.destino / "metadata.csv").exists() or any((args.destino / "wavs").glob("*.wav")):
        parser.error(f"ya hay un dataset en {args.destino}; usa otra carpeta")

    phrases, whisper_s = prepare(args.fuente, args.destino)
    print()
    print(summary(phrases, whisper_s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
