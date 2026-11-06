"""Compara modelos de "Oye Asia" con frases de Piper, por el camino del micrófono (sin micrófono).

    .venv\\Scripts\\python.exe test\\manual\\comparar_wake.py --modelo oye_asia_v0.1 --modelo oye_asia_v0.2

Por cada caso y cada voz (claude-high y los dos hablantes de sharvard), la puntuación
máxima tras calentar el modelo (core/voice/wake.py, warmup_chunks) con el fondo del
caso: "oye Asia" sola, con frase detrás y con frase delante, y "hoy hacia" (que
engañaba al v0.1) sin fondo y con fondo de ruido. Lo que debe activarse, alto; lo
que no, bajo. Carga Piper y openWakeWord; ni Whisper ni Ollama.
"""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import generar_wake  # noqa: E402
from core.voice import DEFAULT_VOICE_SETTINGS  # noqa: E402
from core.voice.audio import FRAME  # noqa: E402
from core.voice.wake import Chunker, reset_model, warmup_chunks  # noqa: E402

RATE = 16000
TAIL_S = 2.0
LEVEL = 0.5  # la voz de Piper, a la mitad: picos como los del micrófono de la laptop
VOICES = [("es_MX-claude-high", None), ("es_ES-sharvard-medium", 0), ("es_ES-sharvard-medium", 1)]
VOICE_LABELS = ["claude", "sharv-M", "sharv-F"]


@dataclass
class Case:
    name: str
    text: str
    background_db: float | None  # None: silencio digital
    should_fire: bool


CASES = [
    Case("sola", "oye Asia", -60, True),
    Case("sola, sin fondo", "oye Asia", None, True),
    Case("con frase detrás", "oye Asia, qué hora es", -60, True),
    Case("con frase delante", "bueno, oye Asia", -60, True),
    Case("hoy hacia, sin fondo", "hoy hacia", None, False),
    Case("hoy hacia, fondo -60 dBFS", "hoy hacia", -60, False),
    Case("hoy hacia, fondo -45 dBFS", "hoy hacia", -45, False),
]


def background(seconds, db, rng) -> np.ndarray:
    count = int(seconds * RATE)

    if db is None:
        return np.zeros(count, dtype=np.float32)

    return rng.normal(0, 10 ** (db / 20), count).astype(np.float32)


def best_score(model, audio, db, rng) -> float:
    """La máxima puntuación de audio (float32 a 16 kHz) entre fondo, tras el calentamiento del modelo."""
    reset_model(model)
    warm = warmup_chunks(model)
    lead = background(warm * 1280 / RATE + 0.5, db, rng)
    samples = np.concatenate([lead, audio, background(TAIL_S, db, rng)])
    chunker, scores = Chunker(), []

    for start in range(0, len(samples) - FRAME + 1, FRAME):
        for chunk in chunker.feed(samples[start:start + FRAME]):
            scores.append(max(model.predict(chunk).values(), default=0.0))

    return max(scores[warm:], default=0.0)


def compare(models, speak, cases=CASES, voices=VOICES, seed=0) -> dict:
    """{(modelo, caso): [puntuación por voz]}. speak(texto, voz, hablante) -> audio float32 a 16 kHz."""
    rng = np.random.default_rng(seed)
    audio = {(case.text, voice, speaker): speak(case.text, voice, speaker) * LEVEL
             for case in cases for voice, speaker in voices}
    return {(name, case.name): [best_score(model, audio[(case.text, voice, speaker)], case.background_db, rng)
                                for voice, speaker in voices]
            for name, model in models.items() for case in cases}


def table(results, models, cases=CASES) -> str:
    voices = "  ".join(f"{label:>8}" for label in VOICE_LABELS)
    lines = []

    for name in models:
        lines += [f"\n{name}", f"{'caso':30} {'¿debe?':>6}  {voices}"]

        for case in cases:
            scores = "  ".join(f"{score:8.3f}" for score in results[(name, case.name)])
            lines.append(f"{case.name:30} {'sí' if case.should_fire else 'no':>6}  {scores}")

    return "\n".join(lines)


def piper_speaker():
    loaded = {}

    def speak(text, voice, speaker):
        if voice not in loaded:
            loaded[voice] = generar_wake.load_piper(voice)

        clip = generar_wake.Clip("x.wav", "comparar", voice, speaker, text, 1.0, 0.667, 0.8)
        return generar_wake.to_16k(*generar_wake.synthesize(loaded[voice], clip))

    return speak


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modelo", action="append", help="un .onnx de voice.wake_models_dir (se puede repetir)")
    args = parser.parse_args()
    from core.voice.wake import load_model, missing

    models = {}

    for name in args.modelo or ["oye_asia_v0.1"]:
        config = {**DEFAULT_VOICE_SETTINGS, "wake_word": name}

        if missing(config):
            print(missing(config))
            return 2

        models[name] = load_model(config)

    print(table(compare(models, piper_speaker()), models))
    return 0


if __name__ == "__main__":
    sys.exit(main())
