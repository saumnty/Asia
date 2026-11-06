"""Clips para entrenar "Oye Asia" en Colab (J3, paso 2 del ROADMAP).

    .venv\\Scripts\\python.exe test\\manual\\generar_wake.py --destino C:\\AsiaVoz\\wake [--respaldo sintetico_v01.zip]

1. Positivos con Piper y las voces de data/voices, repartidos (v0.2) para que el
   modelo no aprenda "voz que sigue tras Asia" (el v0.1 daba 0,01 a "oye Asia"
   sola y 0,8 con una frase detrás):
   - 50 % "oye Asia" sola y sus variantes, con silencio después;
   - 35 % "oye Asia, <frase corta>";
   - 15 % con algo antes ("bueno, oye Asia"), para que no dependa de empezar en silencio.
   Variando length_scale (0,8–1,3), noise_scale y noise_w. WAV de 16 kHz mono, de
   1 a 3 s: lo que pasa de 3 s se corta con un desvanecido (por delante si la
   palabra va al final), lo corto se rellena con silencio.
2. Negativos con las mismas voces y variaciones: la mitad, las frases que engañaban
   al v0.1 ("hoy hacia", "oye Alicia"...), varias también con una frase detrás;
   la otra mitad, el resto de las parecidas.
3. En --destino: sintetico.zip (positivos/, negativos/ y clips.csv con el grupo,
   la voz, el texto y los parámetros de cada clip) y LEEME.txt. mi_voz.zip (lo
   grabado con check_wake) se arma si falta; si ya está, solo se cuenta (para
   rehacerlo, empaquetar_mi_voz.py). Con --respaldo, el sintetico.zip anterior se
   guarda con ese nombre.

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
POSITIVES = 5000
NEGATIVES = 3000
SEED = 2026
# Silencio tras "oye Asia" sola: que el modelo la vea terminar.
SILENCE_AFTER_S = (0.3, 1.0)

# (voz, hablante): sharvard trae dos (M y F).
VOICES = [("es_MX-claude-high", None), ("es_MX-ald-medium", None), ("es_ES-sharvard-medium", 0),
          ("es_ES-sharvard-medium", 1)]
LICENSES = {
    "es_MX-claude-high": "datos Apache-2.0",
    "es_MX-ald-medium": "Unlicense",
    "es_ES-sharvard-medium": "CC BY 3.0 (exige atribución: voz sharvard de Piper, rhasspy/piper-voices)",
}

WAKE = ["oye Asia", "oye, Asia", "¡oye Asia!", "¿oye Asia?", "oye... Asia", "oye Asia."]
FOLLOW_UPS = ["abre el bloc de notas", "qué hora es", "cómo estás", "pon música", "qué tiempo hace",
              "abre Chrome", "¿me ayudas?", "explica este archivo", "busca en Wikipedia", "recuérdame algo",
              "¿qué es un grafo?", "apaga la voz", "cuéntame un chiste", "resume esto"]
LEAD_INS = ["bueno", "a ver", "mira", "perdón", "hola", "entonces", "una cosa", "ya está", "oye, espera"]
# Los que engañaban al v0.1, con más peso, algunos con una frase detrás.
HARD_NEGATIVES = {
    "hoy hacia": ["hoy hacia", "hoy hacia el centro, ¿vienes?"],
    "hoy hacía frío": ["hoy hacía frío", "hoy hacía frío en la mañana"],
    "oye Alicia": ["oye Alicia", "oye Alicia, qué hora es"],
    "o ya sí a": ["o ya sí a", "o ya sí a la escuela"],
    "Asia": ["Asia", "Asia es muy grande"],
    "oye, así": ["oye, así", "oye, así no se hace"],
}
NEGATIVE_PHRASES = ["oye", "Asia Menor", "hey", "Malasia", "fantasía", "Anastasia", "oye tía", "hacia allá", "oye Lucía",
                    "eutanasia", "gimnasia", "oye, amiga", "hoy hay sol", "ya casi", "oiga", "así sí", "Asia y Europa",
                    "oye, ¿y ya?", "hacía calor", "hay sí", "o sea, sí"]
POSITIVE_SHARES = {"sola": 0.50, "detrás": 0.35, "delante": 0.15}
HARD_SHARE = 0.5


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
    group: str = ""
    silence_after: float = 0.0
    keep_end: bool = False
    seconds: float = 0.0
    trimmed: bool = False


def positive_groups() -> dict:
    return {
        "sola": WAKE,
        "detrás": [f"oye Asia, {follow}" for follow in FOLLOW_UPS],
        "delante": [f"{lead}, oye Asia" for lead in LEAD_INS],
    }


def positive_texts() -> list:
    return [text for texts in positive_groups().values() for text in texts]


def negative_texts() -> list:
    return [text for texts in HARD_NEGATIVES.values() for text in texts] + NEGATIVE_PHRASES


def split_count(total, shares) -> list:
    """total repartido según shares (que suman 1), redondeando sin perder clips."""
    counts = [int(total * share) for share in shares]

    for index in range(total - sum(counts)):
        counts[index % len(counts)] += 1

    return counts


def positive_plan(count) -> list:
    """[(grupo, textos, cuántos)] de los positivos."""
    groups = positive_groups()
    counts = split_count(count, list(POSITIVE_SHARES.values()))
    return [(name, groups[name], n) for name, n in zip(POSITIVE_SHARES, counts)]


def negative_plan(count) -> list:
    """[(grupo, textos, cuántos)]: HARD_SHARE para los difíciles, a partes iguales; el resto, para los demás."""
    hard, rest = split_count(count, [HARD_SHARE, 1 - HARD_SHARE])
    per_family = split_count(hard, [1 / len(HARD_NEGATIVES)] * len(HARD_NEGATIVES))
    plan = [(family, texts, n) for (family, texts), n in zip(HARD_NEGATIVES.items(), per_family)]
    return plan + [("parecidas", NEGATIVE_PHRASES, rest)]


def plan(groups, kind, rng, start=0) -> list:
    """Los clips de groups, [(grupo, textos, cuántos)], repartidos por igual entre voces y textos,
    con parámetros al azar (semilla fija)."""
    clips, number = [], start

    for group, texts, count in groups:
        for index in range(count):
            voice, speaker = VOICES[index % len(VOICES)]
            clip = Clip(
                name=f"{kind[0]}{number + 1:05d}.wav", kind=kind, voice=voice, speaker=speaker,
                text=texts[(index // len(VOICES)) % len(texts)], group=group,
                length_scale=round(float(rng.uniform(0.8, 1.3)), 3), noise_scale=round(float(rng.uniform(0.4, 0.9)), 3),
                noise_w=round(float(rng.uniform(0.5, 1.1)), 3),
            )

            if kind == "positivos" and group == "sola":
                clip.silence_after = round(float(rng.uniform(*SILENCE_AFTER_S)), 2)

            clip.keep_end = kind == "positivos" and group == "delante"
            clips.append(clip)
            number += 1

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


def fit(audio, keep_end=False) -> tuple:
    """(audio de MIN_S a MAX_S, si se cortó). Se corta con un desvanecido: por el final, o por
    el principio si keep_end (la palabra va al final). Lo corto se rellena con silencio."""
    longest, shortest = int(MAX_S * RATE), int(MIN_S * RATE)
    fade = int(FADE_S * RATE)

    if len(audio) > longest:
        if keep_end:
            audio = audio[-longest:].copy()
            audio[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
        else:
            audio = audio[:longest].copy()
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


def all_clips(positives, negatives) -> list:
    rng = np.random.default_rng(SEED)
    return plan(positive_plan(positives), "positivos", rng) + plan(negative_plan(negatives), "negativos", rng)


def generate(destination, positives=POSITIVES, negatives=NEGATIVES, load_voice=load_piper, synth=synthesize,
             log=print) -> list:
    """Escribe sintetico.zip en destination; devuelve los clips con su duración."""
    clips = all_clips(positives, negatives)
    voices = {}
    destination.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(destination / "sintetico.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for number, clip in enumerate(clips, 1):
            if clip.voice not in voices:
                voices[clip.voice] = load_voice(clip.voice)

            audio = to_16k(*synth(voices[clip.voice], clip))

            if clip.silence_after:
                audio = np.concatenate([audio, np.zeros(int(clip.silence_after * RATE), dtype=np.float32)])

            audio, clip.trimmed = fit(audio, clip.keep_end)
            clip.seconds = round(len(audio) / RATE, 3)
            archive.writestr(f"{clip.kind}/{clip.name}", wav_bytes(audio))

            if number % 500 == 0:
                log(f"{number}/{len(clips)} clips", flush=True)

        table = io.StringIO()
        writer = csv.writer(table)
        writer.writerow(["archivo", "tipo", "grupo", "voz", "hablante", "texto", "length_scale", "noise_scale", "noise_w",
                         "silencio_despues", "segundos", "cortado"])
        writer.writerows([f"{c.kind}/{c.name}", c.kind, c.group, c.voice, "" if c.speaker is None else c.speaker, c.text,
                          c.length_scale, c.noise_scale, c.noise_w, c.silence_after, c.seconds, c.trimmed] for c in clips)
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


def count_recordings(archive_path) -> dict:
    """Los clips de un mi_voz.zip ya armado."""
    with zipfile.ZipFile(archive_path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".wav")]

    return {kind: sum(name.startswith(f"{kind}/") for name in names) for kind in ("positivos", "negativos")}


def readme(clips, recorded) -> str:
    def groups(kind):
        totals = {}

        for clip in clips:
            if clip.kind == kind:
                count, seconds = totals.get(clip.group, (0, 0.0))
                totals[clip.group] = (count + 1, seconds + clip.seconds)

        return "\n".join(f"  - {group}: {count} clips ({seconds / 60:.1f} min)" for group, (count, seconds) in totals.items())

    count = {kind: sum(c.kind == kind for c in clips) for kind in ("positivos", "negativos")}
    trimmed = sum(c.trimmed for c in clips)
    voices = "\n".join(f"- {name}: {license}" for name, license in LICENSES.items())
    return f"""Clips para entrenar "Oye Asia" (openWakeWord), reparto v0.2

