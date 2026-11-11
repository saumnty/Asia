"""Primer audio de las acciones con voz (criterio de cierre de 1.0: ≤ 15 s), sin micrófono.

Cada frase entra por texto al mismo camino que sigue la voz después de
Whisper (launcher.prepare_message y launcher.respond con la sesión de voz):
IntentEngine, la acción, Ollama con streaming y Piper. El audio no suena
(speaker en silencio), pero se sintetiza igual. Antes de cada corrida se deja
cargado el modelo del IntentEngine, como al abrir Asia (precarga) o después
de una charla.

    .venv\\Scripts\\python.exe test\\manual\\check_primer_audio.py
    .venv\\Scripts\\python.exe test\\manual\\check_primer_audio.py --corridas 1 --frases "Resume el archivo DEMO.md."
    .venv\\Scripts\\python.exe test\\manual\\check_primer_audio.py --salida logs\\primer_audio.json

Desglose de cada corrida (segundos desde que entra el texto):
- intención: el IntentEngine (0 si fue un atajo sin modelo);
- herramienta: desde la intención hasta la llamada al modelo que responde
  (leer el archivo, buscar en la biblioteca, armar el prompt);
- generación: desde esa llamada hasta la primera frase completa (incluye
  cargar el modelo; "carga" lo da aparte, según Ollama);
- síntesis: de la primera frase a su audio (Piper);
- primer audio: el total.

Con el micrófono, el mismo número sale en la línea de --timing ("primer
audio") de check_voz.py: a esto se le suma la voz a texto (≤ 4 s).

Código de salida 0 si la mediana de cada frase queda en ≤ 15 s.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings_manager import SettingsManager
from core.paths import PROJECT_ROOT
from core.session import Session

Session.set_paths(project_root=PROJECT_ROOT, user_cwd=ROOT)

import launcher
from core import timing
from core.actions.voice import VOICE_SETTING
from core.brain import Brain
from core.timing import SETTING as TIMING_SETTING
from core.voice import reading as reading_module
from core.voice.session import VoiceSession

LIMIT = 15.0

# Cinco acciones con voz, como saldrían de Whisper (sin @), con rutas desde C:\Asia: un nombre
# suelto ("timing.py") que no está en la carpeta no se encuentra y el modelo contesta que no existe.
PHRASES = [
    "Explica el archivo launcher.py.",
    "Resume el archivo docs/DEMO.md.",
    "Resume la carpeta docs.",
    "Revisa el archivo core/timing.py.",
    # La biblioteca: "busca en la biblioteca …" lo manda el IntentEngine a search_text (grep).
    "/buscar cómo se crea un entorno virtual en Python",
]

STAGES = ("intencion", "herramienta", "generacion", "sintesis", "primer_audio")


class Silent:
    def play(self, audio, rate):
        pass

    def stop(self):
        pass


class Probe:
    """Anota cuándo sale la primera frase hacia la voz y cuándo está su audio."""

    def __init__(self):
        self.first_text = None
        self.first_synth = None

    def install(self, tts):
        probe = self
        original_say = reading_module.Reading.say

        def say(reading, text):
            if text and probe.first_text is None:
                probe.first_text = time.perf_counter()
            original_say(reading, text)

        reading_module.Reading.say = say
        synthesize = tts.synthesize

        def timed_synthesize(text):
            result = synthesize(text)
            if probe.first_synth is None:
                probe.first_synth = time.perf_counter()
            return result

        tts.synthesize = timed_synthesize

    def reset(self):
        self.first_text = None
        self.first_synth = None


def breakdown(timings, probe) -> dict:
    """Las etapas de una corrida (segundos), o None en las que no hubo."""
    start = timings.start
    intent = timings.intent or 0.0
    # La llamada que responde: la última que no es la del IntentEngine.
    calls = timings.calls
    answer_call = calls[-1] if calls else None
    first_audio = timings.first_audio - start if timings.first_audio else None
    first_text = probe.first_text - start if probe.first_text else None

    result = {"intencion": intent, "herramienta": None, "generacion": None, "sintesis": None,
              "primer_audio": first_audio, "carga": None, "modelo": None, "tokens": None}

    if answer_call is not None:
        # timed() anota la duración al terminar; el inicio es la suma de lo anterior.
        call_start = answer_call_start(timings)
        result["herramienta"] = max(call_start - intent, 0.0)
        result["carga"] = answer_call.load
        result["modelo"] = answer_call.model
        result["tokens"] = answer_call.tokens

        if first_text is not None:
            result["generacion"] = max(first_text - call_start, 0.0)
    elif first_text is not None:
        result["herramienta"] = max(first_text - intent, 0.0)

    if first_text is not None and first_audio is not None:
        result["sintesis"] = first_audio - first_text

    return result


def answer_call_start(timings) -> float:
    """Inicio de la llamada que responde, en segundos desde start (anotado por la sonda de calls)."""
    return getattr(timings, "answer_call_start", None) or 0.0


def watch_calls(brain):
    """Anota en la medición en curso cuándo empieza cada llamada al proveedor."""
    router = brain.provider_router

    for name in ("ask", "chat"):
        original = getattr(router, name)

        def wrapper(*args, _original=original, **kwargs):
            timings = timing.current()
            if timings is not None:
                timings.answer_call_start = time.perf_counter() - timings.start
            return _original(*args, **kwargs)

        setattr(router, name, wrapper)


def ready(brain, voice):
    """Como al abrir Asia: la voz cargada y el modelo del IntentEngine en memoria."""
    voice.stop_speaking()
    if hasattr(voice.tts, "load"):
        voice.tts.load()
    brain.intent_engine.preload()


def run_once(brain, voice, probe, phrase) -> dict:
    probe.reset()
    prepared = launcher.prepare_message(brain, phrase)
    text, attachments, use_actions, text_label = prepared

    captured = {}
    original = timing.measure_request

    def measure():
        context = original()

        class Keep:
            def __enter__(self):
                captured["timings"] = context.__enter__()
                return captured["timings"]

            def __exit__(self, *exc):
                return context.__exit__(*exc)

        return Keep()

    timing.measure_request = measure

    try:
        answer = launcher.respond(brain, text, prefix="\nAsia: ", attachments=attachments,
                                  use_actions=use_actions, text_label=text_label, voice=voice, cuttable=True)
    finally:
        timing.measure_request = original

    voice.wait_reading(300)
    result = breakdown(captured["timings"], probe)
    result["accion"] = getattr(brain, "last_action", None)
    result["caracteres"] = len(answer or "")
    return result


def number(value):
    return "—" if value is None else f"{value:.1f}"


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frases", nargs="+", default=PHRASES)
    parser.add_argument("--corridas", type=int, default=3)
    parser.add_argument("--salida", help="JSON con cada corrida")
    args = parser.parse_args()

    # La consola de Windows (cp1252) no tiene "≤" ni "→".
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    SettingsManager.set_overrides({VOICE_SETTING: True, TIMING_SETTING: True})
    brain = Brain()
    voice = VoiceSession(brain.settings, speaker=Silent())
    probe = Probe()
    probe.install(voice.tts)
    watch_calls(brain)

    runs = []

    for phrase in args.frases:
        for attempt in range(args.corridas):
            ready(brain, voice)
            print(f"\n=== {phrase} (corrida {attempt + 1}) ===", file=sys.stderr)
            result = run_once(brain, voice, probe, phrase)
            result.update(frase=phrase, corrida=attempt + 1)
            runs.append(result)
            print(f"\n[{result['accion']}] " + ", ".join(f"{s} {number(result[s])}" for s in STAGES)
                  + f", carga {number(result['carga'])}, {result['modelo']}, {result['tokens']} tokens",
                  file=sys.stderr)

    print("\n| Frase | Acción | " + " | ".join(STAGES) + " | carga |")
    print("|---|---|" + "---|" * (len(STAGES) + 1))
    ok = True

    for phrase in args.frases:
        mine = [r for r in runs if r["frase"] == phrase]
        medians = {s: median([r[s] for r in mine]) for s in STAGES + ("carga",)}
        total = medians["primer_audio"]
        ok = ok and total is not None and total <= LIMIT
        print(f"| {phrase} | {mine[0]['accion']} | " + " | ".join(number(medians[s]) for s in STAGES)
              + f" | {number(medians['carga'])} |")

    print(f"\nMedianas de {args.corridas} corridas. Criterio: primer audio ≤ {LIMIT:.0f} s → "
          + ("cumple" if ok else "NO cumple"))

    if args.salida:
        Path(args.salida).write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
