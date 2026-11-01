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
cuántas de 11 preguntas responde (8 de C:\\Asia y 3 de Bolitabot), cuántas citan el archivo correcto en las líneas
verificadas, cuántas redacciones se invalidan por nombres o citas que no existen, y a cuántas de 4 trampas responde. Las trampas pasan
el filtro de cobertura pero no tienen respuesta en C:\\Asia: una cita verificada
prueba que la línea existe, no que responda, así que su respuesta se imprime entera
para leerla. Mide sobre una copia del índice sin este archivo ni los fragmentos que
contengan una trampa: si no, el modelo podría "citar" la pregunta misma. Cada corrida
tarda minutos en CPU.

    .venv\\Scripts\\python.exe test\\manual\\check_rag.py --punta-a-punta 2

Para calibrar el filtro, la cobertura y la distancia de cada pregunta, sin el modelo:

    .venv\\Scripts\\python.exe test\\manual\\check_rag.py --calibrar
"""
import argparse
import gc
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
from core.rag.library import Library, named_in_question, without_source
from core.rag.retriever import relevant, search_collections
from tools.rag_tool import DEFAULT_MAX_DISTANCE, DEFAULT_MIN_COVERAGE

COLLECTION = "asia"
TEMP_PREFIX = "asia_rag_"
REMOVE_TRIES = 5
REMOVE_WAIT_S = 1
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


# Casos reales, de la prueba con el repo de Bolitabot. La respuesta está en el código
# de un bloque de Simulink, con pocas palabras en común con la pregunta.
BOLITABOT = [
    ("qué límite de velocidad tiene el controlador en bolitabot", "controlador_trebol.slx"),
    ("cuánto dura cada tramo del trébol en bolitabot", "controlador_trebol.slx"),
    ("cómo se calcula el punto desplazado en bolitabot", "controlador_trebol.slx"),
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
    *BOLITABOT,
]


# Nada en C:\\Asia las responde: se preguntan "en asia", porque con más fuentes pueden
# tener respuesta (en Bolitabot sí hay un servidor, en el puerto 9090).
TRAPS = [
    "cómo se configura el firewall",
    "cómo se conecta la base de datos de usuarios",
    "cómo se cifra la contraseña del usuario",
    "qué puerto usa el servidor web",
]


def release_chroma():
    """Suelta los archivos de Chroma: en Windows los tiene abiertos hasta que se para su sistema."""
    from chromadb.api.shared_system_client import SharedSystemClient

    for system in list(SharedSystemClient._identifier_to_system.values()):
        system.stop()

    SharedSystemClient.clear_system_cache()
    gc.collect()


def remove_tree(folder, tries=REMOVE_TRIES) -> bool:
    """Borra folder, con reintento si Windows la tiene bloqueada. False si no se pudo."""
    release_chroma()

    for attempt in range(tries):
        try:
            shutil.rmtree(folder)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if attempt + 1 < tries:
                time.sleep(REMOVE_WAIT_S)

    print(f"No se pudo borrar {folder}: la próxima corrida lo vuelve a intentar.", file=sys.stderr)
    return False


def temp_folder() -> Path:
    return Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))


def sweep_leftovers(base=None):
    """Borra lo que dejaron corridas anteriores que no terminaron."""
    for folder in Path(base or tempfile.gettempdir()).glob(f"{TEMP_PREFIX}*"):
        remove_tree(folder, tries=1)


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

    state = "redacción inválida" if shown.startswith(prompts.INVALID_DRAFT) else "respondió"
    sources = shown.rpartition(prompts.VERIFIED_LINES)[2].lower()
    return state, bool(expected) and Path(expected).name.lower() in sources, seconds, shown


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

    if ids:
        store.collection.delete(ids=ids)

    vector_store.CHROMA_DIR = folder
    print(f"Índice de la medición: {store.collection.count()} fragmentos, {len(ids)} fuera.", flush=True)


def calibration_row(group, question, sources):
    """Lo que ve el filtro: la mejor cobertura y la menor distancia de los fragmentos."""
    named = named_in_question(question, sources)
    collections = [named.collection] if named else [source.collection for source in sources]
    query = without_source(question, named) if named else question
    hits = search_collections(query, collections, n_results=5)
    distances = [hit.distance for hit in hits if hit.distance is not None]
    coverage = max((hit.coverage for hit in hits), default=0.0)
    distance = min(distances, default=float("inf"))
    print(f"{group:<10} cobertura {coverage:.2f}  distancia {distance:7.1f}  {question[:60]}", flush=True)


def calibrate():
    sources = Library().all()

    for question, _, _ in QUESTIONS:
        calibration_row("con", question, sources)

    for question, _ in BOLITABOT:
        calibration_row("bolitabot", question, sources)

    for question in TRAPS:
        calibration_row("trampa", f"{question} en asia", sources)

    for question in UNANSWERABLE:
        calibration_row("ajena", f"{question} en asia", sources)

    for question in UNANSWERABLE:
        calibration_row("ajena+bol", question, sources)

    return 0


def end_to_end(runs):
    from core import paths
    from core.brain import Brain
    from core.session import Session

    Session.set_paths(project_root=paths.PROJECT_ROOT, user_cwd=ROOT)
    brain = Brain()
    check = explore.draft_problems

    def showing_problems(answer, quotes, context):
        problems = check(answer, quotes, context)

        if problems:
            print(f"    invalidada por {problems} en: {' '.join(answer.split())[:300]}", flush=True)

        return problems

    explore.draft_problems = showing_problems
    summary = [
        "| Corrida | Responde | Redacciones inválidas | Cita el archivo | Trampas respondidas | Segundos por pregunta |",
        "|---|---|---|---|---|---|",
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
            row = answer_row(brain, f"{question} en asia")
            traps.append(row)
            state, _, seconds, shown = row
            print(f"\n[{run}] TRAMPA {state}, {seconds:.0f} s: {question}", flush=True)

            if state != "sin respuesta directa":
                print(shown, flush=True)

        answered = sum(1 for r in rows if r[0] == "respondió")
        invalid = sum(1 for r in rows + traps if r[0] == "redacción inválida")
        cited = sum(1 for r in rows if r[1])
        fell = sum(1 for r in traps if r[0] != "sin respuesta directa")
        seconds = sum(r[2] for r in rows + traps) / len(rows + traps)
        summary.append(
            f"| {run} | {answered}/{len(rows)} | {invalid} | {cited}/{len(rows)} | {fell}/{len(traps)} | {seconds:.0f} |"
        )
        print()

    print("\n".join(summary))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--indice", help="carpeta del índice: se conserva y solo se reindexa lo que cambió")
    parser.add_argument("--punta-a-punta", type=int, metavar="CORRIDAS", help="mide las respuestas del modelo real")
    parser.add_argument("--calibrar", action="store_true", help="cobertura y distancia de cada pregunta")
    parser.add_argument("--fragmentos", type=int, help="fragmentos que recibe el modelo, en vez del valor del código")
    args = parser.parse_args()
    sweep_leftovers()

    if args.fragmentos:
        explore.RAG_FRAGMENTS = args.fragmentos

    if args.punta_a_punta or args.calibrar:
        scratch = temp_folder()

        try:
            clean_copy(scratch / "chroma")
            return calibrate() if args.calibrar else end_to_end(args.punta_a_punta)
        finally:
            remove_tree(scratch)

    folder = Path(args.indice) if args.indice else temp_folder()

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
            found = relevant(hits, DEFAULT_MIN_COVERAGE, DEFAULT_MAX_DISTANCE)
            refused += not found
            print(f"   {'responde' if found else 'no lo encontré'}: {question[:58]} ({describe(hits[0] if hits else None)})")

        wrongly = [r[2] for r in rows if not relevant(r[5], DEFAULT_MIN_COVERAGE, DEFAULT_MAX_DISTANCE)]
        print(f"\nDice \"no lo encontré\": {refused}/{len(UNANSWERABLE)} de las que no tienen respuesta, "
              f"{len(wrongly)}/{len(rows)} de las que sí (mal).")

        for question in wrongly:
            print(f"   mal: {question}")

        print(f"\n{table(rows)}")
        print("Archivos que más salen primero:", Counter(r[3][0] for r in rows if r[3]).most_common(4))
    finally:
        if not args.indice:
            remove_tree(folder)

    return 0


if __name__ == "__main__":
    sys.exit(main())