sintetico.zip (Piper, voz sintética):
- positivos/: {count['positivos']} clips. Grupos:
{groups('positivos')}
  ("sola": {", ".join(WAKE)}, con {SILENCE_AFTER_S[0]:g}–{SILENCE_AFTER_S[1]:g} s de silencio después;
  "detrás": "oye Asia, <frase corta>"; "delante": "<frase corta>, oye Asia").
- negativos/: {count['negativos']} clips. Grupos (los que engañaban al v0.1, con una frase detrás en algunos clips, y el resto):
{groups('negativos')}
- WAV de 16 kHz, mono, 16 bits, de {MIN_S:g} a {MAX_S:g} s ({trimmed} cortados a {MAX_S:g} s con un desvanecido).
- length_scale de 0,8 a 1,3, noise_scale de 0,4 a 0,9 y noise_w de 0,5 a 1,1, al azar (semilla {SEED}).
- clips.csv: el grupo, la voz, el hablante, el texto y los parámetros de cada clip.

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
    parser.add_argument("--respaldo", help="nombre con que se guarda el sintetico.zip anterior (sintetico_v01.zip)")
    args = parser.parse_args()
    previous = args.destino / "sintetico.zip"

    if previous.exists():
        if not args.respaldo:
            parser.error(f"ya hay un sintetico.zip en {args.destino}; usa --respaldo o otra carpeta")

        if (args.destino / args.respaldo).exists():
            parser.error(f"ya existe {args.respaldo} en {args.destino}")

        previous.rename(args.destino / args.respaldo)
        print(f"El anterior queda como {args.respaldo}.")

    started = time.perf_counter()
    clips = generate(args.destino, args.positivos, args.negativos)
    seconds = time.perf_counter() - started
    own = args.destino / "mi_voz.zip"
    recorded = count_recordings(own) if own.exists() else pack_recordings(args.grabaciones, args.destino)
    (args.destino / "LEEME.txt").write_text(readme(clips, recorded), encoding="utf-8")

    print(f"\nGenerados {len(clips)} clips en {seconds / 60:.1f} min.")

    for name in ("sintetico.zip", "mi_voz.zip"):
        print(f"{name}: {(args.destino / name).stat().st_size / 1e6:.1f} MB")

    print(readme(clips, recorded))
    return 0


if __name__ == "__main__":
    sys.exit(main())
