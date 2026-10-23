"""Acción que elige el IntentEngine para mensajes fijos (requiere Ollama).

Sirve para medir antes y después de cambiar el prompt o el modelo del
IntentEngine:

    .venv\\Scripts\\python.exe test\\manual\\check_intents.py --out antes.json
    (cambiar el prompt)
    .venv\\Scripts\\python.exe test\\manual\\check_intents.py --compare antes.json

    # Otro modelo sin tocar settings.json:
    .venv\\Scripts\\python.exe test\\manual\\check_intents.py --model qwen3:4b --compare antes.json

Cada mensaje se clasifica --runs veces (temperatura 0: debería salir igual).
El primer mensaje incluye la carga del modelo; se informa aparte.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings_manager import SettingsManager
from core.intent_engine import IntentEngine

# Así llegan al IntentEngine los mensajes con @ruta: el launcher cambia
# @ruta por la ruta absoluta.
BUGGY = ROOT / "pruebas" / "buggy_calculator.py"
FILE_TOOL = ROOT / "tools" / "file_tool.py"

MESSAGES = [
    "recuerda que mi color favorito es el verde",
    "abre el bloc de notas",
    "¿qué es una closure en Python?",
    "busca la palabra Ollama en el proyecto",
    "explícame el archivo tools/file_tool.py",
    "muéstrame un resumen del archivo core/brain.py",
    "corrige pruebas/buggy_calculator.py",
    "refactoriza pruebas/buggy_calculator.py",
    "mejora el estilo de tools/file_tool.py",
    "encuentra por qué aparece Asia None",
    "arregla el bug de Asia None",
    "revisa a fondo pruebas/buggy_calculator.py",
    "revisa la carpeta pruebas sin síntesis",
    "prueba el cambio pendiente",
    # Agregados al medir qwen3:4b.
    "cómo me llamo?",
    "olvida mi color favorito",
    f"revisa a fondo {BUGGY}",
    f"explica {FILE_TOOL}",
    "ejecuta pruebas/buggy_calculator.py en el sandbox",
    "confirma el cambio por favor",
    "revisa la carpeta core",
    "gracias, eso es todo por hoy",
    "cuéntame un chiste",
    "lista la carpeta pruebas",
    "dónde se usa ProviderRouter",
    "busca código muerto en el proyecto",
    "cambia el provider a gemini",
    "por qué falla el streaming",
]

# Acción correcta de cada mensaje según las reglas del prompt (en el mismo
# orden): para comparar modelos no basta con que coincidan entre sí.
EXPECTED = [
    "remember", "open_app", "chat", "search_text", "explain_file",
    "read_file_preview", "generate_code", "smart_refactor", "smart_refactor",
    "debug_project", "debug_project", "review_file_deep", "review_project",
    "run_sandbox", "recall", "forget", "review_file_deep", "explain_file",
    "run_sandbox", "apply_change", "review_project", "chat", "chat",
    "list_folder", "find_references", "detect_dead_code", "set_provider",
    "debug_project",
]
assert len(EXPECTED) == len(MESSAGES)


def classify(engine, runs):
    results = {}
    first_seconds = None

    for message in MESSAGES:
        intents = []
        seconds = []

        for _ in range(runs):
            start = time.perf_counter()
            intents.append(engine.detect(message))
            seconds.append(time.perf_counter() - start)

        if first_seconds is None:
            first_seconds = seconds.pop(0)

        actions = {i.get("action") for i in intents}
        results[message] = {
            "action": intents[0].get("action"),
            "params": intents[0].get("params"),
            "estable": len(actions) == 1 and all(i == intents[0] for i in intents),
            "segundos": round(sum(seconds) / len(seconds), 2) if seconds else None,
        }
        flag = "" if results[message]["estable"] else f"  INESTABLE: {intents}"
        print(f"{intents[0].get('action'):22} {message}{flag}", flush=True)

    wrong = [(m, e, results[m]["action"]) for m, e in zip(MESSAGES, EXPECTED) if results[m]["action"] != e]
    print(f"\nAcción correcta: {len(MESSAGES) - len(wrong)} de {len(MESSAGES)}")

    for message, expected, got in wrong:
        print(f"  MAL: {message!r}: {got} (esperada {expected})")

    loaded = [r["segundos"] for r in results.values() if r["segundos"] is not None]
    print(f"\nPrimera llamada (con carga del modelo): {first_seconds:.1f} s")
    print(f"Ya cargado: {sum(loaded) / len(loaded):.2f} s por mensaje de media")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--compare", type=Path, help="JSON de una medición anterior")
    parser.add_argument("--model", help="intent_model para esta medición (no cambia settings.json)")
    args = parser.parse_args()

    if args.model:
        SettingsManager.set_overrides({"intent_model": args.model})

    print(f"intent_model: {SettingsManager().get('intent_model')}\n")
    results = classify(IntentEngine(), args.runs)

    if args.out:
        args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))
        common = [m for m in MESSAGES if m in before]
        changed = [m for m in common if before[m].get("action") != results[m]["action"]]
        params = [m for m in common if m not in changed and before[m].get("params") != results[m]["params"]]
        print(f"\n{len(common) - len(changed)} de {len(common)} con la misma acción; "
              f"{len(common) - len(changed) - len(params)} con acción y parámetros iguales.")

        for message in changed:
            print(f"  CAMBIÓ: {message!r}: {before[message].get('action')} -> {results[message]['action']}")

        for message in params:
            print(f"  PARÁMETROS: {message!r}: {before[message].get('params')} -> {results[message]['params']}")


if __name__ == "__main__":
    main()
