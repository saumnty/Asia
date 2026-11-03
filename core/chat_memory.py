"""Qué parte de la memoria personal lleva un mensaje del chat.

Con la memoria completa en el prompt de sistema, qwen3:4b se adjudicaba los
datos del usuario ("Mi color favorito es el amarillo" ante un "hola"). Ahora:
- la charla breve (saludos, agradecimientos, despedidas) no lleva memoria;
- el resto, solo las entradas que tienen que ver con el mensaje, en tercera
  persona y bajo un título que dice de quién son.
"""
import re

from core.actions.models import command_text
from core.fast_chat import SHORT_REPLIES

TITLE = "Datos sobre el usuario, no sobre ti (úsalos solo si el mensaje trata del usuario):"

SMALL_TALK = re.compile(
    r"(hola|holi|hey|buenas|buenos dias|buenas tardes|buenas noches|que tal|como estas|como te va"
    r"|gracias|muchas gracias|mil gracias|de nada|adios|hasta luego|hasta manana|nos vemos|bye|chao)"
    r"(\b|$)"
)

# Lo que no puede faltar en un saludo para que deje de ser charla breve
# ("hola, ¿cómo me llamo?").
ABOUT_USER = re.compile(r"\b(mi|mis|me|yo|sobre mi|de mi)\b")

# Una pregunta a Asia ("¿cuál es tu color favorito?", "¿quién eres?"): sin
# memoria, o el 7B contestaba "Mi color favorito es el amarillo".
ABOUT_ASSISTANT = re.compile(r"\b(tu|tus|te|ti|eres|contigo)\b")

# "qué sabes de mí", "háblame sobre mí", "quién soy": todo lo guardado tiene que
# ver. "de mi color favorito" no: ahí va solo esa entrada.
WHOLE_MEMORY = re.compile(r"\b(sobre|de) mi$|\bquien soy\b")

# Palabras con que se pregunta por una entrada sin nombrar su clave.
SYNONYMS = {
    "nombre": {"llamo", "llamas", "llama", "nombre"},
    "universidad": {"estudio", "estudias", "facultad", "carrera", "universidad"},
    "proyecto": {"proyecto", "trabajo"},
}

STOPWORDS = {
    "que", "cual", "cuales", "como", "cuando", "donde", "quien", "para", "por", "con", "sin",
    "una", "uno", "unos", "unas", "los", "las", "del", "mis", "tus", "sus", "esta", "este", "eso",
    "esto", "algo", "sabes", "dime", "es", "el", "la", "de", "mi", "me", "tu", "te", "yo", "un",
    "en", "y", "o", "a", "al", "lo", "le", "se", "si", "no", "muy", "mas", "hay", "son", "ser",
}

# Tope de entradas por mensaje: nunca la memoria completa de golpe.
MAX_ENTRIES = 5


def is_small_talk(text: str) -> bool:
    command = command_text(text or "")

    if command in SHORT_REPLIES:
        return True

    return bool(SMALL_TALK.match(command)) and len(command.split()) <= 6 and not ABOUT_USER.search(command)


def stem(word: str) -> str:
    """Raíz tosca: "favorito" y "favorita" coinciden."""
    return word[:5]


def words(text: str) -> set:
    return {stem(w) for w in command_text(text).split() if w not in STOPWORDS and len(w) > 2}


def entry_words(key: str, value) -> set:
    key_text = key.replace("_", " ")
    return words(key_text) | words(str(value)) | {stem(w) for w in SYNONYMS.get(key, ())}


def relevant_memory(text: str, data: dict) -> dict:
    """Las entradas de data que tienen que ver con text (como mucho MAX_ENTRIES)."""
    if not data or is_small_talk(text):
        return {}

    command = command_text(text)

    if ABOUT_ASSISTANT.search(command) and not ABOUT_USER.search(command):
        return {}

    if WHOLE_MEMORY.search(command):
        return dict(list(data.items())[:MAX_ENTRIES])

    asked = words(text)
    chosen = {key: value for key, value in data.items() if asked & entry_words(key, value)}
    return dict(list(chosen.items())[:MAX_ENTRIES])


def is_recall(text: str) -> bool:
    """False si recall no es la acción: una pregunta a Asia o una por toda la memoria.

    "¿cuál es tu color favorito?" no pregunta por el del usuario, y "¿qué
    sabes de mí?" no se contesta con una sola entrada: los dos van al chat.
    """
    command = command_text(text or "")

    if ABOUT_ASSISTANT.search(command) and not ABOUT_USER.search(command):
        return False

    return not WHOLE_MEMORY.search(command)


def memory_note(entries: dict) -> str:
    """Las entradas en tercera persona, bajo TITLE; vacío si no hay ninguna."""
    if not entries:
        return ""

    lines = [f"- {key.replace('_', ' ')} del usuario: {value}" for key, value in entries.items()]
    return "\n".join([TITLE, *lines])
