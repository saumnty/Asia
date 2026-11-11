"""Voz propia: dataset final para Piper con las frases aceptadas en revisar.html.

    .venv\\Scripts\\python.exe test\\manual\\dataset_final.py --dataset <carpeta de preparar_voz>
        --metadata <metadata.csv exportado> [--revision <revision.json>] --destino <carpeta nueva>

- Solo las frases aceptadas, con el texto corregido en la página (metadata.csv;
  revision.json, si se da, se usa para avisar de lo que no cuadre entre los dos).
- Recorta el silencio de los extremos con el Silero VAD de faster-whisper, dejando
  PAD_S, y normaliza el pico a PEAK_DBFS (una ganancia, sin compresión).
- Dos versiones, 22 050 y 16 000 Hz, cada una con wavs/NNNN.wav y metadata.csv
  (NNNN.wav|texto, como lo lee piper1-gpl), y un zip por versión, listo para subir a Colab.
- --frecuencias 22050 deja una sola versión; --silencios atenuados baja las pausas de
  dentro de la frase (no las de los extremos) ATTENUATION_DB, con rampas de FADE_S.
- --reemplazos <csv> cambia el texto de las frases por la columna "final" (id, final): el
  numeros_a_palabras.csv corregido a mano. Acepta , ; o tabulador (Excel) y ids sin los ceros
  de la izquierda; un "final" vacío o un id que no existe se avisa y se deja el texto original.
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
ATTENUATION_DB = -24.0  # las pausas largas de dentro de la frase quedan 24 dB más bajas
MIN_PAUSE_S = 0.35      # pausas más cortas que esto se dejan: son parte del ritmo de la frase
PAUSE_MARGIN_S = 0.10   # no se toca lo que rodea a la voz, para no comerse el ataque ni la cola
FADE_S = 0.03
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


def read_replacements(path, ids=()) -> tuple:
    """({id: texto}, avisos) de un CSV con las columnas id y final (las demás se ignoran).

    ids: los de metadata.csv; sirven para devolver los ceros que Excel quita ("5" -> "0005")."""
    text = Path(path).read_text(encoding="utf-8-sig")
    first = text.splitlines()[0] if text.strip() else ""
    delimiter = max(",;\t", key=first.count)
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    reader.fieldnames = [name.strip().lower() for name in reader.fieldnames or []]

    if "id" not in reader.fieldnames or "final" not in reader.fieldnames:
        raise ValueError(f"{path}: el CSV necesita las columnas id y final")

    width = len(next(iter(sorted(ids)), ""))
    found, notes = {}, []

    for row in reader:
        id_ = (row["id"] or "").strip()

        if id_.isdigit() and id_ not in ids and width:
            id_ = id_.zfill(width)

        final = clean_text(row["final"] or "")

        if not final:
            notes.append(f"{id_}: la columna final está vacía, se deja el texto original")
        else:
            found[id_] = final

    return found, notes


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


def attenuate_silences(audio, rate, segments=silero_segments, db=ATTENUATION_DB) -> np.ndarray:
    """audio con las pausas largas de dentro de la frase atenuadas db decibelios (no se recorta nada)."""
    found = segments(resample(audio, rate, VAD_RATE))
    gain = np.ones(len(audio), dtype=np.float32)
    quiet = 10 ** (db / 20)

    for (_, end), (start, _) in zip(found, found[1:]):
        low = int(end * rate / VAD_RATE + PAUSE_MARGIN_S * rate)
        high = int(start * rate / VAD_RATE - PAUSE_MARGIN_S * rate)

        if (start - end) / VAD_RATE >= MIN_PAUSE_S and high > low:
            gain[low:high] = quiet

    fade = max(1, int(FADE_S * rate))
    padded = np.pad(gain, (fade // 2, fade - 1 - fade // 2), mode="edge")  # sin atenuar los bordes
    return audio * np.convolve(padded, np.ones(fade, dtype=np.float32) / fade, mode="valid")


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


def build(dataset, metadata, destination, revision=None, segments=silero_segments, log=print,
          rates=RATES, quiet=False, replacements=None, replacement_notes=()) -> dict:
    """Escribe las versiones (rates) y sus zip en destination; devuelve el resumen.

    quiet: atenúa las pausas de dentro de la frase (attenuate_silences).
    replacements: {id: texto} que sustituye al de metadata.csv (read_replacements)."""
    dataset, destination = Path(dataset), Path(destination)
    notes = mismatches(metadata, revision) if revision is not None else []
    items, skipped = [], []
    replacements = replacements or {}
    replaced = 0
    replacement_notes = list(replacement_notes)
    replacement_notes += [f"{id_}: no está en metadata.csv, no se usa" for id_ in sorted(set(replacements) - set(metadata))]

    for version in rates:
        (destination / str(version) / "wavs").mkdir(parents=True, exist_ok=True)

    for id_ in sorted(metadata):
        text = clean_text(replacements.get(id_, metadata[id_]))
        replaced += id_ in replacements and text != clean_text(metadata[id_])

        if not text:
            skipped.append(f"{id_}: texto vacío, no entra")
            continue

        source = dataset / "wavs" / f"{id_}.wav"

        if not source.exists():
            skipped.append(f"{id_}: falta {source.name} en el dataset")
            continue

        audio, rate = read_wav(source)
        audio = trim(audio, rate, segments)
        audio = attenuate_silences(audio, rate, segments) if quiet else audio
        item = Item(id_, text, round(len(audio) / rate, 2), text_warnings(text))

        if not MIN_S <= item.seconds <= MAX_S:
            item.warnings.append(f"dura {item.seconds:.2f} s (fuera de {MIN_S:g}–{MAX_S:g} s)")

        for version in rates:
            write_wav(destination / str(version) / "wavs" / f"{id_}.wav", normalize(resample(audio, rate, version)), version)

        items.append(item)

    for version in rates:
        folder = destination / str(version)
        # piper1-gpl lee el nombre del archivo en la primera columna (wavs/0001.wav -> "0001.wav").
        (folder / "metadata.csv").write_text("".join(f"{item.id}.wav|{item.text}\n" for item in items), encoding="utf-8")

        with zipfile.ZipFile(destination / f"{destination.name}_{version}.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(folder / "metadata.csv", "metadata.csv")

            for item in items:
                archive.write(folder / "wavs" / f"{item.id}.wav", f"wavs/{item.id}.wav")

    result = {
        "frases": len(items), "minutos": sum(item.seconds for item in items) / 60,
        "distribucion": distribution([item.seconds for item in items]),
        "avisos": [f"{item.id}: {warning}" for item in items for warning in item.warnings],
        "fuera": skipped, "no_cuadra": notes, "reemplazados": replaced, "reemplazos_avisos": replacement_notes,
        "zips": {version: (destination / f"{destination.name}_{version}.zip").stat().st_size for version in rates},
    }
    (destination / "resumen.txt").write_text(summary(result) + "\n", encoding="utf-8")
    return result


def summary(result) -> str:
    lines = [f"Frases: {result['frases']}; {result['minutos']:.1f} min (tras recortar los silencios de los extremos).",
             "Duraciones:"]
    lines += [f"  {label}: {count}" for label, count in result["distribucion"]]
    lines += [f"Zip de {version} Hz: {size / 1e6:.1f} MB" for version, size in result["zips"].items()]

    if result["reemplazados"]:
        lines.append(f"Textos reemplazados: {result['reemplazados']}")

    for title, key in (("Avisos (revisar el texto o el audio)", "avisos"), ("No entran", "fuera"),
                       ("metadata.csv y revision.json no cuadran", "no_cuadra"),
                       ("Reemplazos con problemas", "reemplazos_avisos")):
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
    parser.add_argument("--frecuencias", type=int, nargs="+", default=list(RATES), choices=RATES,
                        help="22050 para el fine-tuning de Piper; por defecto, las dos")
    parser.add_argument("--silencios", choices=("normal", "atenuados"), default="normal",
                        help="atenuados: las pausas de dentro de la frase bajan %g dB" % ATTENUATION_DB)
    parser.add_argument("--reemplazos", type=Path, help="CSV con id y final: el texto que sustituye al de metadata.csv")
    args = parser.parse_args()

    if args.destino.exists() and any(args.destino.iterdir()):
        parser.error(f"{args.destino} ya tiene archivos; usa una carpeta nueva")

    if args.destino.resolve() == args.dataset.resolve():
        parser.error("--destino no puede ser la carpeta del dataset")

    revision = read_revision(args.revision) if args.revision else None
    metadata = read_metadata(args.metadata)
    replacements, notes = read_replacements(args.reemplazos, metadata) if args.reemplazos else ({}, [])
    result = build(args.dataset, metadata, args.destino, revision, rates=tuple(args.frecuencias),
                   quiet=args.silencios == "atenuados", replacements=replacements, replacement_notes=notes)
    print(summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
