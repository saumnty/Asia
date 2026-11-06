"""Voz propia: dataset final para Piper con las frases aceptadas en revisar.html.

    .venv\\Scripts\\python.exe test\\manual\\dataset_final.py --dataset <carpeta de preparar_voz>
        --metadata <metadata.csv exportado> [--revision <revision.json>] --destino <carpeta nueva>

- Solo las frases aceptadas, con el texto corregido en la página (metadata.csv;
  revision.json, si se da, se usa para avisar de lo que no cuadre entre los dos).
- Recorta el silencio de los extremos con el Silero VAD de faster-whisper, dejando
  PAD_S, y normaliza el pico a PEAK_DBFS (una ganancia, sin compresión).
- Dos versiones, 22 050 y 16 000 Hz, cada una con wavs/NNNN.wav y metadata.csv
  (id|texto, formato LJSpeech), y un zip por versión, listo para subir a Colab.
- Avisa de dígitos (deben ir en letra), símbolos raros y duraciones fuera de
  1–15 s; las frases vacías no entran. Escribe resumen.txt.

En --dataset no se escribe nada.
"""
import argparse
import csv
import json
import re
import sys
import wave
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

RATES = (22050, 16000)
VAD_RATE = 16000
PEAK_DBFS = -3.0
PAD_S = 0.15  # entre 0,1 y 0,2 s de silencio en cada extremo
MIN_S, MAX_S = 1.0, 15.0
# Letras (con acentos y ñ), espacios y la puntuación normal del español.
ALLOWED = re.compile(r"[\wáéíóúüñÁÉÍÓÚÜÑ\s.,;:¿?¡!'\"()\-…]")
BINS = [(0, 1), (1, 2), (2, 4), (4, 6), (6, 10), (10, 15), (15, None)]


@dataclass
class Item:
    id: str
    text: str
    seconds: float = 0.0
    warnings: list = field(default_factory=list)


def read_metadata(path) -> dict:
    """{id: texto} de un metadata.csv id|texto (el de revisar.html)."""
    rows = {}

    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            id_, _, text = line.partition("|")
            rows[id_.strip()] = text

    return rows


def read_revision(path) -> dict:
    """{id: {"estado", "texto"}} de revision.json."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def mismatches(metadata, revision) -> list:
    """Lo que no cuadra entre metadata.csv y revision.json (por si uno de los dos es viejo)."""
    accepted = {id_ for id_, row in revision.items() if row.get("estado") == "aceptada"}
    notes = [f"{id_}: aceptada en revision.json pero no está en metadata.csv" for id_ in sorted(accepted - set(metadata))]
    notes += [f"{id_}: en metadata.csv pero no aceptada en revision.json" for id_ in sorted(set(metadata) - accepted)]
    notes += [f"{id_}: el texto de metadata.csv y el de revision.json no coinciden" for id_ in sorted(set(metadata) & accepted)
              if " ".join(metadata[id_].split()) != " ".join(str(revision[id_].get("texto", "")).split())]
    return notes


def clean_text(text) -> str:
    return " ".join(str(text).replace("|", " ").split())


def text_warnings(text) -> list:
    warnings = []

    if re.search(r"\d", text):
        warnings.append("dígitos: van en letra")

    odd = sorted({char for char in text if not ALLOWED.fullmatch(char)})

    if odd:
        warnings.append("símbolos raros: " + " ".join(odd))

    return warnings


def read_wav(path) -> tuple:
    with wave.open(str(path), "rb") as source:
        rate, width, channels = source.getframerate(), source.getsampwidth(), source.getnchannels()
        data = source.readframes(source.getnframes())

    if width != 2 or channels != 1:
        raise ValueError(f"{Path(path).name}: se esperaba mono de 16 bits")

    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32767, rate


def resample(audio, source_rate, target_rate) -> np.ndarray:
    if source_rate == target_rate:
        return audio.astype(np.float32)

    from math import gcd

    from scipy.signal import resample_poly

    common = gcd(source_rate, target_rate)
    return resample_poly(audio, target_rate // common, source_rate // common).astype(np.float32)


def silero_segments(audio16) -> list:
    """[(inicio, fin)] de voz en muestras a 16 kHz, con el Silero VAD de faster-whisper."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(threshold=0.5, min_silence_duration_ms=300, speech_pad_ms=0)
    return [(segment["start"], segment["end"]) for segment in get_speech_timestamps(audio16, options)]


