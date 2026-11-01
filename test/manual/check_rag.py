"""Benchmark del RAG: ¿el archivo correcto sale entre los primeros resultados?

Indexa C:\\Asia en una carpeta temporal con el código real, sin tocar
data/chroma, y hace preguntas cuyo archivo correcto se conoce. Mide en qué puesto
sale ese archivo (1.º, top 3, top 5) por tipo de pregunta: concepto, documento y
nombre exacto. Usa nomic-embed-text; descarga antes los demás modelos.

    .venv\\Scripts\\python.exe test\\manual\\check_rag.py
    .venv\\Scripts\\python.exe test\\manual\\check_rag.py --indice CARPETA   # lo crea o lo reutiliza

También mira las preguntas que no tienen respuesta en C:\\Asia: lo que ayuda a
decidir cuándo decir "no lo encontré".
"""
import argparse
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.rag.indexer import ProjectIndexer, unload_chat_models
from core.rag.retriever import relevant, search_collections
from tools.rag_tool import DEFAULT_MIN_COVERAGE

COLLECTION = "asia"
KINDS = ("concepto", "documento", "nombre")
TOPS = (1, 3, 5)

# (pregunta, archivo correcto, tipo)
QUESTIONS = [
    ("cómo se decide si una frase es charla y va directo al chat", "core/fast_chat.py", "concepto"),
    ("dónde se recorta el audio para pasarle solo la voz a Whisper", "core/voice/session.py", "concepto"),
    ("cómo se escribe un archivo sin dejarlo a medias", "core/atomic_write.py", "concepto"),
    ("cómo se detectan rutas inventadas por el modelo", "core/brain.py", "concepto"),
    ("qué pasa si Ctrl+C llega mientras se espera al modelo", "core/interruptible.py", "concepto"),
    ("cómo se filtran secretos antes de enviar a un proveedor externo", "core/secrets_filter.py", "concepto"),
    ("cómo se elige la voz de Piper y dónde se guardan las voces", "core/voice/tts.py", "concepto"),
    ("dónde se guarda la bitácora de envíos externos", "core/audit.py", "concepto"),
    ("cómo se resume la sesión en segundo plano", "core/reflection.py", "concepto"),
    ("cómo se comprueban los imports del código generado", "tools/import_check.py", "concepto"),
    ("cómo se corta una respuesta en frases para leerla en voz alta", "core/voice/reading.py", "concepto"),
    ("cómo se guardan los pendientes del usuario", "core/tasks.py", "concepto"),
    ("qué voces de Piper se descargaron y qué licencia tienen", "ROADMAP.md", "documento"),
    ("cómo vuelvo a jarvis.bat si quito el ejecutable", "README.md", "documento"),
    ("drop_client", "providers/ollama_models.py", "nombre"),
    ("SessionSummarizer", "core/reflection.py", "nombre"),
    ("MARGIN_FRAMES", "core/voice/session.py", "nombre"),
    ("safe_collection_name", "core/rag/vector_store.py", "nombre"),
    ("is_clear_chat", "core/fast_chat.py", "nombre"),
    ("SentenceSplitter", "core/voice/reading.py", "nombre"),
]

# Nada en C:\\Asia las responde.
UNANSWERABLE = [
    "cuál es la capital de Australia",
    "cómo se calibra un sensor de temperatura PT100",
    "qué dice el contrato de arrendamiento del departamento",
    "receta de mole poblano",
    "cuántos goles metió Maradona en el mundial de 1986",
]


def relative(path: str) -> str:
    return path.replace("\\", "/").removeprefix(ROOT.as_posix() + "/")


def build_index(folder):
    unload_chat_models()
    indexer = ProjectIndexer(str(ROOT), COLLECTION, persist_dir=folder)
    start = time.perf_counter()
    count = indexer.index_project()
    return count, time.perf_counter() - start


def rank_of(expected, files):
    return files.index(expected) + 1 if expected in files else None


def measure(folder):
    rows, seconds = [], 0.0

    for question, expected, kind in QUESTIONS:
        start = time.perf_counter()
        hits = search_collections(question, [COLLECTION], n_results=max(TOPS), persist_dir=folder)
        seconds += time.perf_counter() - start
        files = [relative(hit.metadata["file_path"]) for hit in hits]
        best = hits[0] if hits else None
        rows.append((kind, rank_of(expected, files), question, files[:3], best, hits))

    return rows, seconds / len(QUESTIONS)


def describe(hit) -> str:
    if hit is None:
        return "sin resultados"

    distance = "—" if hit.distance is None else f"{hit.distance:.1f}"
    return f"distancia {distance}, cobertura {hit.coverage:.2f}"


def table(rows) -> str:
    lines = ["| Tipo | 1.º | Top 3 | Top 5 |", "|---|---|---|---|"]

    def line(name, subset):
        hits = [sum(1 for r in subset if r[1] and r[1] <= top) for top in TOPS]
        return f"| {name} | " + " | ".join(f"{h}/{len(subset)}" for h in hits) + " |"

    lines.append(line("Total", rows))

    for kind in KINDS:
        lines.append(line(kind.capitalize(), [r for r in rows if r[0] == kind]))

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--indice", help="carpeta del índice: se conserva y solo se reindexa lo que cambió")
    args = parser.parse_args()
    folder = Path(args.indice) if args.indice else Path(tempfile.mkdtemp(prefix="asia_rag_"))

    try:
        count, seconds = build_index(folder)
        print(f"Índice: {count} fragmentos en {seconds:.0f} s ({seconds / max(count, 1) * 1000:.0f} ms/fragmento).")

        rows, query_seconds = measure(folder)
        print(f"Consulta: {query_seconds * 1000:.0f} ms.\n")

        for kind, rank, question, files, best, _ in rows:
            print(f"{rank or '—':>2} [{kind}] {question[:58]} -> {', '.join(files)} ({describe(best)})")

        print("\nSin respuesta en C:\\Asia:")
        refused = 0

        for question in UNANSWERABLE:
            hits = search_collections(question, [COLLECTION], n_results=max(TOPS), persist_dir=folder)
            found = relevant(hits, DEFAULT_MIN_COVERAGE)
            refused += not found
            print(f"   {'responde' if found else 'no lo encontré'}: {question[:58]} ({describe(hits[0] if hits else None)})")

        wrongly = [r[2] for r in rows if not relevant(r[5], DEFAULT_MIN_COVERAGE)]
        print(f"\nDice \"no lo encontré\": {refused}/{len(UNANSWERABLE)} de las que no tienen respuesta, "
              f"{len(wrongly)}/{len(rows)} de las que sí (mal).")

        for question in wrongly:
            print(f"   mal: {question}")

        print(f"\n{table(rows)}")
        print("Archivos que más salen primero:", Counter(r[3][0] for r in rows if r[3]).most_common(4))
    finally:
        if not args.indice:
            shutil.rmtree(folder, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
