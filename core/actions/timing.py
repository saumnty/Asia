"""Mostrar u ocultar los tiempos de cada respuesta (core/timing.py).

"muestra tiempos" y "oculta tiempos" (y "/tiempos", "/sin tiempos", que
core/commands.py traduce a estas frases) se reconocen por texto, sin el
IntentEngine. Es un valor de sesión, como
--timing: dura hasta salir de Asia y no se escribe en settings.json.
"""
from core.actions.models import command_text, set_session
from core.timing import SETTING

ON_PHRASES = {"muestra tiempos", "muestra los tiempos", "activa los tiempos"}
OFF_PHRASES = {"oculta tiempos", "oculta los tiempos", "desactiva los tiempos"}


def timing_command(text: str):
    """"on", "off" o None."""
    command = command_text(text)

    if command in ON_PHRASES:
        return "on"

    if command in OFF_PHRASES:
        return "off"

    return None


class TimingActions:
    def handle_timing_command(self, name):
        if name == "on":
            set_session(**{SETTING: True})
            return (
                "Tiempos activados: después de cada respuesta muestro el IntentEngine, la carga "
                "del modelo, el prompt, los tokens, la velocidad, el total y el modelo usado. "
                '"/sin tiempos" los oculta.'
            )

        set_session(**{SETTING: None})
        return "Tiempos ocultos."
