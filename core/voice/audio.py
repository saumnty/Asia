"""Micrófono y altavoz con sounddevice. El audio solo vive en memoria."""
import queue
from contextlib import contextmanager

import numpy as np

SAMPLE_RATE = 16000
# 512 muestras a 16 kHz (32 ms): el tamaño de tramo de Silero VAD.
FRAME = 512


class Microphone:
    """Tramos de FRAME muestras float32 (mono, 16 kHz) mientras está abierto."""

    def __init__(self, sample_rate=SAMPLE_RATE, frame=FRAME):
        self.sample_rate = sample_rate
        self.frame = frame

    @contextmanager
    def open(self):
        import sounddevice as sd

        frames = queue.Queue()

        def callback(data, count, time_info, status):
            frames.put(data[:, 0].copy())

        stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32",
            blocksize=self.frame, callback=callback,
        )

        with stream:
            yield FrameReader(frames)


class FrameReader:
    def __init__(self, frames):
        self.frames = frames

    def __iter__(self):
        while True:
            try:
                yield self.frames.get(timeout=2)
            except queue.Empty:
                return


class Speaker:
    def play(self, audio: np.ndarray, sample_rate: int):
        """Reproduce y espera a que termine."""
        import sounddevice as sd

        sd.play(audio, sample_rate)
        sd.wait()

    def stop(self):
        import sounddevice as sd

        sd.stop()
