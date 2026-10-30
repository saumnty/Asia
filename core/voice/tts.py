"""Texto a voz.

Interfaz: synthesize(texto) -> (audio float32, frecuencia). PiperTTS lee la
voz tts_voice (un .onnx con su .onnx.json) de voices_dir, en CPU: una voz
propia entrenada con Piper se usa igual, dejando sus dos archivos ahí.
"""
import numpy as np

from core.voice import project_path


class MissingVoice(RuntimeError):
    pass


class PiperTTS:
    def __init__(self, config):
        self.config = config
        self.voice = None

    def voice_path(self):
        return project_path(self.config["voices_dir"]) / f"{self.config['tts_voice']}.onnx"

    def load(self):
        if self.voice is not None:
            return self.voice

        path = self.voice_path()

        if not path.exists() or not path.with_suffix(".onnx.json").exists():
            raise MissingVoice(
                f"Falta la voz {self.config['tts_voice']} en {path.parent} (el .onnx y su .onnx.json). "
                "Las voces de Piper están en https://huggingface.co/rhasspy/piper-voices"
            )

        from piper import PiperVoice

        self.voice = PiperVoice.load(path)
        return self.voice

    def synthesize(self, text: str):
        from piper import SynthesisConfig

        chunks = list(self.load().synthesize(text, syn_config=SynthesisConfig(speaker_id=self.config["tts_speaker"])))

        if not chunks:
            return np.zeros(0, dtype=np.float32), 22050

        return np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32), chunks[0].sample_rate

    def unload(self):
        self.voice = None
