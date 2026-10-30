"""Ruta rápida: mensajes que claramente son charla van al chat sin el IntentEngine.

El IntentEngine tarda unos 20 s por mensaje con el 7B (reprocesa su prompt
de ~2000 tokens); un saludo no necesita clasificarse. Solo se salta con
mensajes que empiezan como charla (saludo, agradecimiento, respuesta corta
o pregunta de conocimiento) y no tienen nada que pueda ser una acción:
@ruta, rutas o nombres de archivo, identificadores de código, verbos de
acción, palabras de memoria o configuración, ni nombres de apps. Ante la
duda, IntentEngine como siempre.
"""
import re

from core.actions.models import command_text

# Inicios de charla (sobre el texto sin acentos ni signos, en minúsculas).
CHAT_START = re.compile(
    r"(hola|holi|hey|buenas|buenos dias|buenas tardes|buenas noches|que tal|como estas|como te va"
    r"|gracias|muchas gracias|mil gracias|de nada|adios|hasta luego|nos vemos|bye"
    r"|que es|que son|que significa|que quiere decir|quien es|quien fue|quien era|quienes son"
    r"|como funciona|como funcionan|cual es la diferencia entre|en que se diferencia|define|definicion de)"
    r"(\b|$)"
)

# Palabras que pueden ser una acción o un dato de Asia: con cualquiera de
# ellas decide el IntentEngine.
ACTION_WORDS = re.compile(
    r"\b(abr|ejecut|corr[eai]|lanz|cre[ao]|escrib|guard|leer|lee|list|busc|encuentr|revis|analiz"
    r"|explic|resum|index|recuerd|olvid|memoria|cambi|usa\b|usar|refactoriz|mejor|corrig|arregl|genera"
    r"|prueb|muestr|ensen|dime|proyecto|provider|proveedor|modelo|archivo|fichero|carpeta|script"
    r"|codigo|funcion\b|funciones|clase|metodo|modulo|variable|bug|error|falla|sandbox|cambio|rag|configura"
    r"|ajuste|me llamo|mi\b|mis\b|sobre mi|de mi\b)"
)

# Rutas, extensiones e identificadores de código ("ProviderRouter", "file_tool", "x.py").
CODE_LIKE = re.compile(
    r"[@/\\`]|\b[\w-]+\.[a-z][a-z0-9]{0,4}\b|\b[a-z]+_[a-z_]+\b|\b[a-z]+[A-Z]\w*|\b[A-Z][a-z]+[A-Z]\w*"
)

# Respuestas cortas: solo solas o casi ("no funciona X" puede ser un bug).
SHORT_REPLIES = {
    "si", "no", "ok", "okay", "vale", "claro", "genial", "perfecto", "excelente", "entendido",
    "de acuerdo", "si gracias", "no gracias", "ok gracias", "vale gracias",
}

MAX_WORDS = 20


def is_clear_chat(text: str, app_names=()) -> bool:
    if not text or "\n" in text.strip():
        return False

    if CODE_LIKE.search(text):
        return False

    command = command_text(text)

    if command in SHORT_REPLIES:
        return True

    if not command or len(command.split()) > MAX_WORDS or not CHAT_START.match(command):
        return False

    if ACTION_WORDS.search(command):
        return False

    words = set(command.split())
    names = {command_text(name) for name in app_names}

    # "hola notepad", "qué es spotify": puede ser abrir la app.
    return not any(name in words or (" " in name and name in command) for name in names)
