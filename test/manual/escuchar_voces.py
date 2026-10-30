"""Escuchar las voces de Piper descargadas, con la misma frase (fase J1, paso 2).

Lee cada voz de data/voices/ (y cada hablante, si la voz tiene varios),
muestra cuánto tardó en generarse y la reproduce por los altavoces.

    .venv\\Scripts\\python.exe test\\manual\\escuchar_voces.py
    .venv\\Scripts\\python.exe test\\manual\\escuchar_voces.py --voz es_MX-ald-medium
    .venv\\Scripts\\python.exe test\\manual\\escuchar_voces.py --frase "Hola, ¿qué tal?"
    .venv\\Scripts\\python.exe test\\manual\\escuchar_voces.py --sin-audio   # solo mide

El tono medio (Hz) ayuda a saber si una voz es grave o aguda: las
masculinas suelen quedar por debajo de ~165 Hz. Nada se guarda en disco.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
VOICES = ROOT / "data" / "voices"

PHRASE = (
    "Hola, soy Asia. Encontré dos errores en el archivo de la calculadora: "
    "la división no comprueba el cero y la suma convierte mal los decimales. "
    "¿Quieres que te proponga una corrección?"
)


def median_pitch(audio, sample_rate):
    """Tono medio aproximado por autocorrelación en los tramos con voz."""
    frame = int(0.04 * sample_rate)
    low, high = int(sample_rate / 400), int(sample_rate / 70)
    pitches = []

    for start in range(0, len(audio) - frame, frame):
        chunk = audio[start:start + frame]

        if np.sqrt(np.mean(chunk ** 2)) < 0.03:
            continue

        corr = np.correlate(chunk, chunk, mode="full")[frame - 1:]
        lag = low + int(np.argmax(corr[low:high]))

        if corr[lag] > 0.3 * corr[0]:
            pitches.append(sample_rate / lag)

    return float(np.median(pitches)) if pitches else None


def speakers_of(voice_path):
    config = json.loads(voice_path.with_suffix(".onnx.json").read_text(encoding="utf-8"))
    names = config.get("speaker_id_map") or {}
    return list(names.items()) or [(None, None)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voz", help="solo esta voz (nombre del .onnx sin extensión)")
    parser.add_argument("--frase", default=PHRASE)
    parser.add_argument("--sin-audio", action="store_true", help="no reproduce, solo mide")
    args = parser.parse_args()

    from piper import PiperVoice, SynthesisConfig

    voices = sorted(VOICES.glob("*.onnx"))

    if args.voz:
        voices = [v for v in voices if v.stem == args.voz]

    if not voices:
        print(f"No hay voces en {VOICES}.")
        return 1

    for voice_path in voices:
        start = time.perf_counter()
        voice = PiperVoice.load(voice_path)
        loaded = time.perf_counter() - start

        for name, speaker_id in speakers_of(voice_path):
            label = voice_path.stem + (f" (hablante {name})" if name else "")
            start = time.perf_counter()
            chunks = list(voice.synthesize(args.frase, syn_config=SynthesisConfig(speaker_id=speaker_id)))
            synth = time.perf_counter() - start
            audio = np.concatenate([c.audio_float_array for c in chunks])
            rate = chunks[0].sample_rate
            seconds = len(audio) / rate
            pitch = median_pitch(audio, rate)
            pitch_text = f"{pitch:.0f} Hz" if pitch else "?"

            print(f"\n{label}: carga {loaded:.1f} s, generada en {synth:.1f} s para {seconds:.1f} s de audio "
                  f"(x{seconds / synth:.1f} tiempo real), tono medio {pitch_text}", flush=True)

            if not args.sin_audio:
                import sounddevice as sd

                sd.play(audio, rate)
                sd.wait()
                time.sleep(0.5)

    return 0


if __name__ == "__main__":
    sys.exit(main())
