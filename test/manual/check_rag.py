"""Benchmark del RAG: ¿el archivo correcto sale entre los primeros resultados?

Indexa C:\\Asia en una carpeta temporal con el código real, sin tocar
data/chroma, y hace preguntas cuyo archivo correcto se conoce. Mide en qué puesto
sale ese archivo (1.º, top 3, top 5) por tipo de pregunta: concepto, documento y
nombre exacto. Usa nomic-embed-text; descarga antes los demás modelos.

    .venv\\Scripts\\python.exe test\\manual\\check_rag.py
    .venv\\Scripts\\python.exe test\\manual\\check_rag.py --indice CARPETA   # lo crea o lo reutiliza

También mira las preguntas que no tienen respuesta en C:\\Asia: lo que ayuda a
decidir cuándo decir "no lo encontré".

Punta a punta, con el modelo real y el índice real (data/chroma, solo lectura):
cuántas de 8 preguntas responde, cuántas citan el archivo correcto en "Fuentes:",
que sale de líneas verificadas, y a cuántas de 4 trampas responde. Las trampas pasan
el filtro de cobertura pero no tienen respuesta en C:\\Asia: una cita verificada
prueba que la línea existe, no que responda, así que su respuesta se imprime entera
para leerla. Mide sobre una copia del índice sin este archivo ni los fragmentos que
contengan una trampa: si no, el modelo podría "citar" la pregunta misma. Cada corrida
tarda minutos en CPU.

    .venv\\Scripts\\python.exe test\\manual\\check_rag.py --punta-a-punta 2
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

from core import prompts
from core.actions import explore
from core.rag import vector_store
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


# (pregunta, archivo correcto). Salen en el top 5 de la búsqueda: lo que se mide
# aquí es al modelo, no a la búsqueda.
END_TO_END = [
    ("cómo se escribe un archivo sin dejarlo a medias", "core/atomic_write.py"),
    ("qué pasa si Ctrl+C llega mientras se espera al modelo", "core/interruptible.py"),
    ("cómo se filtran secretos antes de enviar a un proveedor externo", "core/secrets_filter.py"),
    ("cómo se resume la sesión en segundo plano", "core/reflection.py"),
    ("cómo se guardan los pendientes del usuario", "core/tasks.py"),
    ("cómo vuelvo a jarvis.bat si quito el ejecutable", "README.md"),
    ("drop_client", "providers/ollama_models.py"),
    ("SentenceSplitter", "core/voice/reading.py"),
]


# Pasan el filtro de cobertura y nada en C:\\Asia las responde.
TRAPS = [
    "cómo se configura el firewall",
    "cómo se conecta la base de datos de usuarios",
    "cómo se cifra la contraseña del usuario",
    "qué puerto usa el servidor web",
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


def answer_row(brain, question, expected=None):
    """(estado, cita el archivo, segundos, lo que se muestra) de una pregunta con el modelo real."""
    start = time.perf_counter()
    shown = brain.process(f"/buscar {question}")
    seconds = time.perf_counter() - start

    if shown == prompts.NOT_FOUND:
        return "el código negó", False, seconds, shown

    if shown.startswith(prompts.NO_DIRECT_ANSWER):
        return "sin respuesta directa", False, seconds, shown

    sources = shown.rpartition("Fuentes:")[2].lower()
    return "respondió", bool(expected) and Path(expected).name.lower() in sources, seconds, shown


def clean_copy(folder):
    """Copia data/chroma en folder sin los fragmentos que traen las preguntas, y busca ahí."""
    shutil.copytree(vector_store.CHROMA_DIR, folder)
    store = vector_store.VectorStore(persist_dir=folder, collection_name=COLLECTION)
    indexed = store.all_documents()
    questions = [question.lower() for question in TRAPS]
    this_file = relative(__file__)
    ids = [
        doc_id
        for doc_id, document, metadata in zip(indexed["ids"], indexed["documents"], indexed["metadatas"])
        if metadata.get("relative_path") == this_file or any(q in document.lower() for q in questions)
    ]
    store.collection.delete(ids=ids)
    vector_store.CHROMA_DIR = folder
    print(f"Índice de la medición: {store.collection.count()} fragmentos, {len(ids)} fuera.", flush=True)


def end_to_end(runs):
    from core import paths
    from core.brain import Brain
    from core.session import Session

    Session.set_paths(project_root=paths.PROJECT_ROOT, user_cwd=ROOT)
    brain = Brain()
    summary = [
        "| Corrida | Responde | Cita el archivo | Trampas respondidas | Segundos por pregunta |",
        "|---|---|---|---|---|",
    ]

    for run in range(1, runs + 1):
        rows = []

        for question, expected in END_TO_END:
            row = answer_row(brain, question, expected)
            rows.append(row)
            state, cited, seconds, shown = row
            opening = " ".join(shown.split())[:90]
            print(f"[{run}] {state}, {'cita' if cited else 'no cita'}, {seconds:.0f} s: {question[:45]} -> {opening}", flush=True)

        traps = []

        for question in TRAPS:
            row = answer_row(brain, question)
            traps.append(row)
            state, _, seconds, shown = row
            print(f"\n[{run}] TRAMPA {state}, {seconds:.0f} s: {question}", flush=True)

            if state == "respondió":
                print(shown, flush=True)

        answered = sum(1 for r in rows if r[0] == "respondió")
        cited = sum(1 for r in rows if r[1])
        fell = sum(1 for r in traps if r[0] == "respondió")
        seconds = sum(r[2] for r in rows + traps) / len(rows + traps)
        summary.append(f"| {run} | {answered}/{len(rows)} | {cited}/{len(rows)} | {fell}/{len(traps)} | {seconds:.0f} |")
        print()

    print("\n".join(summary))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--indice", help="carpeta del índice: se conserva y solo se reindexa lo que cambió")
    parser.add_argument("--punta-a-punta", type=int, metavar="CORRIDAS", help="mide las respuestas del modelo real")
    parser.add_argument("--fragmentos", type=int, help="fragmentos que recibe el modelo, en vez del valor del código")
    args = parser.parse_args()

    if args.fragmentos:
        explore.RAG_FRAGMENTS = args.fragmentos

    if args.punta_a_punta:
        scratch = Path(tempfile.mkdtemp(prefix="asia_rag_"))

        try:
            clean_copy(scratch / "chroma")
            return end_to_end(args.punta_a_punta)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

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
