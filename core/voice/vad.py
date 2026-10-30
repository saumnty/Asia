"""Detección de voz (Silero VAD) y del fin de la frase.

Se usa el ONNX de Silero que trae faster-whisper, con onnxruntime: el
paquete silero-vad cargaría PyTorch. A diferencia de faster-whisper, que
analiza un audio completo, aquí se procesa tramo a tramo mientras se habla,
conservando el estado del modelo entre tramos.
"""
from dataclasses import dataclass

import numpy as np

from core.voice.audio import FRAME, SAMPLE_RATE

CONTEXT = 64

WAITING, SPEAKING, DONE, NO_SPEECH, TOO_LONG = "esperando", "hablando", "fin", "sin voz", "demasiado larga"


class SileroVAD:
    def __init__(self):
        import onnxruntime
        from faster_whisper.vad import get_assets_path

        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.log_severity_level = 4
        path = f"{get_assets_path()}/silero_vad_v6.onnx"
        self.session = onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"], sess_options=options)
        self.reset()

    def reset(self):
        self.h = np.zeros((1, 1, 128), dtype="float32")
        self.c = np.zeros((1, 1, 128), dtype="float32")
        self.context = np.zeros(CONTEXT, dtype="float32")

    def probability(self, frame: np.ndarray) -> float:
        """Probabilidad de voz de un tramo de FRAME muestras."""
        batch = np.concatenate([self.context, frame.astype("float32")])[None, :]
        output, self.h, self.c = self.session.run(None, {"input": batch, "h": self.h, "c": self.c})
        self.context = frame[-CONTEXT:].astype("float32")
        return float(np.ravel(output)[0])


@dataclass
class EndOfSpeech:
    """Decide cuándo terminó la frase a partir de la probabilidad de cada tramo.

    Empieza a contar cuando hay min_speech_ms seguidos de voz (un golpe o un
    clic suelto no abren la frase); termina tras silence_ms de silencio, si
    no hubo voz en start_timeout_s o si la frase pasa de max_seconds.

    first_speech y last_speech son los tramos (desde 0) donde empezó y
    terminó la voz: se usan para no pasarle a Whisper la espera ni el
    silencio del final.
    """
    threshold: float = 0.5
    silence_ms: int = 800
    max_seconds: float = 30
    start_timeout_s: float = 8
    min_speech_ms: float = 96
    frame_ms: float = FRAME / SAMPLE_RATE * 1000

    def __post_init__(self):
        self.state = WAITING
        self.elapsed_ms = 0.0
        self.silent_ms = 0.0
        self.frames = 0
        self.run = 0
        self.first_speech = None
        self.last_speech = None

    @classmethod
    def from_config(cls, config):
        return cls(config["vad_threshold"], config["silence_ms"], config["max_seconds"], config["start_timeout_s"],
                   config.get("min_speech_ms", 96))

    def feed(self, probability: float) -> str:
        self.elapsed_ms += self.frame_ms
        self.frames += 1
        speech = probability >= self.threshold
        self.run = self.run + 1 if speech else 0

        if speech:
            self.last_speech = self.frames - 1

        if self.state == WAITING:
            if self.run * self.frame_ms >= self.min_speech_ms:
                self.state = SPEAKING
                self.first_speech = self.frames - self.run
            elif self.elapsed_ms >= self.start_timeout_s * 1000:
                self.state = NO_SPEECH

            return self.state

        self.silent_ms = 0.0 if speech else self.silent_ms + self.frame_ms

        if self.silent_ms >= self.silence_ms:
            self.state = DONE
        elif self.elapsed_ms >= self.max_seconds * 1000:
            self.state = TOO_LONG

        return self.state
