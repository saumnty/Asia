"""Clips para entrenar "Oye Asia" en Colab (J3, paso 2 del ROADMAP).

    .venv\\Scripts\\python.exe test\\manual\\generar_wake.py --destino C:\\AsiaVoz\\wake

1. Positivos con Piper y las voces de data/voices: "oye Asia" y variantes, y
   "oye Asia, <frase corta>", variando length_scale (0,8–1,3), noise_scale y
   noise_w. WAV de 16 kHz mono, de 1 a 3 s (lo que pasa de 3 s se corta con un
   desvanecido; lo corto se rellena con silencio).
2. Negativos difíciles con las mismas voces y variaciones: frases que suenan
   parecido sin ser la palabra.
3. En --destino: sintetico.zip (positivos/, negativos/ y clips.csv con la voz,
   el texto y los parámetros de cada clip), mi_voz.zip (lo grabado con
   check_wake --grabar y --negativos en data/wake) y LEEME.txt.

Solo voz sintética y lo que el usuario grabó; subirlo a Drive lo decide él.
"""
import argparse
import csv
import io
import sys
import time
import wave
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

RATE = 16000
MIN_S, MAX_S = 1.0, 3.0
FADE_S = 0.05
POSITIVES = 4000
NEGATIVES = 2000
SEED = 2026

# (voz, hablante): sharvard trae dos (M y F).
VOICES = [("es_MX-claude-high", None), ("es_MX-ald-medium", None), ("es_ES-sharvard-medium", 0),
          ("es_ES-sharvard-medium", 1)]
LICENSES = {
    "es_MX-claude-high": "datos Apache-2.0",
    "es_MX-ald-medium": "Unlicense",
    "es_ES-sharvard-medium": "CC BY 3.0 (exige atribución: voz sharvard de Piper, rhasspy/piper-voices)",
}

WAKE = ["oye Asia", "oye, Asia", "¡oye Asia!", "¿oye Asia?", "oye Asia."]
FOLLOW_UPS = ["abre el bloc de notas", "qué hora es", "cómo estás", "pon música", "qué tiempo hace",
              "abre Chrome", "¿me ayudas?", "explica este archivo", "busca en Wikipedia", "recuérdame algo",
              "¿qué es un grafo?", "apaga la voz", "cuéntame un chiste", "resume esto"]
NEGATIVE_PHRASES = ["oye", "Asia", "hoy hacia", "hoy hacía frío", "oye Alicia", "Asia Menor", "o ya sí a", "hey",
                    "Malasia", "fantasía", "Anastasia", "oye tía", "oye, así", "hacia allá", "oye Lucía",
                    "eutanasia", "gimnasia", "oye, amiga", "hoy hay sol", "ya casi", "oiga", "así sí",
                    "Asia y Europa", "oye, ¿y ya?", "hacía calor", "hay sí", "o sea, sí"]


@dataclass
class Clip:
    name: str
    kind: str
    voice: str
    speaker: object
    text: str
    length_scale: float
    noise_scale: float
    noise_w: float
    seconds: float = 0.0
    trimmed: bool = False


def positive_texts() -> list:
    return WAKE + [f"oye Asia, {follow}" for follow in FOLLOW_UPS]


