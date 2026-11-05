"""Palabra de activación (fase J3) con openWakeWord y el micrófono real.

Aciertos: dices la frase de activación cuando lo pide, una vez por intento, y
cuenta en cuántos intentos se activa (y con qué puntuación máxima). El micrófono y
el modelo quedan abiertos toda la prueba; antes de cada intento se reinicia el
modelo y se le dan 2 s de audio sin contar (sus buffers tardan eso en llenarse),
y solo entonces dice "Habla ahora": 6 s de ventana. Da el pico y el RMS del audio.

    .venv\\Scripts\\python.exe test\\manual\\check_wake.py --aciertos 20

--guardar-audio [CARPETA] guarda cada intento (con el calentamiento) como WAV de
16 kHz en CARPETA (data/wake/, ignorada por git; no sale del equipo). --repuntuar
CARPETA puntúa esos WAV sin micrófono, con --umbral y --vad:

    .venv\\Scripts\\python.exe test\\manual\\check_wake.py --aciertos 20 --guardar-audio
    .venv\\Scripts\\python.exe test\\manual\\check_wake.py --repuntuar data\\wake --umbral 0.3

Falsas activaciones: escucha los minutos que digas sin que la llames (habla
normal, música, la tele...) y cuenta cuántas veces se activa; da la tasa por hora.

    .venv\\Scripts\\python.exe test\\manual\\check_wake.py --falsas 30

Por defecto, lo de "voice" en la configuración (voice.wake_word, voice.wake_threshold,
voice.wake_vad_threshold, los modelos de voice.wake_models_dir). --modelo cambia el
.onnx ("Oye Asia", más adelante), --umbral la puntuación desde la que cuenta y --vad
el umbral del VAD de openWakeWord (0 lo apaga). --guardar escribe el resultado en
JSON. Solo carga openWakeWord: ni Whisper ni Ollama. Sin --guardar-audio, el audio
no se guarda en disco.

Grabar ejemplos para entrenar "Oye Asia" (sin puntuar ni cargar openWakeWord):
--grabar N --frase "oye Asia" graba N clips con el mismo calentamiento y "Habla
ahora", recortados a la voz (Silero VAD) con 0,3 s de margen, en
data/wake/positivos/<frase>/ (--carpeta cambia data/wake). De cada clip da la
duración, el pico y el RMS, avisa si satura o si es muy bajo, y deja repetirlo.
La numeración sigue la de los clips que ya haya.

    .venv\\Scripts\\python.exe test\\manual\\check_wake.py --grabar 20 --frase "oye Asia"

--negativos [N] graba lo mismo (N por frase, 3 si no se dice) para frases parecidas
que NO deben activarla, mostradas una por una, en data/wake/negativos/<frase>/.
"""
import argparse
import json
import queue
import re
import sys
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.voice.audio import FRAME, SAMPLE_RATE, Microphone

from config.settings_manager import SettingsManager
from core.voice import voice_settings
from core.voice.wake import CHUNK, Activations, Chunker, load_model as load_wake_model, missing, reset_model, wake_config

# Tras reset(), openWakeWord tarda 25 tramos (2 s) en tener solo audio real: 10 para
# vaciar el espectrograma inicial y 16 embeddings para la ventana de la palabra.
WARMUP_S = 2.0
WINDOW_S = 6.0
AUDIO_DIR = ROOT / "data" / "wake"
SILENCE_DBFS = -120.0
# Clips para entrenar (--grabar): margen alrededor de la voz y avisos de nivel.
MARGIN_S = 0.3
SATURATED = 0.99
LOW_PEAK_DBFS = -30.0
# Parecidas a "Oye Asia" que no deben activarla (--negativos).
NEGATIVE_PHRASES = ["oye", "Asia", "hoy hacia", "oye Alicia", "Asia Menor", "o ya sí a", "hey"]
NEGATIVES_PER_PHRASE = 3


def per_hour(count: int, seconds: float) -> float:
    return count * 3600 / seconds if seconds else 0.0


def config_for(model, vad):
    """voice de la configuración, con el modelo y el VAD de la línea de comandos."""
    config = voice_settings(SettingsManager())
    return {**config, **({"wake_word": model} if model else {}), **({"wake_vad_threshold": vad} if vad is not None else {})}


def load_model(config):
    """El modelo de openWakeWord de config; None si falta el paquete o algún modelo."""
    if missing(config):
        return None

    return load_wake_model(config)


