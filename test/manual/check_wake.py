"""Palabra de activación (fase J3) con openWakeWord y el micrófono real.

Aciertos: dices la frase de activación cuando lo pide, una vez por intento, y
cuenta en cuántos intentos se activa (y con qué puntuación máxima).

    .venv\\Scripts\\python.exe test\\manual\\check_wake.py --aciertos 20

Falsas activaciones: escucha los minutos que digas sin que la llames (habla
normal, música, la tele...) y cuenta cuántas veces se activa; da la tasa por hora.

    .venv\\Scripts\\python.exe test\\manual\\check_wake.py --falsas 30

Por defecto, lo de "voice" en la configuración (voice.wake_word, voice.wake_threshold,
voice.wake_vad_threshold, los modelos de voice.wake_models_dir). --modelo cambia el
.onnx ("Oye Asia", más adelante), --umbral la puntuación desde la que cuenta y --vad
el umbral del VAD de openWakeWord (0 lo apaga). --guardar escribe el resultado en
JSON. Solo carga openWakeWord: ni Whisper ni Ollama. El audio no se guarda en disco.
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

from config.settings_manager import SettingsManager
from core.voice import voice_settings
from core.voice.wake import CHUNK, Activations, Chunker, load_model as load_wake_model, missing, wake_config

TRIAL_S = 4.0


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
    parser.add_argument("--modelo", help="nombre de un .onnx de voice.wake_models_dir o su ruta (voice.wake_word)")
    parser.add_argument("--umbral", type=float, help="puntuación desde la que cuenta (voice.wake_threshold)")
    parser.add_argument("--vad", type=float, help="umbral del VAD de openWakeWord (voice.wake_vad_threshold; 0 lo apaga)")
    parser.add_argument("--guardar", type=Path, help="JSON con el resultado")
    args = parser.parse_args()

    if not args.aciertos and not args.falsas:
        parser.error("di --aciertos INTENTOS o --falsas MINUTOS")

    config = config_for(args.modelo, args.vad)
    threshold = args.umbral if args.umbral is not None else wake_config(config)["wake_threshold"]
    model = load_model(config)

    if model is None:
        print(missing(config) or "No pude cargar el modelo de openWakeWord.")
        return 2

    result = {"modelo": config["wake_word"], "umbral": threshold, "vad": config["wake_vad_threshold"]}

    if args.aciertos:
        result["aciertos"] = hits(model, args.aciertos, threshold)

    if args.falsas:
        result["falsas"] = false_alarms(model, args.falsas, threshold)

    if args.guardar:
        args.guardar.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