def plan(texts, count, kind, rng) -> list:
    """count clips repartidos por igual entre voces y textos, con parámetros al azar (semilla fija)."""
    clips = []

    for number in range(count):
        voice, speaker = VOICES[number % len(VOICES)]
        text = texts[(number // len(VOICES)) % len(texts)]
        clips.append(Clip(
            name=f"{kind[0]}{number + 1:05d}.wav", kind=kind, voice=voice, speaker=speaker, text=text,
            length_scale=round(float(rng.uniform(0.8, 1.3)), 3), noise_scale=round(float(rng.uniform(0.4, 0.9)), 3),
            noise_w=round(float(rng.uniform(0.5, 1.1)), 3),
        ))

    return clips


def load_piper(name):
    from piper import PiperVoice

    return PiperVoice.load(ROOT / "data" / "voices" / f"{name}.onnx")


def synthesize(voice, clip) -> tuple:
    """(audio float32, frecuencia) de clip con su voz y sus parámetros."""
    from piper import SynthesisConfig

    config = SynthesisConfig(speaker_id=clip.speaker, length_scale=clip.length_scale, noise_scale=clip.noise_scale,
                             noise_w_scale=clip.noise_w)
    chunks = list(voice.synthesize(clip.text, syn_config=config))

    if not chunks:
        return np.zeros(0, dtype=np.float32), RATE

    return np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32), chunks[0].sample_rate


def to_16k(audio, rate) -> np.ndarray:
    if rate == RATE:
        return audio.astype(np.float32)

    from math import gcd

    from scipy.signal import resample_poly

    common = gcd(RATE, rate)
    return resample_poly(audio, RATE // common, rate // common).astype(np.float32)


def fit(audio) -> tuple:
    """(audio de MIN_S a MAX_S, si se cortó): se corta con un desvanecido o se rellena con silencio."""
    longest, shortest = int(MAX_S * RATE), int(MIN_S * RATE)

    if len(audio) > longest:
        audio = audio[:longest].copy()
        fade = int(FADE_S * RATE)
        audio[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
        return audio, True

    if len(audio) < shortest:
        return np.concatenate([audio, np.zeros(shortest - len(audio), dtype=np.float32)]), False

    return audio, False


def wav_bytes(audio, rate=RATE) -> bytes:
    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes())

    return buffer.getvalue()


def generate(destination, positives=POSITIVES, negatives=NEGATIVES, load_voice=load_piper, synth=synthesize,
             log=print) -> list:
    """Escribe sintetico.zip en destination; devuelve los clips con su duración."""
    rng = np.random.default_rng(SEED)
    clips = plan(positive_texts(), positives, "positivos", rng) + plan(NEGATIVE_PHRASES, negatives, "negativos", rng)
    voices = {}
    destination.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(destination / "sintetico.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for number, clip in enumerate(clips, 1):
            if clip.voice not in voices:
                voices[clip.voice] = load_voice(clip.voice)

            audio, clip.trimmed = fit(to_16k(*synth(voices[clip.voice], clip)))
            clip.seconds = round(len(audio) / RATE, 3)
            archive.writestr(f"{clip.kind}/{clip.name}", wav_bytes(audio))

            if number % 500 == 0:
                log(f"{number}/{len(clips)} clips", flush=True)

        table = io.StringIO()
        writer = csv.writer(table)
        writer.writerow(["archivo", "tipo", "voz", "hablante", "texto", "length_scale", "noise_scale", "noise_w",
                         "segundos", "cortado"])
        writer.writerows([f"{c.kind}/{c.name}", c.kind, c.voice, "" if c.speaker is None else c.speaker, c.text,
                          c.length_scale, c.noise_scale, c.noise_w, c.seconds, c.trimmed] for c in clips)
        archive.writestr("clips.csv", table.getvalue())

    return clips


def pack_recordings(wake_dir, destination) -> dict:
    """mi_voz.zip con data/wake/positivos/oye_asia y data/wake/negativos/<frase>; {carpeta: clips}."""
    wake_dir = Path(wake_dir)
    counts = {"positivos": 0, "negativos": 0}

    with zipfile.ZipFile(destination / "mi_voz.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((wake_dir / "positivos" / "oye_asia").glob("*.wav")):
            archive.write(path, f"positivos/{path.name}")
            counts["positivos"] += 1

        for path in sorted((wake_dir / "negativos").glob("*/*.wav")):
            archive.write(path, f"negativos/{path.parent.name}/{path.name}")
            counts["negativos"] += 1

    return counts


def readme(clips, recorded) -> str:
    count = {kind: sum(c.kind == kind for c in clips) for kind in ("positivos", "negativos")}
    trimmed = sum(c.trimmed for c in clips)
    seconds = {kind: sum(c.seconds for c in clips if c.kind == kind) for kind in count}
    voices = "\n".join(f"- {name}: {license}" for name, license in LICENSES.items())
    return f"""Clips para entrenar "Oye Asia" (openWakeWord, cuaderno automatic_model_training.ipynb)

sintetico.zip (Piper, voz sintética):
- positivos/: {count['positivos']} clips ({seconds['positivos'] / 60:.1f} min): {", ".join(WAKE)} y "oye Asia, <frase corta>".
- negativos/: {count['negativos']} clips ({seconds['negativos'] / 60:.1f} min): frases parecidas que no deben activarla.
- WAV de 16 kHz, mono, 16 bits, de {MIN_S:g} a {MAX_S:g} s ({trimmed} cortados a {MAX_S:g} s con un desvanecido).
- length_scale de 0,8 a 1,3, noise_scale de 0,4 a 0,9 y noise_w de 0,5 a 1,1, al azar (semilla {SEED}).
- clips.csv: la voz, el hablante, el texto y los parámetros de cada clip.

mi_voz.zip (grabaciones del usuario con el micrófono de la laptop; uso privado):
- positivos/: {recorded['positivos']} clips de "oye Asia".
- negativos/<frase>/: {recorded['negativos']} clips.

Voces de Piper y sus licencias:
{voices}

El modelo que se entrene con las características de ACAV100M (CC BY-NC-SA 4.0)
hereda el uso no comercial: personal, no distribuible.
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destino", type=Path, required=True, help="carpeta de los zip (fuera del repositorio)")
    parser.add_argument("--positivos", type=int, default=POSITIVES)
    parser.add_argument("--negativos", type=int, default=NEGATIVES)
    parser.add_argument("--grabaciones", type=Path, default=ROOT / "data" / "wake", help="lo grabado con check_wake")
    args = parser.parse_args()

    if (args.destino / "sintetico.zip").exists():
        parser.error(f"ya hay un sintetico.zip en {args.destino}; usa otra carpeta")

    started = time.perf_counter()
    clips = generate(args.destino, args.positivos, args.negativos)
    seconds = time.perf_counter() - started
    recorded = pack_recordings(args.grabaciones, args.destino)
    (args.destino / "LEEME.txt").write_text(readme(clips, recorded), encoding="utf-8")

    print(f"\nGenerados {len(clips)} clips en {seconds / 60:.1f} min.")

    for name in ("sintetico.zip", "mi_voz.zip"):
        print(f"{name}: {(args.destino / name).stat().st_size / 1e6:.1f} MB")

    print(readme(clips, recorded))
    return 0


if __name__ == "__main__":
    sys.exit(main())