def scores(model, stream, seconds):
    """La puntuación de cada tramo de 80 ms durante seconds de audio del micrófono."""
    chunker = Chunker()
    heard = 0.0

    for frame in stream:
        for chunk in chunker.feed(frame):
            prediction = model.predict(chunk)
            heard += CHUNK / SAMPLE_RATE
            yield max(prediction.values(), default=0.0)

        if heard >= seconds:
            return


def chunk_count(seconds) -> int:
    return round(seconds * SAMPLE_RATE / CHUNK)


def take(stream, chunker, seconds):
    """Los tramos de CHUNK muestras de seconds de audio del micrófono, a medida que llegan.
    Lo que sobra se queda en chunker para el siguiente take."""
    wanted, given, ready = chunk_count(seconds), 0, []

    for frame in stream:
        ready.extend(chunker.feed(frame))

        while ready and given < wanted:
            yield ready.pop(0)
            given += 1

        if given >= wanted:
            break

    if ready:
        chunker.pending = np.concatenate(ready + [chunker.pending])


def drain(stream):
    """Tira el audio que llegó mientras se esperaba el Enter."""
    frames = getattr(stream, "frames", None)

    while frames is not None:
        try:
            frames.get_nowait()
        except queue.Empty:
            return


def dbfs(value) -> float:
    return round(max(20 * np.log10(value), SILENCE_DBFS), 1) if value > 0 else SILENCE_DBFS


def levels(chunks) -> tuple:
    """(pico, RMS) en dBFS de unos tramos int16."""
    if not chunks:
        return SILENCE_DBFS, SILENCE_DBFS

    samples = np.concatenate(chunks).astype(np.float64) / 32767
    return dbfs(np.max(np.abs(samples))), dbfs(np.sqrt(np.mean(samples ** 2)))


def run_trial(model, warmup, window, threshold, on_ready=lambda: None):
    """Reinicia el modelo, le da warmup sin contar y puntúa window. Las dos, tramos int16.

    Devuelve (fila, tramos): la fila con si activó, la puntuación máxima y los niveles
    de la ventana; los tramos, el calentamiento y la ventana seguidos.
    """
    reset_model(model)
    heard = []

    for chunk in warmup:
        model.predict(chunk)
        heard.append(chunk)

    warm = len(heard)
    on_ready()
    found = Activations(threshold)
    fired = False

    for chunk in window:
        fired = found.feed(max(model.predict(chunk).values(), default=0.0)) or fired
        heard.append(chunk)

    peak, rms = levels(heard[warm:])
    _, rms_warmup = levels(heard[:warm])
    row = {"activó": fired, "puntuación máxima": round(float(found.peak), 3),
           "pico_dbfs": peak, "rms_dbfs": rms, "rms_calentamiento_dbfs": rms_warmup}
    return row, heard


def describe(row) -> str:
    return (f"{'sí' if row['activó'] else 'no'} (máxima {row['puntuación máxima']:.2f}; pico {row['pico_dbfs']:.1f} dBFS, "
            f"RMS {row['rms_dbfs']:.1f} dBFS; antes, RMS {row['rms_calentamiento_dbfs']:.1f} dBFS)")


def save_wav(path, chunks):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(np.concatenate(chunks).astype("<i2").tobytes())


def read_wav(path) -> np.ndarray:
    """Las muestras int16 de un WAV mono de 16 kHz y 16 bits; ValueError si es de otro formato."""
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError(f"{Path(path).name}: no es mono, 16 bits y {SAMPLE_RATE} Hz")

        return np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.int16)


def split_chunks(samples) -> list:
    return [samples[start:start + CHUNK] for start in range(0, len(samples) - CHUNK + 1, CHUNK)]


def trial_files(folder) -> list:
    return sorted(Path(folder).glob("intento_*.wav"))


def summary(rows, threshold) -> dict:
    right = sum(row["activó"] for row in rows)
    print(f"\nAciertos: {right}/{len(rows)} con umbral {threshold}.")
    return {"aciertos": right, "intentos": len(rows), "filas": rows}


def hits(model, trials, threshold, audio_dir=None, microphone=None):
    rows = []

    with (microphone or Microphone()).open() as stream:
        for trial in range(1, trials + 1):
            input(f"[{trial}/{trials}] Enter y di la frase cuando diga «Habla ahora»… ")
            drain(stream)
            chunker = Chunker()
            row, heard = run_trial(
                model, take(stream, chunker, WARMUP_S), take(stream, chunker, WINDOW_S), threshold,
                on_ready=lambda: print(f"    Habla ahora ({WINDOW_S:.0f} s)…", flush=True),
            )

            if audio_dir:
                save_wav(Path(audio_dir) / f"intento_{trial:02d}.wav", heard)

            rows.append({"intento": trial, **row})
            print(f"    {describe(row)}", flush=True)

    return summary(rows, threshold)


