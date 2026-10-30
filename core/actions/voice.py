"""Activar o quitar la voz (fase J1) en la sesión.

"activa la voz" y "desactiva la voz" (y "/voz", "/sin voz", que
core/commands.py traduce a estas frases) se reconocen por texto, sin el
IntentEngine. Es un valor de sesión, como --voz: dura hasta salir de Asia y
no se escribe en settings.json. Whisper y la voz se cargan al primer uso.
"""
from core.actions.models import command_text, set_session

VOICE_SETTING = "voice_mode"

ON_PHRASES = {"activa la voz", "modo voz", "habla conmigo", "activar voz"}
OFF_PHRASES = {"desactiva la voz", "quita la voz", "sin voz", "desactivar voz"}


def voice_command(text: str):
    """"on", "off" o None."""
    command = command_text(text)

    if command in ON_PHRASES:
        return "on"

    if command in OFF_PHRASES:
        return "off"

    return None


class VoiceActions:
    def handle_voice_command(self, name):
        if name == "on":
            set_session(**{VOICE_SETTING: True})
            return (
                "Voz activada: pulsa Enter en una línea vacía y habla; termino de escuchar con un "
                "silencio o con otro Enter. Leo en voz alta el texto de cada respuesta (Ctrl+C la "
                'corta). "/sin voz" la quita.'
            )

        set_session(**{VOICE_SETTING: None})
        return "Voz desactivada."
