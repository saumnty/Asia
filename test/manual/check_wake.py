"""Palabra de activación (fase J3) con openWakeWord y el micrófono real.

Aciertos: dices la frase de activación cuando lo pide, una vez por intento, y
cuenta en cuántos intentos se activa (y con qué puntuación máxima).

    .venv\\Scripts\\python.exe test\\manual\\check_wake.py --aciertos 20

Falsas activaciones: escucha los minutos que digas sin que la llames (habla
normal, música, la tele...) y cuenta cuántas veces se activa; da la tasa por hora.

    .venv\\Scripts\\python.exe test\\manual\\check_wake.py --falsas 30

--modelo es el nombre de un modelo de openWakeWord (hey_jarvis, por defecto) o la
ruta de un .onnx propio ("Oye Asia", más adelante); --umbral, la puntuación desde la
que cuenta (0,5 por defecto). --guardar escribe el resultado en JSON. Solo carga
openWakeWord: ni Whisper ni Ollama. El audio no se guarda en disco.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.voice.audio import SAMPLE_RATE, Microphone

# openWakeWord trabaja con tramos de 80 ms en int16; el micrófono da 512 muestras float32.
CHUNK = 1280
DEFAULT_MODEL = "hey_jarvis"
DEFAULT_THRESHOLD = 0.5
# Una frase dispara varios tramos seguidos: cuenta una activación cada REFRACTORY_S.
REFRACTORY_S = 2.0
TRIAL_S = 4.0
MISSING = (
    "Falta openwakeword: no está instalado (fase J3, pendiente de confirmar la instalación).\n"
    "    .venv\\Scripts\\python.exe -m pip install openwakeword==0.6.0"
)


class Chunker:
    """Junta los tramos del micrófono (float32, 512) en tramos de CHUNK muestras int16."""

    def __init__(self, size=CHUNK):
        self.size = size
        self.pending = np.zeros(0, dtype=np.int16)

    def feed(self, frame) -> list:
        samples = np.clip(np.asarray(frame, dtype=np.float32), -1.0, 1.0)
        self.pending = np.concatenate([self.pending, (samples * 32767).astype(np.int16)])
        chunks = []

        while len(self.pending) >= self.size:
            chunks.append(self.pending[:self.size])
            self.pending = self.pending[self.size:]

        return chunks


class Activations:
    """Las veces que la puntuación pasa el umbral, una por REFRACTORY_S de audio como mucho."""

    def __init__(self, threshold=DEFAULT_THRESHOLD, refractory_s=REFRACTORY_S, chunk_s=CHUNK / SAMPLE_RATE):
        self.threshold = threshold
        self.refractory_s = refractory_s
        self.chunk_s = chunk_s
        self.elapsed = 0.0
        self.last = None
        self.times = []
        self.peak = 0.0

    def feed(self, score: float) -> bool:
        self.peak = max(self.peak, score)
        now = self.elapsed
        self.elapsed += self.chunk_s

        if score < self.threshold or self.last is not None and now - self.last < self.refractory_s:
            return False

        self.last = now
        self.times.append(now)
        return True


def per_hour(count: int, seconds: float) -> float:
    return count * 3600 / seconds if seconds else 0.0


def load_model(name):
    """El modelo de openWakeWord con ONNX (en Windows no hay tflite); None si falta el paquete."""
    try:
        from openwakeword.model import Model
    except ImportError:
        return None

    return Model(wakeword_models=[name], inference_framework="onnx")


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


def hits(model, trials, threshold):
    rows = []

    for trial in range(1, trials + 1):
        input(f"[{trial}/{trials}] Enter y di la frase de activación ({TRIAL_S:.0f} s)… ")
        model.reset()
        found = Activations(threshold)

        with Microphone().open() as stream:
            fired = any([found.feed(score) for score in scores(model, stream, TRIAL_S)])

        rows.append({"intento": trial, "activó": fired, "puntuación máxima": round(found.peak, 3)})
        print(f"    {'sí' if fired else 'no'} (máxima {found.peak:.2f})", flush=True)

    right = sum(row["activó"] for row in rows)
    print(f"\nAciertos: {right}/{trials} con umbral {threshold}.")
    return {"aciertos": right, "intentos": trials, "filas": rows}


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--aciertos", type=int, metavar="INTENTOS", help="intentos diciendo la frase de activación")
    parser.add_argument("--falsas", type=float, metavar="MINUTOS", help="minutos escuchando sin llamarla")
    parser.add_argument("--modelo", default=DEFAULT_MODEL, help="nombre de openWakeWord o ruta de un .onnx")
    parser.add_argument("--umbral", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--guardar", type=Path, help="JSON con el resultado")
    args = parser.parse_args()

    if not args.aciertos and not args.falsas:
        parser.error("di --aciertos INTENTOS o --falsas MINUTOS")

    model = load_model(args.modelo)

    if model is None:
        print(MISSING)
        return 2

    result = {"modelo": args.modelo, "umbral": args.umbral}

    if args.aciertos:
        result["aciertos"] = hits(model, args.aciertos, args.umbral)

    if args.falsas:
        result["falsas"] = false_alarms(model, args.falsas, args.umbral)

    if args.guardar:
        args.guardar.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