def rescore(model, folder, threshold):
    """Puntúa los intentos guardados con --guardar-audio, sin micrófono."""
    rows = []
    warm = chunk_count(WARMUP_S)

    for path in trial_files(folder):
        chunks = split_chunks(read_wav(path))
        row, _ = run_trial(model, chunks[:warm], chunks[warm:], threshold)
        rows.append({"archivo": path.name, **row})
        print(f"{path.name}: {describe(row)}", flush=True)

    return summary(rows, threshold)


def false_alarms(model, minutes, threshold):
    found = Activations(threshold)
    start = time.perf_counter()
    print(f"Escuchando {minutes} min sin llamarla. Ctrl+C para terminar antes.", flush=True)

    try:
        with Microphone().open() as stream:
            for score in scores(model, stream, minutes * 60):
                if found.feed(score):
                    print(f"    activación a los {found.elapsed:.0f} s (puntuación {score:.2f})", flush=True)
    except KeyboardInterrupt:
        pass

    seconds = found.elapsed or time.perf_counter() - start
    rate = per_hour(len(found.times), seconds)
    print(f"\nFalsas activaciones: {len(found.times)} en {seconds / 60:.1f} min ({rate:.1f} por hora), umbral {threshold}.")
    return {"falsas": len(found.times), "segundos": round(seconds), "por_hora": round(rate, 2), "en_s": found.times}


def slug(phrase: str) -> str:
    """"oye Asia" -> "oye_asia": el nombre de la carpeta de una frase."""
    text = unicodedata.normalize("NFKD", phrase.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "_".join(re.findall(r"[a-z0-9]+", text)) or "frase"


def next_index(folder) -> int:
    """El número del clip siguiente: sigue los NNN.wav que ya haya."""
    numbers = [int(path.stem) for path in Path(folder).glob("*.wav") if path.stem.isdigit()]
    return max(numbers, default=0) + 1


def take_frames(stream, seconds) -> list:
    """Los tramos del micrófono (float32, FRAME muestras) de seconds de audio."""
    frames = []

    for frame in stream:
        frames.append(np.asarray(frame, dtype=np.float32))

        if len(frames) * FRAME >= seconds * SAMPLE_RATE:
            break

    return frames


def trim_to_voice(warmup, window, vad, threshold, margin_s=MARGIN_S):
    """La voz de window con margin_s antes y después, según el VAD; None si no hubo voz.

    El calentamiento solo asienta el estado del VAD: no entra en el clip.
    """
    vad.reset()

    for frame in warmup:
        vad.probability(frame)

    voiced = [index for index, frame in enumerate(window) if vad.probability(frame) >= threshold]

    if not voiced:
        return None

    margin = round(margin_s * SAMPLE_RATE / FRAME)
    return np.concatenate(window[max(0, voiced[0] - margin):voiced[-1] + 1 + margin])


def clip_report(samples) -> dict:
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) if len(samples) else 0.0
    return {
        "segundos": round(len(samples) / SAMPLE_RATE, 2), "pico_dbfs": dbfs(peak), "rms_dbfs": dbfs(rms),
        "satura": peak >= SATURATED, "bajo": dbfs(peak) < LOW_PEAK_DBFS,
    }


def describe_clip(report) -> str:
    warnings = [*(["satura: aléjate o baja la voz"] if report["satura"] else []),
                *(["muy bajo: acércate o sube la voz"] if report["bajo"] else [])]
    text = f"{report['segundos']:.2f} s, pico {report['pico_dbfs']:.1f} dBFS, RMS {report['rms_dbfs']:.1f} dBFS"
    return f"{text}. ¡Aviso: {'; '.join(warnings)}!" if warnings else text


def to_int16(samples) -> np.ndarray:
    """Como Chunker (core/voice/wake.py): recorte a ±1 y escala ×32767."""
    return (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)


