"""Escuchar una frase y leer una respuesta.

Los motores se crean al primer uso: activar la voz no carga Whisper hasta
que se escucha algo. Micrófono, VAD y motores se pueden inyectar (pruebas).
"""
import time
from dataclasses import dataclass

import numpy as np

from core import timing
from core.voice import build_stt, build_tts, voice_settings
from core.voice.speakable import to_speakable
from core.voice.vad import DONE, NO_SPEECH, SPEAKING, TOO_LONG, EndOfSpeech


@dataclass
class Heard:
    """Lo que se entendió de una frase y cuánto tardó la transcripción."""
    text: str
    reason: str
    audio_seconds: float = 0.0
    stt_seconds: float = 0.0


@dataclass
class Spoken:
    """Lo que se leyó en voz alta y cuánto tardó en generarse."""
    text: str
    tts_seconds: float = 0.0
    audio_seconds: float = 0.0


class VoiceSession:
    def __init__(self, settings, stt=None, microphone=None, vad=None, tts=None, speaker=None):
        self.settings = settings
        self.config = voice_settings(settings)
        self._stt = stt
        self._microphone = microphone
        self._vad = vad
        self._tts = tts
        self._speaker = speaker

    @property
    def tts(self):
        if self._tts is None:
            self._tts = build_tts(self.settings)

        return self._tts

    @property
    def speaker(self):
        if self._speaker is None:
            from core.voice.audio import Speaker

            self._speaker = Speaker()

        return self._speaker

    def speak(self, answer: str) -> Spoken:
        """Lee el texto normal de answer (core/voice/speakable.py). Ctrl+C corta la lectura."""
        text = to_speakable(answer)

        if not text:
            return Spoken("")

        start = time.perf_counter()
        audio, rate = self.tts.synthesize(text)
        seconds = time.perf_counter() - start

        audio_seconds = len(audio) / rate if rate else 0.0
        timing.record_voice("tts", seconds, audio_seconds)

        try:
            self.speaker.play(audio, rate)
        except KeyboardInterrupt:
            self.speaker.stop()

        return Spoken(text, seconds, audio_seconds)

    def unload(self):
        """Libera los modelos ("/sin voz"): Whisper y la voz de Piper ocupan ~380 MB."""
        for engine in (self._stt, self._tts):
            if engine is not None and hasattr(engine, "unload"):
                engine.unload()

        self._stt = self._tts = None

    @property
    def stt(self):
        if self._stt is None:
            self._stt = build_stt(self.settings)

        return self._stt

    @property
    def microphone(self):
        if self._microphone is None:
            from core.voice.audio import Microphone

            self._microphone = Microphone()

        return self._microphone

    @property
    def vad(self):
        if self._vad is None:
            from core.voice.vad import SileroVAD

            self._vad = SileroVAD()

        return self._vad

    def listen(self, stop_requested=lambda: False) -> Heard:
        """Graba hasta el fin de la frase (silencio) o hasta stop_requested() (Enter).

        El audio queda solo en memoria. Si no hubo voz, text es "".
        """
        detector = EndOfSpeech.from_config(self.config)
        self.vad.reset()
        frames = []
        reason = NO_SPEECH
        spoke = False

        with self.microphone.open() as stream:
            for frame in stream:
                frames.append(frame)
                state = detector.feed(self.vad.probability(frame))
                spoke = spoke or state == SPEAKING

                if stop_requested():
                    reason = "enter"
                    break

                if state in (DONE, NO_SPEECH, TOO_LONG):
                    reason = state
                    break

        if not frames or not spoke and reason != "enter":
            return Heard("", reason)

        audio = np.concatenate(frames)
        start = time.perf_counter()
        text = self.stt.transcribe(audio)

        return Heard(text, reason, len(audio) / 16000, time.perf_counter() - start)
