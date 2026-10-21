"""Banco de calidad de las revisiones (requiere Ollama; pytest no lo recoge).

Revisa los casos de test/manual/casos/ con review_file_deep y con
review_project_files y compara cada hallazgo contra verdad.json:

    precisión = aciertos / reportados   (aciertos: reales + aceptables, sin repetidos)
    recall    = reales detectados / reales esperados

Uso:
    .venv\\Scripts\\python.exe test\\manual\\check_review_quality.py --runs 3 --out salida\\antes
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings_manager import SettingsManager
from providers.provider_router import ProviderRouter
from tools.tool_registry import ToolRegistry

CASES_DIR = Path(__file__).resolve().parent / "casos"

# Secciones donde cada formato pone los hallazgos que presenta como ciertos.
FINDING_HEADERS = [
    r"BUGS_FOUND:",
    r"CONFIRMED_ISSUES:",
    r"VERIFICADO \(cita encontrada\):",
]
SECTION_END = re.compile(
    r"^[\s*#]*([A-Z_]{4,}:|[A-Z][A-Z ]{3,}(\(.*\))?:|Descartados|Duplicados|={5,})"
)
ITEM_START = re.compile(r"^\s*(\d+[.)]|[-*•])\s+")
NEGATIVE = re.compile(r"ningun|no se encontr|no encontr|no hay|n/a|none|sin problemas")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def extract_findings(report: str) -> list[str]:
    """Hallazgos de las secciones de FINDING_HEADERS, uno por viñeta."""
    findings = []
    lines = report.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]
        header = next(
            (h for h in FINDING_HEADERS if re.search(h, line)), None
        )
        index += 1

        if not header:
            continue

        rest = re.split(header, line, maxsplit=1)[1].strip()
        section = [rest] if rest else []

        while index < len(lines) and not SECTION_END.match(lines[index]):
            section.append(lines[index])
            index += 1

        items = []

        for text in section:
            if ITEM_START.match(text):
                items.append(ITEM_START.sub("", text).strip())
            elif text.strip() and items:
                items[-1] += " " + text.strip()

        if not items:
            text = " ".join(t.strip() for t in section).strip()

            if text and not NEGATIVE.search(normalize(text)):
                items.append(text)

        findings.extend(items)

    return findings


def load_truth(case_name: str) -> dict:
    data = json.loads((CASES_DIR / "verdad.json").read_text(encoding="utf-8"))
    common = data["comunes"]
    case = data["casos"].get(case_name, {})

    return {
        kind: case.get(kind, []) + common.get(kind, [])
        for kind in ("reales", "aceptables", "falsos")
    }


def classify(finding: str, truth: dict) -> tuple[str, str | None]:
    text = normalize(finding)

    for kind in ("reales", "aceptables", "falsos"):
        for item in truth[kind]:
            if any(re.search(pattern, text) for pattern in item["patrones"]):
                return kind, item["id"]

    return "no_clasificado", None


def score(findings: list[str], truth: dict) -> dict:
    seen = set()
    result = {
        "reportados": len(findings),
        "aciertos": 0,
        "reales_detectados": [],
        "reales_esperados": [item["id"] for item in truth["reales"]],
        "falsos": 0,
        "repetidos": 0,
        "no_clasificados": [],
        "detalle": [],
    }

    for finding in findings:
        kind, item_id = classify(finding, truth)

        if kind in ("reales", "aceptables"):
            if item_id in seen:
                kind = "repetido"
                result["repetidos"] += 1
            else:
                seen.add(item_id)
                result["aciertos"] += 1

                if kind == "reales":
                    result["reales_detectados"].append(item_id)
        elif kind == "falsos":
            result["falsos"] += 1
        else:
            result["no_clasificados"].append(finding)

        result["detalle"].append({"tipo": kind, "id": item_id, "texto": finding})

    return result


def ratio(numerator, denominator):
    return f"{numerator / denominator:.2f}" if denominator else "n/a"


def run_review(registry, settings, mode, file_path):
    if mode == "deep":
        return registry.execute("review_file_deep", file_path=str(file_path))

    return registry.execute(
        "review_project_files",
        file_paths=[str(file_path)],
        max_chars=settings.get("context_limits")["review_project_file"],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--modo", choices=["deep", "archivo", "ambos"], default="ambos")
    parser.add_argument("--out", type=Path, help="carpeta para respuestas y métricas")
    args = parser.parse_args()

    settings = SettingsManager()
    registry = ToolRegistry(ProviderRouter())
    modes = ["deep", "archivo"] if args.modo == "ambos" else [args.modo]
    cases = sorted(p for p in CASES_DIR.glob("*.py"))
    runs = []

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    for mode in modes:
        for case in cases:
            truth = load_truth(case.name)

            for run in range(1, args.runs + 1):
                report = run_review(registry, settings, mode, case)
                result = score(extract_findings(report), truth)
                result.update({"modo": mode, "caso": case.name, "corrida": run})
                runs.append(result)

                descartados = re.search(r"Descartados[^:]*:\s*(\d+)", report)
                result["descartados"] = int(descartados.group(1)) if descartados else 0

                print(
                    f"[{mode:7}] {case.name:12} #{run}: "
                    f"reportados={result['reportados']:2} aciertos={result['aciertos']} "
                    f"reales={result['reales_detectados']} falsos={result['falsos']} "
                    f"repetidos={result['repetidos']} "
                    f"no_clasif={len(result['no_clasificados'])} "
                    f"descartados={result['descartados']}"
                )

                if args.out:
                    name = f"{mode}_{case.stem}_{run}.txt"
                    (args.out / name).write_text(report, encoding="utf-8")

    print("\nResumen (sumando todas las corridas):")

    for mode in modes:
        selected = [r for r in runs if r["modo"] == mode]
        reported = sum(r["reportados"] for r in selected)
        hits = sum(r["aciertos"] for r in selected)
        found = sum(len(r["reales_detectados"]) for r in selected)
        expected = sum(len(r["reales_esperados"]) for r in selected)
        false = sum(r["falsos"] for r in selected)
        repeated = sum(r["repetidos"] for r in selected)
        unknown = sum(len(r["no_clasificados"]) for r in selected)

        print(
            f"  {mode:7}: precisión={ratio(hits, reported)} ({hits}/{reported})  "
            f"recall={ratio(found, expected)} ({found}/{expected})  "
            f"falsos={false} repetidos={repeated} no_clasificados={unknown}"
        )

    unknown_items = [
        (r["modo"], r["caso"], text)
        for r in runs
        for text in r["no_clasificados"]
    ]

    if unknown_items:
        print("\nNo clasificados (revisar a mano; cuentan como no acertados):")

        for mode, case, text in unknown_items:
            print(f"  [{mode}] {case}: {text[:160]}")

    if args.out:
        (args.out / "metricas.json").write_text(
            json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