def record(plan, root, vad, threshold, microphone=None, ask=input):
    """Graba los clips de plan, [(frase, cuántos)], en root/<frase>/NNN.wav.

    Por clip: Enter, 2 s de calentamiento, "Habla ahora" y 6 s; se recorta a la voz.
    Devuelve {frase: [informe de cada clip guardado]}.
    """
    saved = {}

    with (microphone or Microphone()).open() as stream:
        for phrase, count in plan:
            folder = Path(root) / slug(phrase)
            folder.mkdir(parents=True, exist_ok=True)
            rows = saved.setdefault(phrase, [])

            while len(rows) < count:
                ask(f"[«{phrase}» {len(rows) + 1}/{count}] Enter y dilo cuando diga «Habla ahora»… ")
                drain(stream)
                warmup = take_frames(stream, WARMUP_S)
                print(f"    Habla ahora: «{phrase}»", flush=True)
                clip = trim_to_voice(warmup, take_frames(stream, WINDOW_S), vad, threshold)

                if clip is None:
                    print("    No oí voz: otra vez.", flush=True)
                    continue

                report = clip_report(clip)
                print(f"    {describe_clip(report)}", flush=True)

                if ask("    Enter lo guarda; r y Enter lo repite: ").strip().lower().startswith("r"):
                    continue

                path = folder / f"{next_index(folder):03d}.wav"
                save_wav(path, [to_int16(clip)])
                rows.append({"archivo": path.name, **report})

    for phrase, rows in saved.items():
        print(f"«{phrase}»: {len(rows)} clips en {Path(root) / slug(phrase)}")

    return saved


def negative_plan(count) -> list:
    return [(phrase, count) for phrase in NEGATIVE_PHRASES]


def voice_vad():
    from core.voice.vad import SileroVAD

    return SileroVAD()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--aciertos", type=int, metavar="INTENTOS", help="intentos diciendo la frase de activación")
    parser.add_argument("--falsas", type=float, metavar="MINUTOS", help="minutos escuchando sin llamarla")
    parser.add_argument("--modelo", help="nombre de un .onnx de voice.wake_models_dir o su ruta (voice.wake_word)")
    parser.add_argument("--umbral", type=float, help="puntuación desde la que cuenta (voice.wake_threshold)")
    parser.add_argument("--vad", type=float, help="umbral del VAD de openWakeWord (voice.wake_vad_threshold; 0 lo apaga)")
    parser.add_argument("--guardar", type=Path, help="JSON con el resultado")
    parser.add_argument("--guardar-audio", type=Path, nargs="?", const=AUDIO_DIR, metavar="CARPETA",
                        help="guarda cada intento de --aciertos como WAV de 16 kHz (por defecto, data/wake)")
    parser.add_argument("--repuntuar", type=Path, metavar="CARPETA", help="puntúa los WAV guardados, sin micrófono")
    parser.add_argument("--grabar", type=int, metavar="N", help="graba N clips de --frase para entrenar, sin puntuar")
    parser.add_argument("--frase", help="la frase de --grabar (\"oye Asia\")")
    parser.add_argument("--negativos", type=int, nargs="?", const=NEGATIVES_PER_PHRASE, metavar="N",
                        help=f"graba N clips de cada frase que no debe activarla ({NEGATIVES_PER_PHRASE} si no se dice)")
    parser.add_argument("--carpeta", type=Path, default=AUDIO_DIR, help="dónde van los clips (por defecto, data/wake)")
    args = parser.parse_args()

    if args.grabar:
        if not args.frase:
            parser.error("--grabar necesita --frase")

        config = voice_settings(SettingsManager())
        record([(args.frase, args.grabar)], args.carpeta / "positivos", voice_vad(), config["vad_threshold"])
        return 0

    if args.negativos:
        config = voice_settings(SettingsManager())
        record(negative_plan(args.negativos), args.carpeta / "negativos", voice_vad(), config["vad_threshold"])
        return 0

    if not args.aciertos and not args.falsas and not args.repuntuar:
        parser.error("di --aciertos INTENTOS, --falsas MINUTOS, --repuntuar CARPETA, --grabar N o --negativos")

    if args.repuntuar and not trial_files(args.repuntuar):
        parser.error(f"no hay intento_*.wav en {args.repuntuar}")

    # Nunca se pisa una grabación anterior.
    if args.guardar_audio and trial_files(args.guardar_audio):
        parser.error(f"ya hay intentos guardados en {args.guardar_audio}; usa otra carpeta")

    config = config_for(args.modelo, args.vad)
    threshold = args.umbral if args.umbral is not None else wake_config(config)["wake_threshold"]
    model = load_model(config)

    if model is None:
        print(missing(config) or "No pude cargar el modelo de openWakeWord.")
        return 2

    result = {"modelo": config["wake_word"], "umbral": threshold, "vad": config["wake_vad_threshold"]}

    if args.repuntuar:
        result["repuntuados"] = rescore(model, args.repuntuar, threshold)

    if args.aciertos:
        if args.guardar_audio:
            args.guardar_audio.mkdir(parents=True, exist_ok=True)

        result["aciertos"] = hits(model, args.aciertos, threshold, args.guardar_audio)

    if args.falsas:
        result["falsas"] = false_alarms(model, args.falsas, threshold)

    if args.guardar:
        args.guardar.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
