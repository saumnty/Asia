"""Voz en la terminal (fase J1): una capa de entrada y salida, el cerebro no cambia.

- audio.py: micrófono (16 kHz, mono, tramos de 32 ms) y altavoz.
- vad.py: Silero VAD (el ONNX que trae faster-whisper) y fin de frase.
- stt.py: voz a texto (faster-whisper, siempre en CPU int8).
- tts.py: texto a voz (Piper).
- session.py: escuchar una frase y leer una respuesta.

Los motores se eligen por config ("voice" en config/defaults.json) con los
registros de abajo: otro motor (o una voz propia de Piper) no cambia el resto.
"""
from pathlib import Path

from core.paths import PROJECT_ROOT

DEFAULT_VOICE_SETTINGS = {
    "stt_engine": "faster_whisper",
    "stt_model": "small",
    "stt_compute_type": "int8",
    "stt_beam_size": 5,
    "stt_vocabulary_prompt": True,
    "stt_vocabulary": [],
    "language": "es",
    "tts_engine": "piper",
    "tts_voice": "es_MX-claude-high",
    "tts_speaker": None,
    "models_dir": "data/models",
    "voices_dir": "data/voices",
    "vad_threshold": 0.5,
    "silence_ms": 800,
    "max_seconds": 30,
    "start_timeout_s": 8,
}


def voice_settings(settings) -> dict:
    return {**DEFAULT_VOICE_SETTINGS, **(settings.get("voice") or {})}


def project_path(value) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def stt_engines():
    from core.voice.stt import FasterWhisperSTT

    return {"faster_whisper": FasterWhisperSTT}


def tts_engines():
    from core.voice.tts import PiperTTS

    return {"piper": PiperTTS}


def build_tts(settings, engines=None):
    config = voice_settings(settings)
    engines = engines or tts_engines()
    name = config["tts_engine"]

    if name not in engines:
        raise ValueError(f"Motor de texto a voz desconocido: {name} (disponibles: {', '.join(engines)})")

    return engines[name](config)


def build_stt(settings, engines=None):
    config = voice_settings(settings)
    engines = engines or stt_engines()
    name = config["stt_engine"]

    if name not in engines:
        raise ValueError(f"Motor de voz a texto desconocido: {name} (disponibles: {', '.join(engines)})")

    return engines[name](config)
