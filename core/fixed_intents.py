"""Órdenes inequívocas que no necesitan el IntentEngine (~4 s por mensaje).

- "abre X" / "abrir X": open_app con X, si X parece el nombre de una app
  (pocas palabras, sin rutas, extensiones ni palabras de archivo o carpeta,
  sin una segunda orden). open_app ya tolera nombres aproximados y pide
  aclaración si no conoce la app.
- Consultas fijas: proyecto activo, configuración/provider y probar el
  cambio pendiente, con las frases exactas de abajo.
- "revisa el archivo X" / "revisa X", con X un archivo (ruta o nombre con
  extensión) y nada más: review_file. Por voz es una tarea larga, con su aviso
  fijo: sin el IntentEngine suena antes de 1 s. "a fondo", "la carpeta" o
  "y luego…" siguen al IntentEngine.
- "busca en la biblioteca X", "busca X en mis fuentes", "consulta en
  Wikipedia X": search_project_rag con X, como /buscar. Por voz, el
  IntentEngine las mandaba a search_text (grep en el proyecto).

Ante cualquier duda, None: decide el IntentEngine.
"""
import re
import unicodedata

from core.actions.models import command_text

OPEN = re.compile(r"(abre|abrir|abreme|abrime|abrirme)\s+(?:(?:el|la|los|las|un|una|mi)\s+)?(?P<name>.+)")

# Con alguna de estas, "abre" no es abrir una app ("abre el archivo x", "abre la carpeta").
NOT_AN_APP = re.compile(
    r"\b(archivo|fichero|carpeta|directorio|proyecto|documento|script|codigo|pagina|web|url|link|enlace"
    r"|sesion|conversacion|chat|cambio|puerta|ventana|pestana|y|e|luego|despues|para|con|en|que|de mi)\b"
)
APP_NAME = re.compile(r"[a-z0-9+ ]+")
MAX_APP_WORDS = 4

SEARCH_VERB = r"(?:(?:puedes|podrias|me\s+puedes)\s+)?(?:busca|buscame|buscar|buscarme|consulta|consultar|mira|investiga)"
# Dónde: la biblioteca de /fuentes. "en wikipedia" queda en la pregunta: elige la fuente.
LIBRARY_PLACE = (
    r"(?:(?:en|dentro de)\s+)(?P<place>(?:la|mi|tu)\s+biblioteca|(?:mis|las|tus)\s+fuentes"
    r"|(?:la|mi|tu)\s+documentacion(?:\s+(?:offline|local|que\s+te\s+di|de\s+(?P<topic>ros\s*2|gazebo|python)))?"
    r"|(?:los|mis)\s+documentos\s+que\s+te\s+di|wikipedia)"
)
LIBRARY_BEFORE = re.compile(rf"(?:oye\s+asia\s+)?{SEARCH_VERB}\s+{LIBRARY_PLACE}\s+(?:sobre\s+|acerca\s+de\s+)?(?P<question>.+)")
LIBRARY_AFTER = re.compile(rf"(?:oye\s+asia\s+)?{SEARCH_VERB}\s+(?P<question>.+?)\s+{LIBRARY_PLACE}")

FIXED_PHRASES = {
    **dict.fromkeys(
        ["muestra el proyecto activo", "muestrame el proyecto activo", "dime el proyecto activo",
         "que proyecto esta activo", "cual es el proyecto activo", "proyecto activo"],
        "show_active_project",
    ),
    **dict.fromkeys(
        ["que provider estas usando", "que proveedor estas usando", "que provider usas",
         "que proveedor usas", "muestra la configuracion", "muestrame la configuracion",
         "configuracion actual"],
        "show_settings",
    ),
    **dict.fromkeys(["prueba el cambio pendiente"], "run_sandbox"),
}


REVIEW_FILE = re.compile(
    r"(?:oye\s+asia\s+)?(?:revisa|revisame|revisar|revise)\s+(?:el\s+archivo\s+|el\s+fichero\s+)?"
    r"(?P<path>[\w.:/\\-]+\.[a-z0-9]{1,5})",
    re.IGNORECASE,
)


def review_file(text: str):
    """{"action": "review_file", "params": {"file_path"}} o None (ver arriba)."""
    if not text or "\n" in text.strip():
        return None

    original = text.strip().strip(" .!¡?¿,")
    match = REVIEW_FILE.fullmatch(same_length_plain(original.replace(",", " ")))

    if not match:
        return None

    return {"action": "review_file", "params": {"file_path": original[match.start("path"):match.end("path")]}}


def same_length_plain(text: str) -> str:
    """Minúsculas y sin acentos, letra por letra: cada posición es la misma que en text."""
    plain = []

    for char in text.lower():
        base = "".join(c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c))
        plain.append(base[:1] if len(base) >= 1 else char)

    return "".join(plain)


def library_search(text: str):
    """{"action": "search_project_rag", "params": {"question"}} o None.

    La pregunta sale del texto original (con acentos y mayúsculas), sin el verbo ni el
    lugar; con "en wikipedia" termina en " en wikipedia", que en /buscar elige la fuente.
    """
    if not text or "\n" in text.strip():
        return None

    original = text.strip().strip(" .!¡¿").replace(",", " ")
    plain = same_length_plain(original)
    match = LIBRARY_BEFORE.fullmatch(plain) or LIBRARY_AFTER.fullmatch(plain)

    if not match:
        return None

    question = " ".join(original[match.start("question"):match.end("question")].split()).strip(" ?")

    if not question:
        return None

    question = question.lstrip("¿")
    question = f"{question} en wikipedia" if match.group("place") == "wikipedia" else question

    if match.group("topic"):
        question = f"{question} en {original[match.start('topic'):match.end('topic')]}"

    return {"action": "search_project_rag", "params": {"question": question}}


def fixed_intent(text: str):
    """{"action", "params"} como el IntentEngine, o None si hay duda."""
    if not text or "\n" in text.strip():
        return None

    library = library_search(text)

    if library:
        return library

    review = review_file(text)

    if review:
        return review

    # Una ruta o un nombre de archivo ("abre a.py", "abre C:\\x") va al IntentEngine.
    if re.search(r"[@/\\]|\.[a-z0-9]{1,5}\b", text.lower()):
        return None

    command = command_text(text)
    action = FIXED_PHRASES.get(command)

    if action:
        return {"action": action, "params": {}}

    match = OPEN.fullmatch(command)

    if not match:
        return None

    name = match.group("name").strip()

    if not APP_NAME.fullmatch(name) or len(name.split()) > MAX_APP_WORDS or NOT_AN_APP.search(name):
        return None

    return {"action": "open_app", "params": {"app_name": name}}
