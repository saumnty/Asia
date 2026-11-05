"""Voz propia: segunda transcripción del dataset de preparar_voz con un modelo mejor.

    .venv\\Scripts\\python.exe test\\manual\\transcribir_turbo.py --dataset C:\\AsiaVoz\\dataset\\fa

Transcribe cada wavs/NNNN.wav con faster-whisper large-v3-turbo (data/models), en
CPU int8, language="es", beam_size 5, con las métricas de preparar_voz. Si las
primeras 20 frases tardan más de 2 veces lo que duran, se detiene y dice cuánto
tardaría todo, sin tocar nada; --sin-tope lo corre entero de todos modos.

Reescribe revisar.csv con, junto a cada frase, texto_small y texto_turbo, las
métricas de los dos, los motivos de "revisar" de cada uno y "coinciden"
(comparando sin mayúsculas, acentos ni puntuación). El revisar.csv de antes se
guarda como revisar_small.csv. metadata.csv no se toca.
"""
import argparse
import csv
import re
import shutil
import sys
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from preparar_voz import VAD_RATE, Phrase, WhisperTranscriber, review_reasons  # noqa: E402

MODEL = "large-v3-turbo"
PROBE = 20
MAX_SLOWDOWN = 2.0
METRICS = ["avg_logprob", "no_speech_prob", "compression_ratio"]
COLUMNS = ["id", "segundos", "coinciden",
           "texto_small", *(f"{m}_small" for m in METRICS), "revisar_small", "motivos_small",
           "texto_turbo", *(f"{m}_turbo" for m in METRICS), "revisar_turbo", "motivos_turbo",
           "pico_dbfs", "rms_dbfs", "saturadas_pct", "origen", "inicio_s"]


class TooSlow(Exception):
    def __init__(self, ratio, estimate_s):
        super().__init__(f"{ratio:.1f}× la duración del audio")
        self.ratio, self.estimate_s = ratio, estimate_s


def comparable(text: str) -> str:
    """Sin mayúsculas, acentos ni puntuación: "¿Está bien?" -> "esta bien"."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", text))


def read_16k(path) -> np.ndarray:
    """Un WAV mono de 16 bits del dataset, a 16 kHz para Whisper."""
    with wave.open(str(path), "rb") as source:
        rate = source.getframerate()
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32767

    if rate == VAD_RATE:
        return audio

    from math import gcd

    from scipy.signal import resample_poly

    common = gcd(VAD_RATE, rate)
    return resample_poly(audio, VAD_RATE // common, rate // common).astype(np.float32)


def read_rows(dataset) -> list:
    with open(Path(dataset) / "revisar.csv", encoding="utf-8-sig") as source:
        return list(csv.DictReader(source))


def phrase_from(row, text, logprob, no_speech, compression) -> Phrase:
    return Phrase(id=row["id"], origen=row["origen"], inicio_s=float(row["inicio_s"]), segundos=float(row["segundos"]),
                  texto=text, avg_logprob=logprob, no_speech_prob=no_speech, compression_ratio=compression,
                  saturadas_pct=float(row["saturadas_pct"]))


def transcribe_all(dataset, rows, transcribe, clock=time.perf_counter, log=print, max_slowdown=MAX_SLOWDOWN):
    """[(texto, avg_logprob, no_speech_prob, compression_ratio)] por fila, y los segundos que tardó.

    TooSlow si las primeras PROBE frases tardan más de MAX_SLOWDOWN veces su duración.
    """
    results, started = [], clock()
    total_audio = sum(float(row["segundos"]) for row in rows)

    for number, row in enumerate(rows, 1):
        results.append(transcribe(read_16k(Path(dataset) / "wavs" / f"{row['id']}.wav")))

        if number == PROBE:
            heard = sum(float(r["segundos"]) for r in rows[:PROBE])
            ratio = (clock() - started) / heard if heard else 0.0

            if ratio > max_slowdown:
                raise TooSlow(ratio, ratio * total_audio)

            log(f"{PROBE} frases a {ratio:.2f}× su duración: unos {ratio * total_audio / 60:.0f} min en total.", flush=True)

        if number % 50 == 0:
            log(f"{number}/{len(rows)} frases", flush=True)

    return results, clock() - started


def merged_rows(rows, results) -> list:
    merged = []

    for row, (text, logprob, no_speech, compression) in zip(rows, results):
        small = phrase_from(row, row["texto"], float(row["avg_logprob"]), float(row["no_speech_prob"]),
                            float(row["compression_ratio"]))
        turbo = phrase_from(row, " ".join(text.replace("|", " ").split()), logprob, no_speech, compression)
        small_reasons, turbo_reasons = review_reasons(small), review_reasons(turbo)
        merged.append({
            "id": row["id"], "segundos": row["segundos"],
            "coinciden": "sí" if comparable(small.texto) == comparable(turbo.texto) else "",
            "texto_small": small.texto, **{f"{m}_small": row[m] for m in METRICS},
            "revisar_small": "sí" if small_reasons else "", "motivos_small": "; ".join(small_reasons),
            "texto_turbo": turbo.texto, **{f"{m}_turbo": round(getattr(turbo, m), 4) for m in METRICS},
            "revisar_turbo": "sí" if turbo_reasons else "", "motivos_turbo": "; ".join(turbo_reasons),
            **{key: row[key] for key in ("pico_dbfs", "rms_dbfs", "saturadas_pct", "origen", "inicio_s")},
        })

    return merged


def write_rows(dataset, rows):
    dataset = Path(dataset)
    shutil.copy2(dataset / "revisar.csv", dataset / "revisar_small.csv")

    with open(dataset / "revisar.csv", "w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def summary(rows, seconds) -> str:
    passing = [row for row in rows if not row["revisar_turbo"]]
    return "\n".join([
        f"Transcripción con {MODEL}: {seconds / 60:.1f} min para {len(rows)} frases.",
        f"Coinciden con small: {sum(bool(row['coinciden']) for row in rows)} de {len(rows)}.",
        f"Pasan los umbrales con turbo: {len(passing)} ({sum(float(row['segundos']) for row in passing) / 60:.1f} min); "
        f"con small eran {sum(not row['revisar_small'] for row in rows)}.",
    ])


def main(transcriber=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True, help="la carpeta de preparar_voz (wavs/, revisar.csv)")
    parser.add_argument("--sin-tope", action="store_true", help=f"no se detiene aunque vaya a más de {MAX_SLOWDOWN:g}×")
    args = parser.parse_args()
    rows = read_rows(args.dataset)

    if rows and "texto_turbo" in rows[0]:
        parser.error("revisar.csv ya tiene texto_turbo; el de small está en revisar_small.csv")

    try:
        results, seconds = transcribe_all(args.dataset, rows, transcriber or WhisperTranscriber(MODEL),
                                          max_slowdown=float("inf") if args.sin_tope else MAX_SLOWDOWN)
    except TooSlow as slow:
        print(f"Detenido: las primeras {PROBE} frases van a {slow.ratio:.1f}× su duración; "
              f"todo tardaría unos {slow.estimate_s / 60:.0f} min. No se cambió nada.")
        return 3

    merged = merged_rows(rows, results)
    write_rows(args.dataset, merged)
    print()
    print(summary(merged, seconds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
