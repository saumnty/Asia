"""Órdenes inequívocas que no necesitan el IntentEngine (~4 s por mensaje).

- "abre X" / "abrir X": open_app con X, si X parece el nombre de una app
  (pocas palabras, sin rutas, extensiones ni palabras de archivo o carpeta,
  sin una segunda orden). open_app ya tolera nombres aproximados y pide
  aclaración si no conoce la app.
- Consultas fijas: proyecto activo, configuración/provider y probar el
  cambio pendiente, con las frases exactas de abajo.

Ante cualquier duda, None: decide el IntentEngine.
"""
import re

from core.actions.models import command_text

OPEN = re.compile(r"(abre|abrir|abreme|abrime|abrirme)\s+(?:(?:el|la|los|las|un|una|mi)\s+)?(?P<name>.+)")

# Con alguna de estas, "abre" no es abrir una app ("abre el archivo x", "abre la carpeta").
NOT_AN_APP = re.compile(
    r"\b(archivo|fichero|carpeta|directorio|proyecto|documento|script|codigo|pagina|web|url|link|enlace"
    r"|sesion|conversacion|chat|cambio|puerta|ventana|pestana|y|e|luego|despues|para|con|en|que|de mi)\b"
)
APP_NAME = re.compile(r"[a-z0-9+ ]+")
MAX_APP_WORDS = 4

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


def fixed_intent(text: str):
    """{"action", "params"} como el IntentEngine, o None si hay duda."""
    if not text or "\n" in text.strip():
        return None

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
