"""Lectura frase por frase (J2): la respuesta suena mientras el modelo sigue escribiendo.

SentenceSplitter corta el texto del streaming en frases completas (nunca
dentro de un bloque de código ni de una línea de tabla). Reading las pasa a
voz en un hilo y las reproduce en otro, en orden: mientras suena una frase
ya se está generando la siguiente. stop() corta la lectura y vacía la cola
(Enter, Ctrl+C o volver a escuchar).
"""
import queue
import re
import sys
import threading
import time

from core.voice.speakable import screen_note, to_speakable

# Fin de frase: punto, "!", "?" o "…" seguido de espacio (no "3.5" ni "1. " de
# una lista numerada, ni "archivo.py"), o un salto de línea.
BOUNDARY = re.compile(r"(?<=[^\d\s])[.!?…]+[\"')\]»]*(?=\s)|\n")
FENCE = "```"
END = object()


def table_or_code_line(line: str) -> bool:
    return line.lstrip().startswith("|") or line.startswith(("    ", "\t"))


class SentenceSplitter:
    """feed(chunk) devuelve los tramos de texto que ya terminaron; flush(), el resto."""

    def __init__(self):
        self.buffer = ""
        self.pos = 0

    def feed(self, chunk: str) -> list:
        self.buffer += chunk
        parts = []

        while (cut := self.next_cut()) is not None:
            parts.append(self.buffer[self.pos:cut])
            self.pos = cut

        return parts

    def next_cut(self):
        for match in BOUNDARY.finditer(self.buffer, self.pos):
            end = match.end()

            # Dentro de un bloque de código: se espera a que se cierre.
            if self.buffer.count(FENCE, self.pos, end) % 2:
                continue

            # Un punto dentro de una fila de tabla o de código indentado no corta la línea.
            line_start = self.buffer.rfind("\n", 0, match.start()) + 1

            if match.group() != "\n" and table_or_code_line(self.buffer[line_start:end]):
                continue

            return end

        return None

    def flush(self) -> str:
        rest = self.buffer[self.pos:]
        self.pos = len(self.buffer)
        return rest


class Reading:
    """Una respuesta que se lee frase por frase. timings: la medición del mensaje (--timing)."""

    def __init__(self, tts, speaker, timings=None):
        self.tts = tts
        self.speaker = speaker
        self.timings = timings
        self.splitter = SentenceSplitter()
        self.texts = queue.Queue()
        self.audios = queue.Queue()
        self.stopped = threading.Event()
        self.first_audio = threading.Event()
        self.done = threading.Event()
        self.spoken = []
        self.tts_seconds = 0.0
        self.audio_seconds = 0.0
        self.error = None
        self.threads = [
            threading.Thread(target=self.synthesize_all, name="asia-tts", daemon=True),
            threading.Thread(target=self.play_all, name="asia-speaker", daemon=True),
        ]

        for thread in self.threads:
            thread.start()

    # --- Entrada (hilo principal) -----------------------------------------------

    def feed(self, chunk: str):
        for part in self.splitter.feed(chunk or ""):
            self.say(to_speakable(part, note=False))

    def finish(self, answer: str = None):
        """Fin de la respuesta: lo que quedaba y "te dejo el código en pantalla" si hacía falta."""
        if answer and not self.splitter.buffer:
            self.feed(answer)

        self.say(to_speakable(self.splitter.flush(), note=False))
        self.say(screen_note(answer if answer is not None else self.splitter.buffer))
        self.texts.put(END)

    def say(self, text: str):
        if text and not self.stopped.is_set():
            self.texts.put(text)

    def stop(self):
        """Corta la lectura: vacía las colas y para el audio que suena."""
        self.stopped.set()

        for pending in (self.texts, self.audios):
            while True:
                try:
                    pending.get_nowait()
                except queue.Empty:
                    break

        self.texts.put(END)
        self.audios.put(END)

        try:
            self.speaker.stop()
        except Exception:
            pass

    @property
    def active(self) -> bool:
        return not self.done.is_set() and not self.stopped.is_set()

    def wait(self, timeout=None) -> bool:
        return self.done.wait(timeout)

    def wait_first_audio(self, timeout=None) -> bool:
        """Espera a que suene la primera frase (o a que termine sin nada que leer)."""
        start = time.perf_counter()

        while not self.first_audio.wait(0.05):
            if self.done.is_set() or timeout is not None and time.perf_counter() - start > timeout:
                return False

        return True

    # --- Hilos ------------------------------------------------------------------

    def synthesize_all(self):
        while (text := self.texts.get()) is not END:
            if self.stopped.is_set():
                break

            try:
                start = time.perf_counter()
                audio, rate = self.tts.synthesize(text)
                self.tts_seconds += time.perf_counter() - start
            except Exception as e:
                self.fail(e)
                break

            self.audios.put((text, audio, rate))

        self.audios.put(END)

    def play_all(self):
        try:
            while (item := self.audios.get()) is not END:
                if self.stopped.is_set():
                    break

                text, audio, rate = item

                if not self.first_audio.is_set():
                    if self.timings is not None and self.timings.first_audio is None:
                        self.timings.first_audio = time.perf_counter()

                    self.first_audio.set()

                self.spoken.append(text)
                self.audio_seconds += len(audio) / rate if rate else 0.0

                try:
                    self.speaker.play(audio, rate)
                except Exception as e:
                    self.fail(e)
                    break
        finally:
            self.done.set()

    def fail(self, error):
        """Un fallo de la voz no pierde la respuesta: ya está en pantalla."""
        if self.error is None:
            self.error = error
            print(f"No pude leer la respuesta en voz alta: {error}", file=sys.stderr)

        self.stopped.set()
