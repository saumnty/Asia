"""Vocabulario de Asia para Whisper (initial_prompt).

Whisper entendía "sobre el blog de notas" por "abre el bloc de notas" y
"rootmap.md" por "ROADMAP": no conoce las órdenes ni los nombres propios de
Asia. El initial_prompt es texto que Whisper toma como lo dicho antes y que
lo inclina hacia esas palabras.

Se construye con los datos de Asia, sin listas a mano:
- verbos de las órdenes: frases entre comillas y ejemplos del prompt del
  IntentEngine, los atajos fijos y las frases de los comandos "/";
- apps de apps.json y apps_learned.json;
- proyectos (memory/projects y el proyecto activo);
- y voice.stt_vocabulary de config/defaults.json (ROADMAP, Bolitabot...).
"""
import re
import unicodedata
from pathlib import Path

from core.paths import APPS_FILE, PROJECTS_DIR

# Primeras palabras de frases que no son órdenes.
NOT_VERBS = {
    "que", "cual", "como", "donde", "quien", "por", "mi", "el", "la", "los", "las", "un", "una",
    "segun", "otras", "usa", "si", "sin", "modo", "configuracion", "proyecto", "cambio",
    "aplicar", "ver", "mostrar", "confirmar", "cancelar", "dime", "usuario", "encuentra",
    "solo", "synthesis", "cwd", "carpeta",
}

# Whisper solo mira los últimos ~220 tokens del prompt.
MAX_CHARS = 400

QUOTED = re.compile(r'"([^"\n]{2,40})"')
RULE = re.compile(r"^- .+$", re.MULTILINE)
EXAMPLE = re.compile(r"^Usuario: (.+)$", re.MULTILINE)


def plain(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word.lower()) if unicodedata.category(c) != "Mn")


def first_word(phrase: str) -> str:
    match = re.match(r"[¿¡]?([a-záéíóúñü]+)", phrase.strip().lower())
    return match.group(1) if match else ""


def command_phrases():
    """Frases de órdenes que Asia ya reconoce, en el orden en que aparecen."""
    from core.brain import SHORTCUT_ACTIONS
    from core.commands import COMMANDS
    from core.fixed_intents import FIXED_PHRASES
    from core.intent_engine import INTENT_PROMPT

    yield from EXAMPLE.findall(INTENT_PROMPT)

    for rule in RULE.findall(INTENT_PROMPT):
        yield from QUOTED.findall(rule)
    yield from FIXED_PHRASES
    yield from SHORTCUT_ACTIONS

    for command in COMMANDS:
        yield from command.aliases


def command_verbs(phrases) -> list:
    """Primera palabra de cada frase, si parece un verbo: primero los que más frases usan."""
    verbs, counts = {}, {}

    for phrase in phrases:
        word = first_word(phrase)

        if len(word) < 3 or plain(word) in NOT_VERBS:
            continue

        # "explícame" y "muéstrame" cuentan como "explica" y "muestra".
        key = plain(word)[:-2] if plain(word).endswith("me") and len(word) > 5 else plain(word)

        if key not in verbs or len(word) < len(verbs[key]):
            verbs[key] = word

        counts[key] = counts.get(key, 0) + 1

    # sorted es estable: a igual cuenta, el orden en que aparecen.
    return [verbs[key] for key in sorted(verbs, key=lambda key: -counts[key])]


def unique(words):
    seen = set()

    for word in words:
        word = " ".join(str(word).split())

        if word and plain(word) not in seen:
            seen.add(plain(word))
            yield word


def vocabulary_prompt(verbs, apps, projects, extra) -> str:
    """Texto para initial_prompt: como lo que se le dijo antes a Asia.

    Si no cabe, se recortan los verbos: apps, proyectos y palabras van enteros.
    """
    names = [
        ("apps", list(unique(apps))),
        ("proyectos", list(unique(projects))),
        ("palabras", list(unique(extra))),
    ]
    tail = "".join(f" {name.capitalize()}: {', '.join(words)}." for name, words in names if words)
    verbs = list(unique(verbs))

    while verbs and len(f"Órdenes para Asia: {', '.join(verbs)}.{tail}") > MAX_CHARS:
        verbs.pop()

    head = f"Órdenes para Asia: {', '.join(verbs)}." if verbs else ""
    return f"{head}{tail}".strip()


def known_projects(settings, projects_dir=PROJECTS_DIR):
    names = [settings.get("active_project"), settings.get("project_name")]

    try:
        names += [path.stem for path in sorted(Path(projects_dir).glob("*.md"))]
    except OSError:
        pass

    return [name for name in names if name]


def known_apps(apps_file=APPS_FILE):
    from tools.app_tool import AppTool

    try:
        return list(AppTool(apps_file).known_apps())
    except Exception:
        return []


def build_prompt(settings, config, apps_file=APPS_FILE, projects_dir=PROJECTS_DIR) -> str:
    """initial_prompt con los datos actuales de Asia; "" si stt_vocabulary_prompt es false."""
    if not config.get("stt_vocabulary_prompt", True):
        return ""

    apps = known_apps(apps_file)
    # "abre X" es el atajo fijo de cada app (core/fixed_intents.py).
    phrases = [*command_phrases(), *(f"abre {app}" for app in apps)]

    return vocabulary_prompt(
        command_verbs(phrases), apps, known_projects(settings, projects_dir), config.get("stt_vocabulary") or [],
    )
