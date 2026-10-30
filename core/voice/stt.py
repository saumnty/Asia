"""Voz a texto.

Interfaz: transcribe(audio float32 mono a 16 kHz, prompt) -> texto. prompt es
el vocabulario de Asia (core/voice/vocabulary.py) como initial_prompt. FasterWhisperSTT
corre siempre en CPU (int8): la GPU de 4 GB la ocupa el 7B de Ollama y no
debe desalojarse. El modelo se lee de models_dir; Asia no lo descarga.
"""
import os

import numpy as np

from core.voice import project_path


class MissingModel(RuntimeError):
    pass


class FasterWhisperSTT:
    def __init__(self, config):
        self.config = config
        self.model = None

    def model_path(self):
        return project_path(self.config["models_dir"]) / f"faster-whisper-{self.config['stt_model']}"

    def load(self):
        if self.model is not None:
            return self.model

        path = self.model_path()

        if not (path / "model.bin").exists():
            raise MissingModel(
                f"Falta el modelo de voz a texto en {path}. Descárgalo (una vez) con:\n"
                f"  .venv\\Scripts\\python.exe -c \"from faster_whisper.utils import download_model; "
                f"download_model('{self.config['stt_model']}', output_dir=r'{path}')\""
            )

        from faster_whisper import WhisperModel

        # Siempre CPU: device no se lee de config a propósito.
        self.model = WhisperModel(
            str(path), device="cpu", compute_type=self.config["stt_compute_type"],
            cpu_threads=max(1, (os.cpu_count() or 4) // 2), local_files_only=True,
        )
        return self.model

    def transcribe(self, audio: np.ndarray, prompt: str = "") -> str:
        segments, _ = self.load().transcribe(
            audio, language=self.config["language"], beam_size=self.config["stt_beam_size"],
            condition_on_previous_text=False, vad_filter=False, initial_prompt=prompt or None,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def unload(self):
        self.model = None
