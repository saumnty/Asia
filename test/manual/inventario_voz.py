"""Inventario de audios para una voz propia (solo lectura).

    .venv\\Scripts\\python.exe test\\manual\\inventario_voz.py --carpeta <ruta> [--salida inventario.csv]

Por archivo: formato, duración, frecuencia de muestreo, canales, pico y RMS en
dBFS, % de muestras saturadas (|x| >= 0,99) y voz neta con el Silero VAD de
faster-whisper (segundos de voz y tramos). Decodifica con PyAV (lo trae
faster-whisper); lo que no se pueda leer se lista con el error. Al final, un
resumen por subcarpeta y el total. Los archivos solo se leen.

Voz neta: el VAD a 16 kHz mono, umbral 0,5, sin relleno alrededor de la voz
(speech_pad_ms 0) y uniendo pausas de menos de 0,5 s. Un archivo cuenta como
saturado si al menos el 0,1 % de sus muestras llega a |x| >= 0,99.
"""
import argparse
import csv
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

# Audio y vídeo (los vídeos de WhatsApp traen la voz en su pista de audio).
MEDIA_EXTENSIONS = {".opus", ".ogg", ".oga", ".m4a", ".mp3", ".aac", ".amr", ".wav", ".flac", ".wma",
                    ".mp4", ".3gp", ".webm", ".mov", ".mkv"}
SATURATED = 0.99
SATURATED_SHARE = 0.1  # % de muestras para contar el archivo como saturado
VAD_RATE = 16000
SILENCE_DBFS = -120.0
COLUMNS = ["archivo", "subcarpeta", "formato", "codec", "segundos", "hz", "canales", "pico_dbfs", "rms_dbfs",
           "saturadas_pct", "voz_s", "tramos_voz", "error"]


@dataclass
class Row:
    archivo: str
    subcarpeta: str
    formato: str = ""
    codec: str = ""
    segundos: float = 0.0
    hz: int = 0
    canales: int = 0
    pico_dbfs: float = SILENCE_DBFS
    rms_dbfs: float = SILENCE_DBFS
    saturadas_pct: float = 0.0
    voz_s: float = 0.0
    tramos_voz: int = 0
    error: str = ""

    @property
    def saturado(self) -> bool:
        return not self.error and self.saturadas_pct >= SATURATED_SHARE


@dataclass
class Totals:
    archivos: int = 0
    segundos: float = 0.0
    voz_s: float = 0.0
    saturados: int = 0
    ilegibles: int = 0
    nombres_ilegibles: list = field(default_factory=list)

    def add(self, row: Row):
        self.archivos += 1

        if row.error:
            self.ilegibles += 1
            self.nombres_ilegibles.append(row.archivo)
            return

        self.segundos += row.segundos
        self.voz_s += row.voz_s
        self.saturados += row.saturado


def dbfs(value: float) -> float:
    return round(max(20 * np.log10(value), SILENCE_DBFS), 1) if value > 0 else SILENCE_DBFS


def decode(path):
    """(muestras float32 de todos los canales, hz, canales, formato, codec) con PyAV."""
    import av

    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError("sin pista de audio")

        stream = container.streams.audio[0]
        rate, channels = stream.rate or stream.codec_context.sample_rate, stream.codec_context.channels
        resampler = av.AudioResampler(format="flt", layout=stream.layout.name, rate=rate)
        parts = []

        for frame in container.decode(stream):
            for converted in resampler.resample(frame):
                parts.append(converted.to_ndarray().reshape(-1))

        for converted in resampler.resample(None):
            parts.append(converted.to_ndarray().reshape(-1))

        samples = np.concatenate(parts).astype(np.float32) if parts else np.zeros(0, dtype=np.float32)
        return samples, rate, channels, container.format.name, stream.codec_context.name


def to_vad_audio(samples, rate, channels) -> np.ndarray:
    """Mono a 16 kHz para el VAD (interpolación lineal: basta para decidir dónde hay voz)."""
    mono = samples.reshape(-1, channels).mean(axis=1) if channels > 1 else samples

    if rate == VAD_RATE or not len(mono):
        return mono.astype(np.float32)

    count = int(round(len(mono) * VAD_RATE / rate))
    return np.interp(np.linspace(0, len(mono) - 1, count), np.arange(len(mono)), mono).astype(np.float32)


