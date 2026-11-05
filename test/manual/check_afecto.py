"""Núcleo afectivo, versión 0 (core/afecto), con el modelo real: zonas, estilos y tiempo añadido.

24 mensajes inventados con la zona esperada (6 por zona del modelo circunflejo:
desagradable y agitado, desagradable y calmado, agradable y agitado, agradable y
calmado) y 4 neutros. Cada uno se estima solo, sin el estado anterior (carpeta
temporal): mide los aciertos de zona, el estilo elegido y lo que tarda la
estimación (lo que añade a cada mensaje del chat). Con seed fijo y temperatura 0.

    .venv\\Scripts\\python.exe test\\manual\\check_afecto.py
    .venv\\Scripts\\python.exe test\\manual\\check_afecto.py --guardar resultado.json
"""
import argparse
import json
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings_manager import SettingsManager
from core.afecto import AffectCore
from core.afecto.politica import CALM, LIVELY, LOW, NEUTRAL, TENSE, style, zone
from providers.ollama_provider import make_repeatable

CASES = [
    (TENSE, "¡Llevo tres horas con este error y nada funciona, ya no aguanto!"),
    (TENSE, "Me acaban de borrar el trabajo de toda la semana, estoy furioso."),
    (TENSE, "La entrega es en una hora y el robot no arranca, ayúdame ya."),
    (TENSE, "Otra vez se cayó el servidor en plena demo, qué rabia."),
    (TENSE, "Estoy muy nervioso, mañana es el examen y no entiendo nada."),
    (TENSE, "¡No puede ser que vuelva a fallar la compilación justo ahora!"),
    (LOW, "Hoy no tengo ganas de nada, todo me sale mal."),
    (LOW, "Estoy cansado, siento que no avanzo con el proyecto."),
    (LOW, "Me rechazaron la beca. Ya no sé qué hacer."),
    (LOW, "Últimamente me siento solo y sin energía."),
    (LOW, "Qué día tan gris, no logré terminar nada."),
    (LOW, "Creo que ya me rendí con este curso, me siento derrotado."),
    (LIVELY, "¡Por fin funcionó el control del PID, estoy feliz!"),
    (LIVELY, "¡Me aceptaron en la maestría, no lo puedo creer!"),
    (LIVELY, "¡El robot ya balancea la bolita, quiero probar más cosas!"),
    (LIVELY, "¡Ganamos el concurso de robótica, qué emoción!"),
    (LIVELY, "¡Mañana me voy de viaje y estoy emocionadísimo!"),
    (LIVELY, "¡Salió el primer prototipo y quedó increíble!"),
    (CALM, "Hoy fue un día tranquilo, terminé todo con calma."),
    (CALM, "Estoy a gusto leyendo en el jardín."),
    (CALM, "Me siento en paz después de hablar con mi familia."),
    (CALM, "Qué rico descansar después de entregar el proyecto."),
    (CALM, "Todo va bien, sin prisas, disfrutando el café."),
    (CALM, "Estoy satisfecho con cómo quedó el informe."),
    (NEUTRAL, "qué es un grafo bipartito"),
    (NEUTRAL, "convierte 3 km a millas"),
    (NEUTRAL, "cómo se declara una lista en Python"),
    (NEUTRAL, "a qué hora abre la biblioteca"),
]
ZONES = [TENSE, LOW, LIVELY, CALM, NEUTRAL]


def measure(ask, folder):
    rows = []

    for i, (expected, text) in enumerate(CASES):
        # Cada mensaje solo: sin el estado del anterior.
        core = AffectCore(SettingsManager(), path=folder / f"estado_{i}.json")
        start = time.perf_counter()
        state = core.observe(text, ask)
        seconds = time.perf_counter() - start
        found = zone(state)
        rows.append({
            "esperada": expected, "zona": found, "estilo": style(state), "acierto": found == expected,
            "valencia": state.valence, "activacion": state.arousal, "confianza": state.confidence,
            "etiqueta": state.label, "segundos": round(seconds, 2), "mensaje": text,
        })
        print(f"{'sí' if found == expected else 'no'} [{expected} -> {found}, {style(state)}] "
              f"v {state.valence:+.2f} a {state.arousal:+.2f} c {state.confidence:.2f} {state.label}, "
              f"{seconds:.1f} s: {text}", flush=True)

    return rows


def report(rows):
    print("\n| Zona esperada | Aciertos | Zonas estimadas | Estilos |")
    print("|---|---|---|---|")

    for name in ZONES:
        mine = [r for r in rows if r["esperada"] == name]
        zones = ", ".join(f"{z} {n}" for z, n in Counter(r["zona"] for r in mine).most_common())
        styles = ", ".join(f"{s} {n}" for s, n in Counter(r["estilo"] for r in mine).most_common())
        print(f"| {name} | {sum(r['acierto'] for r in mine)}/{len(mine)} | {zones} | {styles} |")

    seconds = sorted(r["segundos"] for r in rows)
    print(f"\nTotal: {sum(r['acierto'] for r in rows)}/{len(rows)}. Tiempo añadido por mensaje: "
          f"mediana {seconds[len(seconds) // 2]:.1f} s, máximo {seconds[-1]:.1f} s (el primero incluye la carga).")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--guardar", type=Path, help="JSON con cada mensaje y su estimación")
    args = parser.parse_args()
    make_repeatable()

    from providers.provider_router import ProviderRouter

    router = ProviderRouter()

    with tempfile.TemporaryDirectory(prefix="asia_afecto_") as folder:
        rows = measure(router.ask, Path(folder))

    report(rows)

    if args.guardar:
        args.guardar.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
