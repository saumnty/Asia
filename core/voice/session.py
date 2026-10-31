"""Escuchar una frase y leer una respuesta (frase por frase, core/voice/reading.py).

Los motores se crean al primer uso: activar la voz no carga Whisper hasta
que se escucha algo. Micrófono, VAD y motores se pueden inyectar (pruebas).
"""
import threading
import time
from dataclasses import dataclass

import numpy as np

from core import timing
from core.voice import build_stt, build_tts, voice_settings
from core.voice.reading import Reading
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
        self.reading = None
        self.voice_preload = None

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

    def preload_voice(self):
        """Carga la voz en un hilo: la primera lectura no detiene los tokens ni retrasa Ctrl+C.

        Si falla, no se avisa aquí: lo dirá la primera lectura.
        """
        if self.voice_preload is not None:
            return self.voice_preload

        try:
            tts = self.tts
        except Exception:
            return None

        if not hasattr(tts, "load"):
            return None

        def load():
            try:
                tts.load()
            except Exception:
                pass

        self.voice_preload = threading.Thread(target=load, name="asia-voz", daemon=True)
        self.voice_preload.start()
        return self.voice_preload

    def start_reading(self) -> Reading:
        """Una lectura frase por frase (core/voice/reading.py); corta la anterior si seguía."""
        self.stop_speaking()
        self.reading = Reading(self.tts, self.speaker, timing.current())
        return self.reading

    @property
    def speaking(self) -> bool:
        return self.reading is not None and self.reading.active

    def stop_speaking(self) -> bool:
        """Corta la lectura en curso. True si había algo sonando o por sonar."""
        reading, self.reading = self.reading, None

        if reading is None or not reading.active:
            return False

        reading.stop()
        return True

    def wait_reading(self, timeout=None):
        if self.reading is not None:
            self.reading.wait(timeout)

    def speak(self, answer: str) -> Spoken:
        """Lee answer entera y espera a que termine (jarvis --voz "mensaje"). Ctrl+C corta la lectura."""
        reading = self.start_reading()
        reading.finish(answer)

        try:
            reading.wait()
        except KeyboardInterrupt:
            self.stop_speaking()

        return Spoken(" ".join(reading.spoken), reading.tts_seconds, reading.audio_seconds)

    def unload(self):
        """Libera los modelos ("/sin voz"): Whisper y la voz de Piper ocupan ~380 MB."""
        self.stop_speaking()

        for engine in (self._stt, self._tts):
            if engine is not None and hasattr(engine, "unload"):
                engine.unload()

        self._stt = self._tts = None
        self.voice_preload = None

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
        # Volver a escuchar corta la lectura: el micrófono no debe oír a Asia.
        self.stop_speaking()
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
