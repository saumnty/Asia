"""Compara modelos de "Oye Asia" con frases de Piper, por el camino del micrófono (sin micrófono).

    .venv\\Scripts\\python.exe test\\manual\\comparar_wake.py --modelo oye_asia_v0.1 --modelo oye_asia_v0.2

Por cada caso y cada voz (claude-high y los dos hablantes de sharvard), la puntuación
máxima tras calentar el modelo (core/voice/wake.py, warmup_chunks) con el fondo del
caso: "oye Asia" sola, con frase detrás y con frase delante, y "hoy hacia" (que
engañaba al v0.1) sin fondo y con fondo de ruido. Lo que debe activarse, alto; lo
que no, bajo. Carga Piper y openWakeWord; ni Whisper ni Ollama.

Con grabaciones reales (--audios CARPETA), los mismos audios para todos los modelos:
los intento_*.wav de `check_wake --aciertos 20 --guardar-audio CARPETA` (cada uno con su
calentamiento) y los falsas_*.wav de `check_wake --falsas 30 --guardar-audio CARPETA`
(el cuarto sin llamarla). Por cada modelo y cada umbral de 0,05 a 0,95: aciertos y
falsas por hora; elige el umbral que cumple el criterio de cierre (17/20 aciertos y
≤ 0,5 falsas por hora) o, si ninguno, el que más se acerca:

    .venv\\Scripts\\python.exe test\\manual\\comparar_wake.py --audios data\\wake\\prueba --modelo oye_asia_v0.1 --modelo oye_asia_v0.2

Entre los umbrales que cumplen, el de más aciertos y, empatados, el más alto (más margen
contra las falsas). Si ninguno cumple, el de menor distancia: cada acierto que falta
cuenta 1 y cada 0,5 falsas por hora de más, también 1. Solo lee los WAV, sin micrófono.
Código de salida 0 si el elegido cumple, 1 si no.
"""
import argparse
import json
import math
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
from core.voice.wake import CHUNK, Activations, Chunker, reset_model, warmup_chunks  # noqa: E402

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


# --- Con grabaciones reales (--audios) -------------------------------------------

# Criterio de cierre de 1.0 (ROADMAP): 17 de 20 aciertos y ≤ 0,5 falsas por hora.
HIT_RATE = 17 / 20
MAX_PER_HOUR = 0.5
THRESHOLDS = [round(0.05 * step, 2) for step in range(1, 20)]


def needed_hits(attempts) -> int:
    return math.ceil(HIT_RATE * attempts - 1e-9)


def silence(chunks) -> list:
    return [np.zeros(CHUNK, dtype=np.int16)] * max(0, chunks)


def trace(model, chunks, skip) -> list:
    """Las puntuaciones de cada tramo int16 tras reiniciar el modelo, sin las skip primeras."""
    reset_model(model)
    return [max(model.predict(chunk).values(), default=0.0) for chunk in chunks][skip:]


def recorded(folder) -> tuple:
    """(intentos, sin llamarla): los tramos int16 de cada intento_*.wav y de cada falsas_*.wav."""
    import check_wake

    def load(pattern):
        return [check_wake.split_chunks(check_wake.read_wav(path)) for path in sorted(Path(folder).glob(pattern))]

    return load("intento_*.wav"), load("falsas_*.wav")


def score_recordings(model, positives, negatives) -> dict:
    """{"picos": la máxima de cada intento tras su calentamiento, "falsas": las puntuaciones sin llamarla}.

    Como check_wake --repuntuar: cada intento trae su calentamiento (check_wake.recorded_warmup); si el
    modelo pide más, se completa con silencio delante. Lo grabado sin llamarla cuenta entero, tras
    calentar con silencio.
    """
    import check_wake

    peaks = []

    for chunks in positives:
        warm = check_wake.recorded_warmup(chunks)
        padding = silence(warmup_chunks(model) - warm)
        peaks.append(max(trace(model, padding + chunks, len(padding) + warm), default=0.0))

    lead = silence(warmup_chunks(model))
    quiet = [trace(model, lead + chunks, len(lead)) for chunks in negatives]
    return {"picos": peaks, "falsas": quiet}


def sweep(scored, thresholds=THRESHOLDS) -> list:
    """Por umbral: aciertos, intentos, falsas, horas sin llamarla y falsas por hora (None sin horas)."""
    hours = sum(len(scores) for scores in scored["falsas"]) * CHUNK / RATE / 3600
    rows = []

    for threshold in thresholds:
        alarms = 0

        for scores in scored["falsas"]:
            found = Activations(threshold)

            for score in scores:
                found.feed(score)

            alarms += len(found.times)

        rows.append({
            "umbral": threshold,
            "aciertos": int(sum(bool(peak >= threshold) for peak in scored["picos"])),
            "intentos": len(scored["picos"]),
            "falsas": alarms,
            "horas": round(hours, 4),
            "por_hora": round(alarms / hours, 3) if hours else None,
        })

    return rows


def meets(row) -> bool:
    """17/20 (o la misma proporción) y ≤ 0,5 por hora; sin horas sin llamarla, no se puede decir que cumple."""
    if not row["intentos"] or row["por_hora"] is None:
        return False

    return row["aciertos"] >= needed_hits(row["intentos"]) and row["por_hora"] <= MAX_PER_HOUR


