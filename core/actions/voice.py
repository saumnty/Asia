"""Activar o quitar la voz (fase J1) en la sesión.

"activa la voz" y "desactiva la voz" (y "/voz", "/sin voz", que
core/commands.py traduce a estas frases) se reconocen por texto, sin el
IntentEngine. Es un valor de sesión, como --voz: dura hasta salir de Asia y
no se escribe en settings.json. Whisper y la voz se cargan al primer uso.
"""
from core.actions.models import command_text, set_session

VOICE_SETTING = "voice_mode"
# La palabra de activación (core/voice/wake.py), también de sesión: "/escucha" y "/sin escucha".
WAKE_SETTING = "wake_mode"

ON_PHRASES = {"activa la voz", "modo voz", "habla conmigo", "activar voz"}
OFF_PHRASES = {"desactiva la voz", "quita la voz", "sin voz", "desactivar voz"}
WAKE_ON_PHRASES = {"activa la escucha", "escucha la palabra", "activar escucha"}
WAKE_OFF_PHRASES = {"desactiva la escucha", "quita la escucha", "sin escucha", "desactivar escucha"}


def voice_command(text: str):
    """"on", "off", "wake_on", "wake_off" o None."""
    command = command_text(text)

    for name, phrases in (("on", ON_PHRASES), ("off", OFF_PHRASES), ("wake_on", WAKE_ON_PHRASES),
                          ("wake_off", WAKE_OFF_PHRASES)):
        if command in phrases:
            return name

    return None


class VoiceActions:
    def handle_voice_command(self, name):
        if name == "wake_on":
            return self.wake_on()

        if name == "wake_off":
            set_session(**{WAKE_SETTING: None})
            return "Escucha desactivada: Enter en una línea vacía sigue escuchando."

        if name == "on":
            set_session(**{VOICE_SETTING: True})
            return (
                "Voz activada: pulsa Enter en una línea vacía y habla; termino de escuchar con un "
                "silencio o con otro Enter. Leo en voz alta el texto de cada respuesta (Ctrl+C la "
                'corta). "/sin voz" la quita.'
            )

        set_session(**{VOICE_SETTING: None, WAKE_SETTING: None})
        return "Voz desactivada."

    def wake_on(self):
        """La palabra de activación necesita la voz: "/escucha" la activa también."""
        from core.voice import voice_settings
        from core.voice.wake import missing, wake_config

        config = voice_settings(self.settings)
        absent = missing(config)

        if absent:
            return f"No puedo escuchar la palabra de activación. {absent}"

        set_session(**{VOICE_SETTING: True, WAKE_SETTING: True})
        label = wake_config(config)["wake_label"]
        return (
            f"Escucha activada: di «{label}» y luego lo que quieras; termino de escuchar con un silencio. "
            "No escucho mientras leo en voz alta. Enter en una línea vacía también escucha. "
            '"/sin escucha" la quita.'
        )
