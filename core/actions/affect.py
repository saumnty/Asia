"""El núcleo afectivo en la sesión (core/afecto): /estado, /afecto on|off|borrar y la corrección.

Texto fijo, sin el IntentEngine. "/afecto on" y "/afecto off" son valores de
sesión, como /voz; para dejarlo encendido, afecto.activo en config/settings.json.
La corrección ("no, solo estoy concentrado") solo se reconoce con el afecto activo.
"""
from core.actions.models import command_text, set_session
from core.afecto import AFFECT_SETTING, AffectCore, affect_enabled
from core.afecto.nucleo import is_correction
from core.provenance import EMOCIONAL, Fragment, record

PHRASES = {
    "estado": {"muestra el estado", "como me ves", "que estado tengo"},
    "on": {"activa el afecto", "afecto on"},
    "off": {"desactiva el afecto", "afecto off"},
    "borrar": {"borra el estado", "afecto borrar", "borra mi estado"},
}


def affect_command(text: str, settings=None):
    """"estado", "on", "off", "borrar", "corregir" o None."""
    command = command_text(text)

    for name, phrases in PHRASES.items():
        if command in phrases:
            return name

    if settings is not None and affect_enabled(settings) and is_correction(text):
        return "corregir"

    return None


class AffectActions:
    def handle_affect_command(self, name, text=""):
        self.last_action = "afecto"
        core = AffectCore(self.settings)

        if name == "on":
            set_session(**{AFFECT_SETTING: True})
            return (
                "Afecto activado para la sesión: estimo cómo te sientes en cada mensaje (en local, nunca sale) y "
                "ajusto el tono. Es una simulación, puede fallar: /estado muestra lo que creo, corrígeme cuando "
                "quieras y /afecto off lo apaga."
            )

        if name == "off":
            set_session(**{AFFECT_SETTING: False})
            return "Afecto desactivado: ya no estimo tu estado. Lo guardado sigue hasta /afecto borrar."

        if name == "borrar":
            return "Borré la estimación de tu estado." if core.clear() else "No había ninguna estimación guardada."

        # Lo que se muestra o se corrige es sobre el usuario: nunca sale.
        record(Fragment(EMOCIONAL, text or name))

        if name == "corregir":
            state = core.correct(text, self.provider_router.ask)
            return f"Gracias, lo corrijo. {core.describe(state)}"

        return core.describe(core.state())
