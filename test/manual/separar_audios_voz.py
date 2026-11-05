"""Separa los audios de un remitente de una exportación de WhatsApp (voz propia, uso privado).

    .venv\\Scripts\\python.exe test\\manual\\separar_audios_voz.py --export <carpeta> --remitente "<nombre>" --destino <carpeta>

Del .txt del chat lee SOLO la fecha, el remitente y el nombre del adjunto de las
líneas con un audio; el texto de los mensajes no se guarda ni se imprime. COPIA
(no mueve) a --destino los audios de ese remitente, con su nombre original, y
lista los audios sin remitente claro y los que el chat nombra pero faltan. En
--export no se toca nada.

Formatos de WhatsApp en español e inglés:
    12/03/24, 14:05 - Nombre: PTT-20240312-WA0001.opus (archivo adjunto)
    3/12/24, 2:05 p. m. - Name: PTT-20240312-WA0001.opus (file attached)
    [12/03/24, 14:05:33] Nombre: <adjunto: 00000012-AUDIO-2024-03-12-14-05-33.opus>
    [3/12/24, 2:05:33 PM] Name: <attached: 00000012-AUDIO-2024-03-12-14-05-33.opus>
"""
import argparse
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTENSIONS = {".opus", ".ogg", ".m4a", ".mp3", ".aac", ".amr", ".wav"}
# Marcas invisibles que WhatsApp pone delante de adjuntos y nombres.
INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬﻿"), None)

HEADER = re.compile(
    r"^\[?(?P<date>\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}),?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:[\s ]*(?:[ap]\.?[\s ]?m\.?|am|pm))?)\]?"
    r"\s*(?:-\s+)?(?P<rest>.*)$",
    re.IGNORECASE,
)
AUDIO = r"[^\s<>:/\\]+\.(?:" + "|".join(ext[1:] for ext in sorted(AUDIO_EXTENSIONS)) + r")"
ATTACHED = re.compile(
    rf"(?P<a>{AUDIO})\s*\((?:archivo adjunto|file attached)\)|<(?:adjunto|attached):\s*(?P<b>{AUDIO})\s*>",
    re.IGNORECASE,
)


@dataclass
class AudioLine:
    """Lo único que se lee de una línea del chat con un audio."""
    date: str
    sender: str | None
    name: str


def normalized(name: str) -> str:
    """Para comparar remitentes: sin marcas invisibles, sin "~ ", sin mayúsculas ni acentos."""
    text = unicodedata.normalize("NFKD", (name or "").translate(INVISIBLE))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.replace("~", " ").split()).casefold()


def audio_line(line: str) -> AudioLine | None:
    """La fecha, el remitente y el adjunto de una línea con un audio; None si no lo tiene.

    El resto de la línea (el texto del mensaje) se descarta aquí.
    """
    header = HEADER.match(line.translate(INVISIBLE).strip())

    if not header:
        return None

    rest = header.group("rest")
    attached = ATTACHED.search(rest)

    if not attached:
        return None

    before = rest[:attached.start()]
    # "Nombre: <adjunto…>": el remitente es lo que va antes del primer ": ".
    sender = before.split(": ", 1)[0].strip() if ": " in before else None
    return AudioLine(header.group("date"), sender or None, attached.group("a") or attached.group("b"))


def chat_file(export: Path) -> Path:
    chats = sorted(export.glob("*.txt"))

    if len(chats) != 1:
        raise SystemExit(f"Esperaba un .txt del chat en la exportación y hay {len(chats)}.")

    return chats[0]


def read_audio_lines(chat: Path) -> list:
    with open(chat, encoding="utf-8-sig", errors="replace") as source:
        return [found for found in map(audio_line, source) if found]


def audio_files(export: Path) -> dict:
    """{nombre: ruta} de los audios de la exportación (también en subcarpetas)."""
    return {path.name: path for path in sorted(export.rglob("*")) if path.suffix.lower() in AUDIO_EXTENSIONS}


def separate(export, sender, destination) -> dict:
    """Copia los audios de sender a destination; devuelve qué se copió y qué no."""
    export, destination = Path(export), Path(destination)

    if destination.resolve() == export.resolve() or export.resolve() in destination.resolve().parents:
        raise SystemExit("--destino no puede estar dentro de --export: ahí no se toca nada.")

    lines = read_audio_lines(chat_file(export))
    files = audio_files(export)
    wanted = normalized(sender)
    by_name = {}

    for line in lines:
        by_name.setdefault(line.name, set()).add(normalized(line.sender) if line.sender else None)

    result = {"copiados": [], "ya_estaban": [], "sin_remitente_claro": [], "faltan": [], "de_otros": 0}

    for name, senders in by_name.items():
        if name not in files:
            result["faltan"].append(name)
        elif None in senders or len(senders) > 1:
            result["sin_remitente_claro"].append(name)
        elif wanted not in senders:
            result["de_otros"] += 1
        else:
            target = destination / name

            if target.exists():
                result["ya_estaban"].append(name)
            else:
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(files[name], target)
                result["copiados"].append(name)

    # Audios de la carpeta que el chat no nombra: no se sabe de quién son.
    result["sin_remitente_claro"] += [name for name in files if name not in by_name]
    result["remitentes"] = len({normalized(line.sender) for line in lines if line.sender})
    return result


def report(result, sender) -> str:
    lines = [
        f"Copiados de «{sender}»: {len(result['copiados'])}.",
        f"Ya estaban en el destino: {len(result['ya_estaban'])}.",
        f"De otros remitentes: {result['de_otros']}.",
    ]

    for title, key in (("Sin remitente claro", "sin_remitente_claro"), ("En el chat pero faltan en la carpeta", "faltan")):
        lines.append(f"{title}: {len(result[key])}.")
        lines += [f"  {name}" for name in result[key]]

    if not result["copiados"] and not result["ya_estaban"]:
        lines.append(f"Ningún audio de «{sender}»: revisa el nombre (en el chat hay {result['remitentes']} remitentes).")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, required=True, help="carpeta de la exportación de WhatsApp (no se toca)")
    parser.add_argument("--remitente", required=True, help="el nombre del remitente tal como sale en el chat")
    parser.add_argument("--destino", type=Path, required=True, help="adónde se copian sus audios")
    args = parser.parse_args()

    if not args.export.is_dir():
        parser.error(f"no existe la carpeta {args.export}")

    print(report(separate(args.export, args.remitente, args.destino), args.remitente))
    return 0


if __name__ == "__main__":
    sys.exit(main())
