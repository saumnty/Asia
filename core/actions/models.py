"""Ver y cambiar el modelo desde Asia (fase F, parte 3).

"¿qué modelo estás usando?", "usa el modelo de matemáticas", "usa el
modelo qwen3:4b" y "vuelve al modelo normal" se reconocen por texto, sin el
IntentEngine (como los atajos de core/brain.py). Lo que se cambia es un
valor de sesión (SettingsManager.overrides): dura hasta salir de Asia y no
se escribe en settings.json.
"""
import re
import unicodedata

from config.settings_manager import SettingsManager
from core.model_selection import model_for, thinks
from providers.ollama_models import installed_models, is_installed

DOMAIN_WORDS = {
    "matematicas": "math", "mates": "math", "math": "math",
    "codigo": "code", "programacion": "code", "code": "code",
    "general": "general", "charla": "general", "conversacion": "general",
}
DOMAIN_NAMES = {"math": "matemáticas", "code": "código", "general": "general"}

SHOW = re.compile(
    r"(dime |muestra(me)? )?(que|cual es (el|tu)) modelo( (estas usando|usas|tienes|estas))?( ahora)?"
    r"|(dime|muestra(me)?) (el|tu) modelo( actual)?|modelo actual"
)
SET_DOMAIN = re.compile(
    r"(usa el|cambia al|pasa al|activa el) modelo ((de|para) )?(?P<word>" + "|".join(DOMAIN_WORDS) + r")"
)
# Un nombre de modelo de Ollama lleva tag: "qwen3:4b", "qwen2.5-coder:7b".
SET_NAME = re.compile(r"(usa el|cambia al|pasa al) modelo (?P<name>[\w.\-/]+:[\w.\-]+)")
RESET = re.compile(
    r"(vuelve|regresa) al modelo (normal|por defecto|de siempre|original)|usa el modelo normal"
)


def command_text(text: str) -> str:
    """Minúsculas, sin acentos ni signos de puntuación de los extremos."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.split()).strip(" .,!¡?¿")


def model_command(text: str):
    """("show" | "domain" | "name" | "reset", valor) o None si no es un comando."""
    command = command_text(text)

    if SHOW.fullmatch(command):
        return "show", None

    if RESET.fullmatch(command):
        return "reset", None

    match = SET_DOMAIN.fullmatch(command)

    if match:
        return "domain", DOMAIN_WORDS[match.group("word")]

    # El nombre se toma del texto original: puede llevar mayúsculas.
    match = SET_NAME.fullmatch(command)

    if match:
        original = re.search(re.escape(match.group("name")), text, re.IGNORECASE)
        return "name", original.group(0) if original else match.group("name")

    return None


def set_session(**values):
    """Agrega o quita (valor None) valores de sesión."""
    overrides = dict(SettingsManager.overrides)

    for key, value in values.items():
        if value is None:
            overrides.pop(key, None)
        else:
            overrides[key] = value

    SettingsManager.set_overrides(overrides)


class ModelActions:
    def installed(self):
        return installed_models(self.settings.get("ollama_host"))

    def missing_model_message(self, model, installed):
        return (
            f"El modelo {model} no está descargado en Ollama "
            f"(descargados: {', '.join(installed) or 'ninguno'}). "
            f"Descárgalo tú con: ollama pull {model}"
        )

    def handle_model_command(self, kind, value):
        if kind == "show":
            return self.show_models()

        if kind == "reset":
            set_session(forced_model=None, forced_domain=None)
            return f"Vuelvo al modelo normal.\n\n{self.show_models()}"

        if kind == "domain":
            # Sin model_for: un --model fijado no debe decidir cuál es el
            # modelo de matemáticas.
            by_domain = self.settings.get("models_by_domain") or {}
            model = by_domain.get(value) or self.settings.get("ollama_model")
        else:
            model = value
        installed = self.installed()

        if installed is not None and not is_installed(model, installed):
            return self.missing_model_message(model, installed)

        if kind == "domain":
            set_session(forced_domain=value, forced_model=None)
            change = f"Uso el modelo de {DOMAIN_NAMES[value]} ({model}) en el chat"
        else:
            set_session(forced_model=model, forced_domain=None)
            change = f"Uso {model} en el chat y en las acciones"

        return f"{change} hasta que salgas de Asia o escribas \"vuelve al modelo normal\"."

    def show_models(self):
        settings = self.settings
        sticky = getattr(self.provider_router, "sticky_model", None)
        domain = settings.get("forced_domain") or (sticky.domain if sticky else None) or "general"
        chat_model = model_for(settings, domain)
        reasoning = " con razonamiento" if thinks(settings, domain) else ""

        lines = [
            f"Chat: {chat_model} (dominio {DOMAIN_NAMES.get(domain, domain)}{reasoning}).",
            f"Acciones de código: {model_for(settings, 'code')}.",
            f"Detección de intención: {settings.get('intent_model')}.",
        ]

        if settings.get("forced_model"):
            lines.append(f"Fijado en esta sesión: {settings.get('forced_model')} (para todo).")
        elif settings.get("forced_domain"):
            lines.append(f"Fijado en esta sesión: dominio {DOMAIN_NAMES[settings.get('forced_domain')]}.")

        by_domain = settings.get("models_by_domain") or {}
        lines.append(
            "Modelos por dominio: "
            + ", ".join(f"{DOMAIN_NAMES.get(d, d)} = {m}" for d, m in by_domain.items())
            + "."
        )

        return "\n".join(lines)
