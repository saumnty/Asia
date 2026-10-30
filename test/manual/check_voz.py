"""Comprobación de la voz (fase J1) con los modelos reales.

Con el micrófono (por defecto): abre Asia con la voz y --timing. Pulsa Enter
en una línea vacía, habla, y Asia responde en pantalla y en voz alta.

    .venv\\Scripts\\python.exe test\\manual\\check_voz.py
    .venv\\Scripts\\python.exe test\\manual\\check_voz.py --dispositivos   # micrófonos disponibles

Sin micrófono: cada frase se genera con Piper, se pasa a 16 kHz y entra como
si se hubiera dicho (VAD, Whisper, Brain, Ollama y Piper reales). Sirve para
medir las latencias sin hablar:

    .venv\\Scripts\\python.exe test\\manual\\check_voz.py --sin-microfono
    .venv\\Scripts\\python.exe test\\manual\\check_voz.py --sin-microfono --sin-audio   # no reproduce

El audio no se guarda en disco.
"""
import argparse
import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings_manager import SettingsManager
from core.paths import PROJECT_ROOT
from core.session import Session

Session.set_paths(project_root=PROJECT_ROOT, user_cwd=ROOT)

import launcher
from core.actions.voice import VOICE_SETTING
from core.brain import Brain
from core.timing import SETTING as TIMING_SETTING
from core.voice.audio import FRAME, SAMPLE_RATE
from core.voice.session import VoiceSession

PHRASES = ["Muestra el proyecto activo.", "Cuéntame un chiste.", "Qué es un grafo bipartito."]


class SpokenMicrophone:
    """Micrófono simulado: cada vez que se abre entrega la siguiente frase y 1,5 s de silencio."""

    def __init__(self, audios):
        self.audios = list(audios)

    @contextmanager
    def open(self):
        audio = np.concatenate([np.zeros(SAMPLE_RATE // 4, np.float32), self.audios.pop(0),
                                np.zeros(int(SAMPLE_RATE * 1.5), np.float32)])
        audio = np.pad(audio, (0, -len(audio) % FRAME))
        yield iter(audio.reshape(-1, FRAME))


class Silent:
    def play(self, audio, rate):
        pass

    def stop(self):
        pass


def spoken(phrases, tts):
    for phrase in phrases:
        audio, rate = tts.synthesize(phrase)
        positions = np.arange(0, len(audio), rate / SAMPLE_RATE)
        yield np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sin-microfono", action="store_true", help="frases generadas con Piper en lugar del micrófono")
    parser.add_argument("--sin-audio", action="store_true", help="no reproduce las respuestas")
    parser.add_argument("--frases", nargs="+", default=PHRASES)
    parser.add_argument("--dispositivos", action="store_true", help="lista los micrófonos y sale")
    args = parser.parse_args()

    if args.dispositivos:
        import sounddevice as sd

        print(sd.query_devices())
        print(f"\nEntrada por defecto: {sd.default.device[0]}")
        return 0

    SettingsManager.set_overrides({VOICE_SETTING: True, TIMING_SETTING: True})
    brain = Brain()
    voice = VoiceSession(brain.settings, speaker=Silent() if args.sin_audio else None)

    if not args.sin_microfono:
        launcher.interactive_mode(brain, voice=voice)
        return 0

    voice._microphone = SpokenMicrophone(spoken(args.frases, voice.tts))
    lines = iter([""] * len(args.frases) + ["salir"])
    # Como en la terminal: el Enter en la línea vacía deja el prompt en su línea.
    launcher.interactive_mode(brain, read=lambda prompt: print(prompt) or next(lines), voice=voice)
    return 0


if __name__ == "__main__":
    sys.exit(main())