def trim(audio, rate, segments=silero_segments, pad_s=PAD_S) -> np.ndarray:
    """audio sin el silencio de los extremos, con pad_s antes de la primera voz y después de la última."""
    found = segments(resample(audio, rate, VAD_RATE))

    if not found:
        return audio

    start = max(0, int(found[0][0] * rate / VAD_RATE - pad_s * rate))
    end = min(len(audio), int(found[-1][1] * rate / VAD_RATE + pad_s * rate))
    return audio[start:end]


def normalize(audio, peak_dbfs=PEAK_DBFS) -> np.ndarray:
    """Una sola ganancia hasta que el pico quede en peak_dbfs: sin compresión ni limitador."""
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    return audio * (10 ** (peak_dbfs / 20) / peak) if peak else audio


def write_wav(path, audio, rate):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes())


def distribution(seconds) -> list:
    rows = []

    for low, high in BINS:
        count = sum(1 for s in seconds if s >= low and (high is None or s < high))
        rows.append((f"{low}–{high} s" if high is not None else f"{low} s o más", count))

    return rows


def build(dataset, metadata, destination, revision=None, segments=silero_segments, log=print) -> dict:
    """Escribe las dos versiones y sus zip en destination; devuelve el resumen."""
    dataset, destination = Path(dataset), Path(destination)
    notes = mismatches(metadata, revision) if revision is not None else []
    items, skipped = [], []

    for version in RATES:
        (destination / str(version) / "wavs").mkdir(parents=True, exist_ok=True)

    for id_ in sorted(metadata):
        text = clean_text(metadata[id_])

        if not text:
            skipped.append(f"{id_}: texto vacío, no entra")
            continue

        source = dataset / "wavs" / f"{id_}.wav"

        if not source.exists():
            skipped.append(f"{id_}: falta {source.name} en el dataset")
            continue

        audio, rate = read_wav(source)
        audio = trim(audio, rate, segments)
        item = Item(id_, text, round(len(audio) / rate, 2), text_warnings(text))

        if not MIN_S <= item.seconds <= MAX_S:
            item.warnings.append(f"dura {item.seconds:.2f} s (fuera de {MIN_S:g}–{MAX_S:g} s)")

        for version in RATES:
            write_wav(destination / str(version) / "wavs" / f"{id_}.wav", normalize(resample(audio, rate, version)), version)

        items.append(item)

    for version in RATES:
        folder = destination / str(version)
        (folder / "metadata.csv").write_text("".join(f"{item.id}|{item.text}\n" for item in items), encoding="utf-8")

        with zipfile.ZipFile(destination / f"{destination.name}_{version}.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(folder / "metadata.csv", "metadata.csv")

            for item in items:
                archive.write(folder / "wavs" / f"{item.id}.wav", f"wavs/{item.id}.wav")

    result = {
        "frases": len(items), "minutos": sum(item.seconds for item in items) / 60,
        "distribucion": distribution([item.seconds for item in items]),
        "avisos": [f"{item.id}: {warning}" for item in items for warning in item.warnings],
        "fuera": skipped, "no_cuadra": notes,
        "zips": {version: (destination / f"{destination.name}_{version}.zip").stat().st_size for version in RATES},
    }
    (destination / "resumen.txt").write_text(summary(result) + "\n", encoding="utf-8")
    return result


def summary(result) -> str:
    lines = [f"Frases: {result['frases']}; {result['minutos']:.1f} min (tras recortar los silencios de los extremos).",
             "Duraciones:"]
    lines += [f"  {label}: {count}" for label, count in result["distribucion"]]
    lines += [f"Zip de {version} Hz: {size / 1e6:.1f} MB" for version, size in result["zips"].items()]

    for title, key in (("Avisos (revisar el texto o el audio)", "avisos"), ("No entran", "fuera"),
                       ("metadata.csv y revision.json no cuadran", "no_cuadra")):
        if result[key]:
            lines.append(f"{title}: {len(result[key])}")
            lines += [f"  {line}" for line in result[key]]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True, help="la carpeta de preparar_voz (wavs/); solo se lee")
    parser.add_argument("--metadata", type=Path, required=True, help="el metadata.csv exportado de revisar.html")
    parser.add_argument("--revision", type=Path, help="el revision.json exportado de revisar.html")
    parser.add_argument("--destino", type=Path, required=True, help="carpeta nueva del dataset final")
    args = parser.parse_args()

    if args.destino.exists() and any(args.destino.iterdir()):
        parser.error(f"{args.destino} ya tiene archivos; usa una carpeta nueva")

    if args.destino.resolve() == args.dataset.resolve():
        parser.error("--destino no puede ser la carpeta del dataset")

    revision = read_revision(args.revision) if args.revision else None
    result = build(args.dataset, read_metadata(args.metadata), args.destino, revision)
    print(summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
