"""Palabra de activación (fase J3) con openWakeWord: "Hey Jarvis" ahora, "Oye Asia" después.

Un hilo escucha el micrófono mientras se espera un mensaje. Cuando la puntuación
pasa voice.wake_threshold, suelta el micrófono y avisa: el launcher corta el
prompt y escucha la frase con Silero VAD y Whisper, como Enter en una línea
vacía. Mientras Asia lee en voz alta no escucha (Piper no debe activarla).

Los modelos (melspectrograma, embeddings, la palabra y el VAD de Silero) van en
voice.wake_models_dir; son CC BY-NC-SA 4.0: uso personal, no distribuibles.
"""
import threading
from pathlib import Path

import numpy as np

from core.paths import PROJECT_ROOT
from core.voice.audio import SAMPLE_RATE

# openWakeWord trabaja con tramos de 80 ms en int16; el micrófono da 512 muestras float32.
CHUNK = 1280
# Una frase dispara varios tramos seguidos: cuenta una activación cada REFRACTORY_S.
REFRACTORY_S = 2.0
MISSING_PACKAGE = "Falta openwakeword: .venv\\Scripts\\python.exe -m pip install openwakeword==0.6.0 --no-deps"
MISSING_MODELS = "Faltan los modelos de openWakeWord en {folder}: {names} (versión v0.5.1)."


class Chunker:
    """Junta los tramos del micrófono (float32, 512) en tramos de CHUNK muestras int16."""

    def __init__(self, size=CHUNK):
        self.size = size
        self.pending = np.zeros(0, dtype=np.int16)

    def feed(self, frame) -> list:
        samples = np.clip(np.asarray(frame, dtype=np.float32), -1.0, 1.0)
        self.pending = np.concatenate([self.pending, (samples * 32767).astype(np.int16)])
        chunks = []

        while len(self.pending) >= self.size:
            chunks.append(self.pending[:self.size])
            self.pending = self.pending[self.size:]

        return chunks


class Activations:
    """Las veces que la puntuación pasa el umbral, una por REFRACTORY_S de audio como mucho."""

    def __init__(self, threshold, refractory_s=REFRACTORY_S, chunk_s=CHUNK / SAMPLE_RATE):
        self.threshold = threshold
        self.refractory_s = refractory_s
        self.chunk_s = chunk_s
        self.elapsed = 0.0
        self.last = None
        self.times = []
        self.peak = 0.0

    def feed(self, score: float) -> bool:
        self.peak = max(self.peak, score)
        now = self.elapsed
        self.elapsed += self.chunk_s

        if score < self.threshold or self.last is not None and now - self.last < self.refractory_s:
            return False

        self.last = now
        self.times.append(now)
        return True


def wake_config(config) -> dict:
    """config: lo de "voice" (voice_settings), con los valores por defecto de la palabra."""
    from core.voice import DEFAULT_VOICE_SETTINGS

    return {**DEFAULT_VOICE_SETTINGS, **(config or {})}


def models_folder(config) -> Path:
    folder = Path(wake_config(config)["wake_models_dir"])
    return folder if folder.is_absolute() else PROJECT_ROOT / folder


def model_files(config) -> dict:
    """Las rutas de los .onnx; wake_word es un nombre de la carpeta o la ruta de un .onnx propio."""
    folder = models_folder(config)
    word = wake_config(config)["wake_word"]
    word_path = Path(word) if word.endswith(".onnx") else folder / f"{word}.onnx"
    return {
        "melspec": folder / "melspectrogram.onnx",
        "embedding": folder / "embedding_model.onnx",
        "word": word_path,
        "vad": folder / "silero_vad.onnx",
    }


def missing(config) -> str:
    """Qué falta para escuchar la palabra (el paquete o los modelos); "" si nada."""
    try:
        import openwakeword  # noqa: F401
    except ImportError:
        return MISSING_PACKAGE

    files = model_files(config)
    needed = [path for name, path in files.items() if name != "vad" or wake_config(config)["wake_vad_threshold"] > 0]
    absent = [path for path in needed if not path.is_file()]
    return MISSING_MODELS.format(folder=models_folder(config), names=", ".join(p.name for p in absent)) if absent else ""


def load_model(config):
    """El modelo de openWakeWord con ONNX (en Windows no hay tflite), desde wake_models_dir."""
    import openwakeword
    from openwakeword.model import Model

    files = model_files(config)
    model = Model(
        wakeword_models=[str(files["word"])], inference_framework="onnx",
        melspec_model_path=str(files["melspec"]), embedding_model_path=str(files["embedding"]),
    )
    vad = wake_config(config)["wake_vad_threshold"]

    # openWakeWord 0.6.0 busca el VAD en su propia carpeta: se le pone el de wake_models_dir.
    if vad > 0:
        model.vad_threshold = vad
        model.vad = openwakeword.VAD(model_path=str(files["vad"]))

    return model


def reset_model(model):
    """Vacía lo que openWakeWord guarda de la escucha anterior. model.reset() de 0.6.0
    no toca el VAD de Silero: su estado y sus últimas puntuaciones seguían ahí."""
    model.reset()
    vad = getattr(model, "vad", None)

    if getattr(model, "vad_threshold", 0) > 0 and vad is not None:
        vad.reset_states()
        vad.prediction_buffer.clear()


def scores(model, frames):
    """La puntuación de cada tramo de 80 ms de frames (tramos del micrófono)."""
    chunker = Chunker()

    for frame in frames:
        for chunk in chunker.feed(frame):
            yield max(model.predict(chunk).values(), default=0.0)


class WakeListener:
    """Escucha la palabra en un hilo hasta oírla o hasta stop().

    paused(): True mientras Asia lee en voz alta; el micrófono se suelta y se
    espera a que termine. on_wake() se llama con el micrófono ya cerrado, para
    que lo abra Whisper.
    """

    def __init__(self, model, microphone, threshold, on_wake, paused=lambda: False):
        self.model = model
        self.microphone = microphone
        self.threshold = threshold
        self.on_wake = on_wake
        self.paused = paused
        self.stopping = threading.Event()
        self.heard = threading.Event()
        self.thread = threading.Thread(target=self.run, name="asia-wake", daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self, timeout=3.0):
        self.stopping.set()

        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout)

    def run(self):
        while not self.stopping.is_set():
            if self.paused():
                self.stopping.wait(0.1)
                continue

            if self.listen_once():
                self.heard.set()
                self.on_wake()
                return

    def listen_once(self) -> bool:
        """Con el micrófono abierto hasta oír la palabra (True), parar o empezar a leer (False)."""
        reset_model(self.model)
        found = Activations(self.threshold)

        with self.microphone.open() as stream:
            for score in scores(self.model, self.until_stopped(stream)):
                if found.feed(score):
                    return True

        return False

    def until_stopped(self, stream):
        for frame in stream:
            if self.stopping.is_set() or self.paused():
                return

            yield frame
