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
cuántas de 24 preguntas responde (8 de C:\\Asia, 3 de Bolitabot y 13 de documentación, 4 de ellas de Python), cuántas citan el archivo correcto en las líneas
verificadas, cuántas frases de la redacción quedan limpias, se eliminan o se marcan "(sin cita)" y por qué, si dice sin
marca una de las tres frases falsas conocidas (el límite conocido, aparte) y a cuántas de 9 trampas responde. "Con resumen" es que quedó alguna frase. Las trampas pasan
el filtro de cobertura pero no tienen respuesta en C:\\Asia: una cita verificada
prueba que la línea existe, no que responda, así que su respuesta se imprime entera
para leerla. Mide sobre una copia del índice sin este archivo ni los fragmentos que
contengan una trampa: si no, el modelo podría "citar" la pregunta misma. Cada corrida
tarda minutos en CPU. Ahí y en el ranking, al ROADMAP se le quitan las líneas que citan
una pregunta del benchmark: anota los resultados y saldría primero por repetirla.

    .venv\\Scripts\\python.exe test\\manual\\check_rag.py --punta-a-punta 2

Las ajenas (nada que ver con ninguna fuente) también pasan por la cadena: la distancia
de embeddings deja llegar algunas al modelo. Los glosarios son de la medición, en una
carpeta temporal; --sin-glosario mide sin ellos.

Para calibrar el filtro, la cobertura y la distancia de cada pregunta, sin el modelo:

    .venv\\Scripts\\python.exe test\\manual\\check_rag.py --calibrar

Wikipedia offline, aparte para que no cambien las bases de lo demás: si el artículo
esperado está entre los que elige la búsqueda del .zim (sin modelo, con 0 corridas) y,
con corridas, si la respuesta esperada sale en las líneas verificadas y si se responde
alguna trampa (preguntas cuyo artículo no está en el top). Usa la fuente "wikipedia" de
la biblioteca y una caché de embeddings temporal: la corrida 1 es en frío.

    .venv\\Scripts\\python.exe test\\manual\\check_rag.py --wikipedia 1