def silero_segments(audio) -> list:
    """[(inicio, fin)] en muestras a 16 kHz, con el Silero VAD de faster-whisper."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(threshold=0.5, speech_pad_ms=0, min_silence_duration_ms=500)
    return [(segment["start"], segment["end"]) for segment in get_speech_timestamps(audio, options)]


def inventory_row(path, root, decoder=decode, segments=silero_segments) -> Row:
    sub = path.parent.relative_to(root).as_posix()
    row = Row(archivo=path.name, subcarpeta="." if sub in ("", ".") else sub)

    try:
        samples, rate, channels, row.formato, row.codec = decoder(path)
    except Exception as e:  # PyAV da varios tipos de error según el formato
        row.formato = path.suffix.lower().lstrip(".")
        row.error = f"{type(e).__name__}: {e}"[:200]
        return row

    row.hz, row.canales = int(rate), int(channels)
    row.segundos = round(len(samples) / channels / rate, 2) if rate and channels else 0.0

    if len(samples):
        magnitude = np.abs(samples)
        row.pico_dbfs = dbfs(float(magnitude.max()))
        row.rms_dbfs = dbfs(float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))))
        row.saturadas_pct = round(float(np.mean(magnitude >= SATURATED)) * 100, 3)
        found = segments(to_vad_audio(samples, rate, channels))
        row.voz_s = round(sum(end - start for start, end in found) / VAD_RATE, 2)
        row.tramos_voz = len(found)

    return row


def media_files(root):
    """(audios y vídeos, {extensión: cuántos} de lo que se salta)."""
    media, skipped = [], {}

    for path in sorted(Path(root).rglob("*")):
        if not path.is_file():
            continue

        extension = path.suffix.lower()

        if extension in MEDIA_EXTENSIONS:
            media.append(path)
        else:
            skipped[extension or "(sin extensión)"] = skipped.get(extension or "(sin extensión)", 0) + 1

    return media, skipped


def inventory(root, decoder=decode, segments=silero_segments):
    """(filas, {subcarpeta: Totals}, Totals del total, lo que se saltó)."""
    root = Path(root)
    files, skipped = media_files(root)
    rows = [inventory_row(path, root, decoder, segments) for path in files]
    by_folder, total = {}, Totals()

    for row in rows:
        by_folder.setdefault(row.subcarpeta, Totals()).add(row)
        total.add(row)

    return rows, by_folder, total, skipped


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=COLUMNS)
        writer.writeheader()

        for row in rows:
            writer.writerow(asdict(row))


def totals_line(name, totals) -> str:
    return (f"{name}: {totals.archivos} archivos, {totals.segundos / 60:.1f} min, voz neta {totals.voz_s / 60:.1f} min, "
            f"{totals.saturados} saturados" + (f", {totals.ilegibles} sin leer" if totals.ilegibles else ""))


def summary(by_folder, total, skipped) -> str:
    lines = [totals_line(name, totals) for name, totals in sorted(by_folder.items())]
    lines.append(totals_line("Total", total))

    if total.nombres_ilegibles:
        lines.append("Sin leer (PyAV no pudo decodificarlos): " + ", ".join(total.nombres_ilegibles))

    if skipped:
        lines.append("Saltados (no son audio ni vídeo): " + ", ".join(f"{ext} {n}" for ext, n in sorted(skipped.items())))

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--carpeta", type=Path, required=True, help="carpeta con los audios (solo se lee)")
    parser.add_argument("--salida", type=Path, help="CSV con una fila por archivo")
    args = parser.parse_args()

    if not args.carpeta.is_dir():
        parser.error(f"no existe la carpeta {args.carpeta}")

    rows, by_folder, total, skipped = inventory(args.carpeta)

    for row in rows:
        detail = row.error or (f"{row.formato}/{row.codec}, {row.segundos:.1f} s, {row.hz} Hz, {row.canales} can., "
                               f"pico {row.pico_dbfs:.1f}, RMS {row.rms_dbfs:.1f} dBFS, saturadas {row.saturadas_pct:.2f} %, "
                               f"voz {row.voz_s:.1f} s en {row.tramos_voz} tramos")
        print(f"{row.subcarpeta}/{row.archivo}: {detail}")

    print()
    print(summary(by_folder, total, skipped))

    if args.salida:
        write_csv(rows, args.salida)
        print(f"\nCSV: {args.salida}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
