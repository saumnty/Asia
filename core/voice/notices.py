"""Avisos fijos para las tareas largas con voz: suenan en menos de 1 s.

"Reviso el archivo…" y "Busco en la biblioteca…" se sintetizan una vez con Piper
al cargar la voz y después se tocan sin sintetizar. Así se sabe enseguida que
Asia entendió, mientras el 7B carga y responde (review_file, /buscar).
"""
import threading

NOTICES = {
    "review": "Reviso el archivo.",
    "search": "Busco en la biblioteca.",
}


class Notices:
    def __init__(self, tts):
        self.tts = tts
        self.cache = {}
        self.lock = threading.Lock()

    def warm(self):
        """Sintetiza todos (al precargar la voz, en su hilo)."""
        for key in NOTICES:
            self.audio(key)

    def audio(self, key):
        """(audio, rate) del aviso; lo sintetiza si todavía no estaba."""
        with self.lock:
            if key not in self.cache:
                self.cache[key] = self.tts.synthesize(NOTICES[key])

            return self.cache[key]


def announce(owner, key):
    """El aviso de key si owner (Brain) tiene la voz activa; si no, nada.

    El launcher deja owner.action_notice con la voz, como action_stream.
    """
    on_notice = getattr(owner, "action_notice", None)

    if on_notice is not None:
        on_notice(key)