Sale con código 1 si el ranking baja de check_rag_base.json, si se responde una trampa
o una ajena, o si alguna corrida supera el límite conocido de ese archivo. Lo demás
del punta a punta varía con el azar del 7B: se lee, no se comprueba.
"""
import argparse
import gc
import json
import re
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
from core.rag.embedder import OllamaEmbedder
from core.rag.indexer import ProjectIndexer, unload_chat_models
from core.rag.library import Library, named_in_question, without_source
from core.rag.quotes import BAD_TAG, NOT_DEFINED, UNKNOWN_FIGURE, UNKNOWN_NAME
from core.rag.retriever import relevant, search_collections
from tools import rag_tool
from tools.rag_tool import DEFAULT_MAX_DISTANCE, DEFAULT_MIN_COVERAGE

COLLECTION = "asia"
TEMP_PREFIX = "asia_rag_"
REMOVE_TRIES = 5
REMOVE_WAIT_S = 1
KINDS = ("concepto", "documento", "nombre")
TOPS = (1, 3, 5)
# Por tipo, los aciertos en cada top; el límite conocido, por corrida.
BASE_FILE = Path(__file__).with_name("check_rag_base.json")

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


# En español, sobre documentación en inglés. El segundo dato es parte de su ruta.
DOCS = [
    ("cómo se publica un mensaje en un tópico desde la terminal en ros2", "Understanding-ROS2-Topics"),
    ("qué políticas de calidad de servicio QoS existen en ros2", "About-Quality-of-Service-Settings"),
    ("cómo se crea un paquete con ros2 pkg create en ros2", "Creating-Your-First-ROS2-Package"),
    ("cómo se escribe un archivo launch en Python en ros2", "Creating-Launch-Files"),
    ("cómo se conecta ROS 2 con Gazebo usando parameter_bridge en gazebo", "ros2_integration"),
    ("cómo se mueve un robot con el plugin de tracción diferencial en gazebo", "moving_robot"),
    ("cómo se crea un mundo en SDF en gazebo", "sdf_worlds"),
    ("a qué tipo de Gazebo corresponde geometry_msgs/msg/Twist en ros_gz_bridge", "README"),
    ("cómo se configura el puente con un archivo YAML en ros_gz_bridge", "README"),
    ("cómo se crea un entorno virtual con venv en python", "venv"),
    ("cómo se lee un archivo JSON en python", "json"),
    ("cómo se captura una excepción con try y except en python", "errors"),
    ("cómo se define una clase de datos con dataclass en python", "dataclasses"),
]

# Sobre esas fuentes, sin respuesta en ellas.
DOC_TRAPS = [
    "cuánto cuesta una licencia comercial en ros2",
    "cómo se entrena una red neuronal en gazebo",
    "cómo se programa una Raspberry Pi Pico en ros2",
    "cuál es el precio del robot Spot en gazebo",
    "cómo se dibuja un sprite con pygame en python",
]

# El de la medición: el real lo mantiene el usuario en data/biblioteca/.
GLOSSARIES = {
    "bolitabot": {"punto desplazado": ["x_front", "y_front"]},
    "ros2": {"calidad de servicio": ["QoS policies", "History", "Reliability", "Durability"]},
}

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
    *DOCS,
]


# Nada en C:\\Asia las responde: se preguntan "en asia", porque con más fuentes pueden
# tener respuesta (en Bolitabot sí hay un servidor, en el puerto 9090).
TRAPS = [
    "cómo se configura el firewall",
    "cómo se conecta la base de datos de usuarios",
    "cómo se cifra la contraseña del usuario",
    "qué puerto usa el servidor web",
]


# Las frases falsas que el ROADMAP recoge: citarlas no prueba nada, como con las trampas.
INDEXED_FALSE_CLAIMS = ['debes abrirlo con el modo "w"', 'el resumen "cada 3 segundos"']

# Tres respuestas falsas que pasaron todas las comprobaciones: el código no comprueba
# significado, así que pueden salir en el resumen no verificado. Es el límite conocido.
FORBIDDEN = {
    "cómo se escribe un archivo sin dejarlo a medias": r'modo\s+\W?w\b',
    "drop_client": r'(?:defin|se encuentra)[^.\n]*ollama_provider',
    "cómo se resume la sesión en segundo plano": r'cada\s+3\s*(?:s\b|seg)',
}

WIKIPEDIA = "wikipedia"

ROADMAP = "ROADMAP.md"
# Lo que se añade para nombrar la fuente: el ROADMAP cita la pregunta con o sin ello.
SOURCE_SUFFIX = re.compile(r" en (?:asia|bolitabot|ros2|gazebo|ros_gz_bridge|python|wikipedia)$", re.IGNORECASE)

# (pregunta, artículos que la responden, lo que tiene que salir en las líneas verificadas).
WIKIPEDIA_QUESTIONS = [
    ("cuál es la capital de Australia en wikipedia", ("Camberra",), r"Camberra|Canberra"),
    ("quién descubrió la penicilina en wikipedia", ("Alexander_Fleming", "Penicilina"), r"Fleming"),
    ("quién escribió Don Quijote de la Mancha en wikipedia", ("Don_Quijote_de_la_Mancha", "Miguel_de_Cervantes"), r"Cervantes"),
    ("quién pintó la Mona Lisa en wikipedia", ("La_Gioconda", "Leonardo_da_Vinci"), r"Leonardo"),
    ("en qué año cayó el muro de Berlín en wikipedia", ("Muro_de_Berlín", "Caída_del_Muro_de_Berlín"), r"1989"),
    ("a qué temperatura hierve el agua en wikipedia", ("Agua", "Punto_de_ebullición"), r"\b100\b"),
    ("cuántos huesos tiene el cuerpo humano en wikipedia", ("Esqueleto_humano",), r"\b206\b"),
    ("qué moneda se usa en Japón en wikipedia", ("Yen", "Japón"), r"\byen"),
    ("cuál es la montaña más alta del mundo en wikipedia", ("Monte_Everest",), r"Everest"),
    ("quién escribió Cien años de soledad en wikipedia", ("Cien_años_de_soledad", "Gabriel_García_Márquez"), r"García Márquez"),
    ("qué necesita una planta para hacer la fotosíntesis en wikipedia", ("Fotosíntesis",), r"\bluz\b"),
    ("en qué año llegó el hombre a la Luna en wikipedia", ("Apolo_11", "Programa_Apolo", "Luna"), r"1969"),
]

# Sus artículos no están en el top (has_entry_by_path, con el .zim de 2026-10): un dato
# así de concreto no debería estar en otro. Si se responde, se lee entera. Fuera la
# laguna de Bacalar y Copán Ruinas: "Bacalar" y "Departamento_de_Copán" sí están.
WIKIPEDIA_TRAPS = [
    "cuántos habitantes tiene Villarrubia de los Ojos en wikipedia",
    "en qué año se fundó Tlacolula de Matamoros en wikipedia",
    "dónde nace el río Ulúa en wikipedia",
    "qué minas había en Real del Monte en wikipedia",
    "cuántos habitantes tiene Purmamarca en wikipedia",
    "cuántos habitantes tiene Salento en el Quindío en wikipedia",
    "en qué año se fundó Barichara en wikipedia",
    "cuántos habitantes tiene Vilcabamba en Ecuador en wikipedia",
    "en qué año se fundó Concepción de Ataco en wikipedia",
    "qué altura tiene el Salto del Laja en wikipedia",
    "en qué año se creó el Parque nacional Conguillío en wikipedia",
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


def benchmark_questions() -> list:
    """Las preguntas de frase del benchmark, en minúsculas y sin la fuente al final.

    Los nombres exactos (drop_client) no: que el ROADMAP los nombre es contenido, no una cita.
    """
    questions = [q for q, _, _ in QUESTIONS] + [q for q, _ in DOCS + BOLITABOT] + TRAPS + DOC_TRAPS + UNANSWERABLE
    questions += [q for q, _, _ in WIKIPEDIA_QUESTIONS] + WIKIPEDIA_TRAPS
    return [SOURCE_SUFFIX.sub("", q).lower() for q in questions if " " in q]


def without_benchmark_lines(store, embedder=None) -> int:
    """Quita de los fragmentos del ROADMAP las líneas que citan una pregunta del benchmark.

    El ROADMAP anota los resultados con la pregunta entre comillas: sin esto sale primero
    por repetirla, como pasaría con las trampas. Se vuelven a embeber con el mismo id.
    Devuelve cuántas líneas quitó.
    """
    questions = benchmark_questions()
    indexed = store.all_documents()
    ids, documents, metadatas, removed = [], [], [], 0

    for doc_id, document, metadata in zip(indexed["ids"], indexed["documents"], indexed["metadatas"]):
        if (metadata or {}).get("relative_path") != ROADMAP:
            continue

        # La primera línea es "ROADMAP.md · sección", la de indexable_text.
        where, *lines = document.split("\n")
        kept = [line for line in lines if not any(q in line.lower() for q in questions)]

        if len(kept) < len(lines):
            removed += len(lines) - len(kept)
            ids.append(doc_id)
            documents.append("\n".join([where, *kept]))
            metadatas.append(metadata)

    if ids:
        store.add_documents(ids, documents, (embedder or OllamaEmbedder()).embed_documents(documents), metadatas)

    return removed


def load_base(path=None) -> dict:
    return json.loads(Path(path or BASE_FILE).read_text(encoding="utf-8"))


def ranking_failures(rows, base) -> list:
    """Cada top de cada tipo que baja de la base: una mejora en un tipo no tapa otro."""
    failures = []

    for kind in KINDS:
        found = in_top([r for r in rows if r[0] == kind])

        for top, got, expected in zip(TOPS, found, base["ranking"][kind]):
            if got < expected:
                failures.append(f"ranking, {kind}, top {top}: {got}, base {expected}")

    return failures


def end_to_end_failures(known_limit, traps, strangers, base) -> list:
    """known_limit: uno por corrida. traps y strangers: las respondidas, en total."""
    failures = []

    if max(known_limit) > base["limite_conocido"]:
        failures.append(f"límite conocido: {max(known_limit)} en una corrida, base {base['limite_conocido']}")

    if traps:
        failures.append(f"trampas respondidas: {traps}")

    if strangers:
        failures.append(f"ajenas respondidas: {strangers}")

    return failures


def finished(failures) -> int:
    """El código de salida. Dice qué falló."""
    for failure in failures:
        print(f"FALLA: {failure}")

    return 1 if failures else 0


def relative(path: str) -> str:
    return path.replace("\\", "/").removeprefix(ROOT.as_posix() + "/")


def build_index(folder):
    unload_chat_models()
    indexer = ProjectIndexer(str(ROOT), COLLECTION, persist_dir=folder)
    start = time.perf_counter()
    count = indexer.index_project()
    seconds = time.perf_counter() - start
    print(f"ROADMAP: {without_benchmark_lines(indexer.store)} líneas que citan el benchmark, fuera.", flush=True)
    return count, seconds


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


def in_top(rows) -> list:
    """Cuántas filas tienen el archivo correcto en cada top."""
    return [sum(1 for r in rows if r[1] and r[1] <= top) for top in TOPS]


def table(rows) -> str:
    lines = ["| Tipo | 1.º | Top 3 | Top 5 |", "|---|---|---|---|"]

    def line(name, subset):
        hits = in_top(subset)
        return f"| {name} | " + " | ".join(f"{h}/{len(subset)}" for h in hits) + " |"

    lines.append(line("Total", rows))

    for kind in KINDS:
        lines.append(line(kind.capitalize(), [r for r in rows if r[0] == kind]))

    return "\n".join(lines)


ANSWERED = ("respondió", "solo líneas", "redacción inválida")
PROJECT_QUESTIONS = len(END_TO_END) - len(BOLITABOT) - len(DOCS)


def by_source(rows) -> tuple:
    """Las filas de END_TO_END de Asia, de Bolitabot y de la documentación."""
    bolitabot = PROJECT_QUESTIONS + len(BOLITABOT)
    return rows[:PROJECT_QUESTIONS], rows[PROJECT_QUESTIONS:bolitabot], rows[bolitabot:]


def count_answered(rows) -> str:
    return f"{sum(1 for row in rows if row[0] == 'respondió')}/{len(rows)}"


def forbidden_said(question, shown) -> bool:
    """True si el resumen dice la frase falsa conocida de esa pregunta."""
    summary = shown.partition(prompts.UNVERIFIED_SUMMARY)[2].splitlines()
    unmarked = "\n".join(line for line in summary if not line.endswith(prompts.UNCITED))
    return question in FORBIDDEN and bool(re.search(FORBIDDEN[question], unmarked, re.IGNORECASE))


def answer_row(brain, question, expected=None):
    """(estado, cita el archivo, segundos, lo que se muestra) de una pregunta con el modelo real."""
    start = time.perf_counter()
    shown = brain.process(f"/buscar {question}")
    seconds = time.perf_counter() - start

    if shown in prompts.NOTHING_TO_ANSWER:
        return "el código negó", False, seconds, shown

    if shown.startswith(prompts.NO_DIRECT_ANSWER):
        return "sin respuesta directa", False, seconds, shown

    lines, _, summary = shown.partition(prompts.VERIFIED_LINES)[2].partition(prompts.UNVERIFIED_SUMMARY)
    state = "respondió" if summary else "redacción inválida" if shown.startswith(prompts.INVALID_DRAFT) else "solo líneas"
    return state, bool(expected) and Path(expected).name.lower() in lines.lower(), seconds, shown


def clean_copy(folder):
    """Copia data/chroma en folder sin los fragmentos que traen las preguntas, y busca ahí."""
    shutil.copytree(vector_store.CHROMA_DIR, folder)
    store = vector_store.VectorStore(persist_dir=folder, collection_name=COLLECTION)
    indexed = store.all_documents()
    questions = [question.lower() for question in TRAPS + INDEXED_FALSE_CLAIMS]
    this_file = relative(__file__)
    ids = [
        doc_id
        for doc_id, document, metadata in zip(indexed["ids"], indexed["documents"], indexed["metadatas"])
        if metadata.get("relative_path") == this_file or any(q in document.lower() for q in questions)
    ]

    store.delete_ids(ids)
    lines = without_benchmark_lines(store)
    vector_store.CHROMA_DIR = folder
    print(f"Índice de la medición: {store.collection.count()} fragmentos, {len(ids)} fuera; "
          f"{lines} líneas del ROADMAP que citan el benchmark, fuera.", flush=True)


def calibration_row(group, question, sources, expected=""):
    """Lo que ve el filtro: la mejor cobertura y la menor distancia de los fragmentos."""
    named = named_in_question(question, sources)
    collections = [named.collection] if named else [source.collection for source in sources]
    query = without_source(question, named) if named else question
    hits = search_collections(query, collections, n_results=5)
    distances = [hit.distance for hit in hits if hit.distance is not None]
    coverage = max((hit.coverage for hit in hits), default=0.0)
    distance = min(distances, default=float("inf"))
    files = [hit.metadata.get("relative_path", "") for hit in hits]
    place = next((i for i, name in enumerate(files, 1) if expected in name), "-") if expected else ""
    print(f"{group:<10} cobertura {coverage:.2f}  distancia {distance:7.1f}  {place!s:>2} {question[:60]}", flush=True)


def calibrate():
    sources = Library().all()

    for question, _, _ in QUESTIONS:
        calibration_row("con", question, sources)

    for question, _ in BOLITABOT:
        calibration_row("bolitabot", question, sources)

    for question, expected in DOCS:
        calibration_row("docs", question, sources, expected)

    for question in TRAPS:
        calibration_row("trampa", f"{question} en asia", sources)

    for question in DOC_TRAPS:
        calibration_row("trampa doc", question, sources)

    for question in UNANSWERABLE:
        calibration_row("ajena", f"{question} en asia", sources)

    for question in UNANSWERABLE:
        calibration_row("ajena+bol", question, sources)

    return 0


def end_to_end(runs, glossary_dir, base):
    from core import paths
    from core.brain import Brain
    from core.session import Session

    Session.set_paths(project_root=paths.PROJECT_ROOT, user_cwd=ROOT)
    # Sin glosario, una carpeta sin archivos; nunca el del usuario.
    paths.GLOSSARY_DIR = glossary_dir or Path(tempfile.gettempdir()) / f"{TEMP_PREFIX}sin_glosario"

    if glossary_dir:
        for name, glossary in GLOSSARIES.items():
            (glossary_dir / f"glosario_{name}.json").write_text(json.dumps(glossary), encoding="utf-8")

    brain = Brain()
    check = explore.check_draft
    verify = explore.verify_quotes
    clean = explore.clean_translation
    sentences = []

    def showing_translation(answer):
        translated = clean(answer)
        print(f"    traducción: {translated}", flush=True)
        return translated

    explore.clean_translation = showing_translation

    def showing_extraction(extracted, context):
        quotes = verify(extracted, context)

        if not quotes:
            print(f"    extracción sin líneas: {' '.join(extracted.split())[:150]}", flush=True)

        return quotes

    explore.verify_quotes = showing_extraction

    def showing_removed(answer, quotes, question):
        shown, uncited, removed = check(answer, quotes, question)
        sentences.extend(["limpia"] * (len(shown) - len(uncited)))

        for name, group in (("eliminada", removed), ("sin cita", uncited)):
            for sentence, problems in group:
                sentences.append(UNKNOWN_NAME if group is removed else problems[0][0])
                print(f"    frase {name}, {problems}: {' '.join(sentence.split())[:200]}", flush=True)

        return shown, uncited, removed

    explore.check_draft = showing_removed
    summary = [
        "| Corrida | Con resumen | Asia | Bolitabot | Docs | Solo líneas | Sin respuesta directa en docs | Frases "
        "| Limpias | Eliminadas | Sin etiqueta | Dato | Definición | Límite conocido | Cita el archivo "
        "| Trampas respondidas | Ajenas respondidas | Segundos por pregunta |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    known_limit, all_fell, all_strayed = [], 0, 0

    for run in range(1, runs + 1):
        rows = []
        sentences.clear()

        for question, expected in END_TO_END:
            row = answer_row(brain, question, expected)
            rows.append(row)
            state, cited, seconds, shown = row
            opening = " ".join((shown.partition(prompts.UNVERIFIED_SUMMARY)[2] or shown).split())[:500]
            print(f"[{run}] {state}, {'cita' if cited else 'no cita'}, {seconds:.0f} s: {question[:45]} -> {opening}", flush=True)

            if forbidden_said(question, shown):
                print(f"    LÍMITE CONOCIDO: {question}", flush=True)

        traps = []

        strangers = []

        trap_questions = [f"{q} en asia" for q in TRAPS] + DOC_TRAPS

        for group, name, questions in ((traps, "TRAMPA", trap_questions), (strangers, "AJENA", UNANSWERABLE)):
            for question in questions:
                row = answer_row(brain, question)
                group.append(row)
                state, _, seconds, shown = row
                print(f"\n[{run}] {name} {state}, {seconds:.0f} s: {question}", flush=True)

                if state in ANSWERED:
                    print(shown, flush=True)

        answered = sum(1 for r in rows if r[0] == "respondió")
        only_lines = sum(1 for r in rows + traps + strangers if r[0] in ANSWERED[1:])
        tally = Counter(sentences)
        reasons = " | ".join(str(tally[kind]) for kind in ("limpia", UNKNOWN_NAME, BAD_TAG, UNKNOWN_FIGURE, NOT_DEFINED))
        cited = sum(1 for r in rows if r[1])
        forbidden = sum(forbidden_said(question, row[3]) for (question, _), row in zip(END_TO_END, rows))
        fell = sum(1 for r in traps if r[0] in ANSWERED)
        strayed = sum(1 for r in strangers if r[0] in ANSWERED)
        known_limit.append(forbidden)
        all_fell += fell
        all_strayed += strayed
        seconds = sum(r[2] for r in rows + traps + strangers) / len(rows + traps + strangers)
        groups = "".join(f"{count_answered(group)} | " for group in by_source(rows))
        refused = sum(1 for r in by_source(rows)[2] if r[0] == "sin respuesta directa")
        summary.append(
            f"| {run} | {answered}/{len(rows)} | {groups}{only_lines} | {refused} "
            f"| {len(sentences)} | {reasons} | {forbidden} | {cited}/{len(rows)} "
            f"| {fell}/{len(traps)} | {strayed}/{len(strangers)} | {seconds:.0f} |"
        )
        print()

    print("\n".join(summary))
    print(f"Límite conocido: {max(known_limit)} como máximo en una corrida, base {base['limite_conocido']}.")
    return finished(end_to_end_failures(known_limit, all_fell, all_strayed, base))


def wikipedia_correct(shown, pattern) -> bool:
    """True si la respuesta esperada está en las líneas verificadas, no en el resumen ni en el respaldo."""
    if prompts.VERIFIED_LINES not in shown:
        return False

    lines = shown.partition(prompts.VERIFIED_LINES)[2].partition(prompts.UNVERIFIED_SUMMARY)[0]
    return bool(re.search(pattern, lines, re.IGNORECASE))


def wikipedia_failures(found, traps, base) -> list:
    """found: preguntas con su artículo entre los encontrados. traps: las respondidas, en total."""
    failures = []
    expected = base[WIKIPEDIA]

    if found < expected["encontrados"]:
        failures.append(f"Wikipedia, artículo encontrado: {found}, base {expected['encontrados']}")

    if traps > expected["trampas"]:
        failures.append(f"Wikipedia, trampas respondidas: {traps}, base {expected['trampas']}")

    return failures


def wikipedia(runs, base):
    """La búsqueda en el .zim (sin modelo) y, con runs, las respuestas del modelo real."""
    from libzim.reader import Archive

    from core import paths
    from core.rag.wikipedia import found_articles

    source = Library().get(WIKIPEDIA)

    if source is None or not Path(source.path).is_file():
        print(f"Falta la fuente {WIKIPEDIA}: /indexar {WIKIPEDIA} <ruta del .zim> enciclopedia")
        return 1

    archive = Archive(source.path)
    found = 0

    for question, expected, _ in WIKIPEDIA_QUESTIONS:
        paths_found = [path for path, _, _ in found_articles(archive, without_source(question, source))]
        hit = bool(set(expected) & set(paths_found))
        found += hit
        print(f"{'sí' if hit else 'no'}: {question} -> {', '.join(paths_found) or 'nada'}", flush=True)

    for question in WIKIPEDIA_TRAPS:
        paths_found = [path for path, _, _ in found_articles(archive, without_source(question, source))]
        print(f"trampa: {question} -> {', '.join(paths_found) or 'nada'}", flush=True)

    print(f"\nArtículo esperado entre los encontrados: {found}/{len(WIKIPEDIA_QUESTIONS)}, "
          f"base {base[WIKIPEDIA]['encontrados']}.\n", flush=True)

    if not runs:
        return finished(wikipedia_failures(found, 0, base))

    from core.brain import Brain
    from core.session import Session

    Session.set_paths(project_root=paths.PROJECT_ROOT, user_cwd=ROOT)
    scratch = temp_folder()
    # Caché aparte: la corrida 1 embebe en frío y la 2 ya la tiene.
    paths.WIKIPEDIA_CACHE_FILE = scratch / "embeddings.sqlite3"
    brain = Brain()
    summary = [
        "| Corrida | Correctas | Respondió | Solo líneas | Sin respuesta directa | No lo encontré "
        "| Trampas respondidas | Segundos por pregunta |",
        "|---|---|---|---|---|---|---|---|",
    ]
    all_fell = 0

    try:
        for run in range(1, runs + 1):
            rows, traps = [], []

            for question, _, pattern in WIKIPEDIA_QUESTIONS:
                state, _, seconds, shown = answer_row(brain, question)
                correct = wikipedia_correct(shown, pattern)
                rows.append((state, correct, seconds))
                opening = " ".join((shown.partition(prompts.UNVERIFIED_SUMMARY)[2] or shown).split())[:300]
                print(f"[{run}] {state}, {'correcta' if correct else 'no'}, {seconds:.0f} s: {question} -> {opening}",
                      flush=True)

            for question in WIKIPEDIA_TRAPS:
                state, _, seconds, shown = answer_row(brain, question)
                traps.append((state, seconds))
                print(f"\n[{run}] TRAMPA {state}, {seconds:.0f} s: {question}", flush=True)

                # Una línea verificada prueba que existe, no que responda: se lee entera.
                if state in ANSWERED:
                    print(shown, flush=True)

            states = Counter(state for state, _, _ in rows)
            fell = sum(1 for state, _ in traps if state in ANSWERED)
            all_fell += fell
            seconds = (sum(r[2] for r in rows) + sum(t[1] for t in traps)) / (len(rows) + len(traps))
            summary.append(
                f"| {run} | {sum(1 for r in rows if r[1])}/{len(rows)} | {states['respondió']} "
                f"| {states['solo líneas'] + states['redacción inválida']} | {states['sin respuesta directa']} "
                f"| {states['el código negó']} | {fell}/{len(traps)} | {seconds:.0f} |"
            )
            print()
    finally:
        remove_tree(scratch)

    print("\n".join(summary))
    return finished(wikipedia_failures(found, all_fell, base))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--indice", help="carpeta del índice: se conserva y solo se reindexa lo que cambió")
    parser.add_argument("--punta-a-punta", type=int, metavar="CORRIDAS", help="mide las respuestas del modelo real")
    parser.add_argument("--max-distancia", type=float, help="umbral de distancia de la medición, en vez del de config")
    parser.add_argument("--sin-glosario", action="store_true", help="punta a punta sin el glosario de la medición")
    parser.add_argument("--calibrar", action="store_true", help="cobertura y distancia de cada pregunta")
    parser.add_argument("--fragmentos", type=int, help="fragmentos que recibe el modelo, en vez del valor del código")
    parser.add_argument("--wikipedia", type=int, metavar="CORRIDAS", help="Wikipedia offline; con 0, solo la búsqueda")
    args = parser.parse_args()
    base = load_base()
    sweep_leftovers()

    if args.wikipedia is not None:
        return wikipedia(args.wikipedia, base)

    if args.fragmentos:
        explore.RAG_FRAGMENTS = args.fragmentos

    if args.max_distancia:
        limits = {"min_coverage": DEFAULT_MIN_COVERAGE, "max_distance": args.max_distancia}
        rag_tool.SettingsManager = lambda: {"rag": limits}

    if args.punta_a_punta or args.calibrar:
        scratch = temp_folder()

        try:
            clean_copy(scratch / "chroma")

            if args.calibrar:
                return calibrate()

            return end_to_end(args.punta_a_punta, None if args.sin_glosario else scratch, base)
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
        return finished(ranking_failures(rows, base))
    finally:
        if not args.indice:
            remove_tree(folder)


if __name__ == "__main__":
    sys.exit(main())
