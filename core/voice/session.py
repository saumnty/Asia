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
from core.voice.vocabulary import build_prompt
from core.voice.audio import FRAME, SAMPLE_RATE
from core.voice.vad import DONE, NO_SPEECH, SPEAKING, TOO_LONG, EndOfSpeech

# Audio que se deja antes y después de la voz al pasarlo a Whisper.
MARGIN_FRAMES = round(0.3 * SAMPLE_RATE / FRAME)


@dataclass
class Heard:
    """Lo que se entendió de una frase y cuánto tardó la transcripción.

    audio_seconds es lo que se le pasó a Whisper (la voz con un margen);
    recorded_seconds, todo lo grabado (la espera antes de hablar y el
    silencio del final incluidos).
    """
    text: str
    reason: str
    audio_seconds: float = 0.0
    stt_seconds: float = 0.0
    recorded_seconds: float = 0.0


@dataclass
class Calibration:
    """Ruido del cuarto según el VAD: probabilidad de voz de cada tramo en silencio."""
    p95: float
    peak: float
    over_threshold: float
    threshold_before: float
    threshold: float


def calibrated_threshold(probabilities, threshold, margin=0.15, ceiling=0.9):
    """Umbral para que el ruido no cuente como voz: solo sube, nunca baja."""
    noise = float(np.percentile(probabilities, 95)) if len(probabilities) else 0.0

    if noise + margin <= threshold:
        return threshold

    return round(min(ceiling, noise + margin), 2)


def speech_part(frames, detector):
    """Los tramos con voz y MARGIN_FRAMES antes y después; todos si no se detectó voz."""
    if detector.first_speech is None:
        return frames

    start = max(0, detector.first_speech - MARGIN_FRAMES)
    return frames[start:detector.last_speech + 1 + MARGIN_FRAMES]


@dataclass
class Spoken:
    """Lo que se leyó en voz alta y cuánto tardó en generarse."""
    text: str
    tts_seconds: float = 0.0
    audio_seconds: float = 0.0


class VoiceSession:
    def __init__(self, settings, stt=None, microphone=None, vad=None, tts=None, speaker=None, vocabulary=None):
        self.settings = settings
        self.config = voice_settings(settings)
        # Texto para initial_prompt de Whisper; se rehace en cada frase (apps aprendidas).
        self.vocabulary = vocabulary or (lambda: build_prompt(self.settings, self.config))
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

        recorded = len(frames) * FRAME / SAMPLE_RATE
        audio = np.concatenate(speech_part(frames, detector))
        start = time.perf_counter()
        text = self.stt.transcribe(audio, self.vocabulary())

        return Heard(text, reason, len(audio) / SAMPLE_RATE, time.perf_counter() - start, recorded)

    def calibrate(self, seconds=3.0) -> Calibration:
        """Mide el ruido del cuarto (hay que estar en silencio) y sube el umbral del VAD si hace falta.

        El umbral nuevo vale para esta sesión de voz; no se escribe en config.
        """
        self.vad.reset()
        probabilities = []

        with self.microphone.open() as stream:
            for frame in stream:
                probabilities.append(self.vad.probability(frame))

                if len(probabilities) * FRAME >= seconds * SAMPLE_RATE:
                    break

        before = self.config["vad_threshold"]
        self.config["vad_threshold"] = calibrated_threshold(probabilities, before)

        return Calibration(
            p95=float(np.percentile(probabilities, 95)) if probabilities else 0.0,
            peak=max(probabilities, default=0.0),
            over_threshold=sum(p >= before for p in probabilities) / len(probabilities) if probabilities else 0.0,
            threshold_before=before,
            threshold=self.config["vad_threshold"],
        )