def distance(row) -> float:
    """0 si cumple. Cada acierto que falta cuenta 1; cada 0,5 falsas por hora de más, también 1."""
    missing_hits = max(0, needed_hits(row["intentos"]) - row["aciertos"])
    extra = max(0.0, (row["por_hora"] or 0.0) - MAX_PER_HOUR) / MAX_PER_HOUR
    return missing_hits + extra


def choose(rows) -> dict:
    """El umbral recomendado (ver el docstring del módulo)."""
    passing = [row for row in rows if meets(row)]

    if passing:
        return max(passing, key=lambda row: (row["aciertos"], row["umbral"]))

    return min(rows, key=lambda row: (distance(row), -row["aciertos"], -row["umbral"]))


def describe_row(row) -> str:
    rate = "sin medir" if row["por_hora"] is None else f"{row['por_hora']:.2f}/h"
    return f"{row['umbral']:.2f}: {row['aciertos']}/{row['intentos']} aciertos, {row['falsas']} falsas ({rate})"


def sweep_table(name, rows, chosen) -> str:
    minutes = rows[0]["horas"] * 60 if rows else 0
    lines = [f"\n{name} ({minutes:.1f} min sin llamarla)",
             f"{'umbral':>6}  {'aciertos':>8}  {'falsas':>6}  {'por hora':>8}  cumple"]

    for row in rows:
        rate = "—" if row["por_hora"] is None else f"{row['por_hora']:.2f}"
        arrow = "  ←" if row is chosen else ""
        lines.append(f"{row['umbral']:6.2f}  {row['aciertos']:>4}/{row['intentos']:<3}  {row['falsas']:>6}  {rate:>8}  "
                     f"{'sí' if meets(row) else 'no'}{arrow}")

    verdict = "cumple el criterio" if meets(chosen) else "no cumple; el que más se acerca"
    lines.append(f"Umbral recomendado: {describe_row(chosen)} ({verdict}).")
    return "\n".join(lines)


def best_model(choices) -> str:
    """El modelo cuyo umbral recomendado cumple, con más aciertos; si ninguno cumple, el más cercano."""
    return min(choices, key=lambda name: (not meets(choices[name]), distance(choices[name]),
                                          -choices[name]["aciertos"], choices[name]["por_hora"] or 0.0))


def compare_recordings(models, folder) -> tuple:
    """(texto, resultado) de --audios: cada modelo sobre los mismos WAV. ValueError si no hay intentos."""
    positives, negatives = recorded(folder)

    if not positives:
        raise ValueError(f"No hay intento_*.wav en {folder} (check_wake --aciertos 20 --guardar-audio {folder}).")

    texts, result, choices = [], {}, {}

    if not negatives:
        texts.append(f"Aviso: no hay falsas_*.wav en {folder}; sin falsas por hora ningún umbral cumple "
                     f"(check_wake --falsas 30 --guardar-audio {folder}).")

    for name, model in models.items():
        rows = sweep(score_recordings(model, positives, negatives))
        choices[name] = choose(rows)
        result[name] = {"umbrales": rows, "recomendado": choices[name]}
        texts.append(sweep_table(name, rows, choices[name]))

    best = best_model(choices)
    chosen = choices[best]
    result["elegido"] = {"modelo": best, **chosen}
    texts.append(f"\nElegido: {best}, umbral {chosen['umbral']:.2f} "
                 f"({'cumple' if meets(chosen) else 'no cumple'} el criterio). En config/defaults.json, dentro de \"voice\":\n"
                 f'  "wake_word": "{best.removesuffix(" (2)")}",\n  "wake_threshold": {chosen["umbral"]}')
    return "\n".join(texts), result


def load_models(names) -> dict:
    """{nombre: modelo}; el mismo nombre dos veces (v0.1 contra sí mismo) va como "nombre (2)".
    Devuelve el aviso (str) si falta algún modelo."""
    from core.voice.wake import load_model, missing

    models = {}

    for name in names:
        config = {**DEFAULT_VOICE_SETTINGS, "wake_word": name}

        if missing(config):
            return missing(config)

        models[name if name not in models else f"{name} (2)"] = load_model(config)

    return models


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modelo", action="append", help="un .onnx de voice.wake_models_dir (se puede repetir)")
    parser.add_argument("--audios", type=Path, metavar="CARPETA",
                        help="intento_*.wav y falsas_*.wav grabados con check_wake --guardar-audio")
    parser.add_argument("--guardar", type=Path, help="JSON con el resultado de --audios")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    models = load_models(args.modelo or ["oye_asia_v0.1"])

    if isinstance(models, str):
        print(models)
        return 2

    if args.audios:
        try:
            text, result = compare_recordings(models, args.audios)
        except ValueError as e:
            print(e)
            return 2

        print(text)

        if args.guardar:
            args.guardar.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

        return 0 if meets(result["elegido"]) else 1

    print(table(compare(models, piper_speaker()), models))
    return 0


if __name__ == "__main__":
    sys.exit(main())
