"""Wikipedia offline (fase H, capa 3): se busca en el .zim, no se indexa.

La búsqueda de texto del .zim elige los artículos y los embeddings solo ordenan sus
fragmentos, en el momento y con caché. Da Hit como una colección, para que lo
demás de la cadena (filtro, extracción, verificación) no sepa de dónde viene.
"""
import re
from pathlib import Path

from core.rag.article import article_chunks
from core.rag.embedder import OllamaEmbedder
from core.rag.embedding_cache import EmbeddingCache
from core.rag.library import ENGLISH_SOURCE, WIKI_SUFFIX
from core.rag.retriever import CANDIDATES, Hit, merge
from core.rag.tokens import WORD, tokenize
from core.rag.word_index import ENGLISH, SPANISH, inverse_frequency

ARTICLES = 3
# Lo que da la búsqueda antes de seguir redirecciones, que pueden repetir artículo.
SEARCH_RESULTS = 10
# Por artículo: 40 fragmentos por pregunta. Un artículo largo pasa de 500.
ARTICLE_FRAGMENTS = 13
NOT_IN_TAG = re.compile(r"_*[^\w.-]+_*")
FALLBACK_SLUG = "articulo"


def slug_of(path: str) -> str:
    """Una etiqueta que la verificación reconoce: "Mercurio_(planeta)" da "Mercurio_planeta.wiki"."""
    return (NOT_IN_TAG.sub("_", path).strip("_") or FALLBACK_SLUG) + WIKI_SUFFIX


def zim_summary(path: str) -> dict:
    """{"articles": n, "searchable": bool}: lo que hay que saber antes de registrar el archivo."""
    from libzim.reader import Archive

    archive = Archive(str(path))
    return {"articles": archive.article_count, "searchable": archive.has_fulltext_index}


def edition_of(archive) -> str:
    """"2026-10", del metadato Date. Vacía si no lo tiene."""
    return archive.get_metadata("Date").decode("utf-8")[:7] if "Date" in archive.metadata_keys else ""


def search_for(archive, question: str):
    """La búsqueda de las palabras con contenido de question, o None si no hay resultados.

    El .zim exige todas las palabras (y OR no es un operador): con "cuál" o una palabra
    que no sale en ningún artículo, una pregunta se quedaría sin nada. Con varias que no
    coinciden en ninguno, se quita la más común, que es la que menos dice.
    """
    from libzim.search import Query, Searcher

    searcher = Searcher(archive)

    def search(text):
        return searcher.search(Query().set_query(text))

    matches = {word: search(word).get_estimated_matches() for word in WORD.findall(question) if tokenize(word)}
    words = [word for word, found in matches.items() if found]

    while words:
        found = search(" ".join(words))

        if found.get_estimated_matches():
            return found

        words.remove(max(words, key=matches.get))

    return None


def found_articles(archive, question: str, count: int = ARTICLES) -> list:
    """[(ruta, título, html)] de los mejores artículos, siguiendo redirecciones."""
    found = search_for(archive, question)
    articles = {}

    for result in found.get_results(0, SEARCH_RESULTS) if found else []:
        entry = archive.get_entry_by_path(result.path)
        entry = entry.get_redirect_entry() if entry.is_redirect else entry

        if entry.path not in articles and len(articles) < count:
            articles[entry.path] = (entry.path, entry.title, bytes(entry.get_item().content).decode("utf-8"))

    return list(articles.values())


def closest_chunks(chunks: list, question: str, count: int = ARTICLE_FRAGMENTS, language: str = SPANISH) -> list:
    """El principio del artículo y los fragmentos que más palabras comparten con la pregunta.

    Embeber todo un artículo largo no cabe en el tiempo de una pregunta.
    """
    wanted = set(tokenize(question, language))
    shared = {id(chunk): len(wanted.intersection(tokenize(chunk.text, language))) for chunk in chunks}
    return chunks[:1] + sorted(chunks[1:], key=lambda chunk: -shared[id(chunk)])[:count - 1]


def coverage_of(question: str, documents: list, language: str = SPANISH) -> list:
    """Qué parte de la pregunta está en cada documento, pesando las palabras raras entre ellos.

    Como WordIndex.coverage, sin tabla: estos fragmentos no están en ningún índice.
    """
    tokens = set(tokenize(question, language))
    words = [set(tokenize(document, language)) for document in documents]
    weights = {token: inverse_frequency(len(words), sum(token in word for word in words)) for token in tokens}
    whole = sum(weights.values())
    return [sum(weights[t] for t in word if t in weights) / whole if whole else 0.0 for word in words]


def distance(one: list, other: list) -> float:
    """La de Chroma por defecto, para que valga el mismo umbral: L2 al cuadrado."""
    return sum((a - b) ** 2 for a, b in zip(one, other))


def origin_of_article(source, path: str, edition: str) -> str:
    parts = ["Wikipedia", source.url.format(path), source.license, f"edición {edition}" if edition else ""]
    return " · ".join(part for part in parts if part)


def article_fragments(archive, source, question: str, language: str = SPANISH) -> list:
    """[(id, documento, metadatos)] de los fragmentos elegidos, listos para ordenar."""
    edition = edition_of(archive)
    fragments = []

    for path, title, html in found_articles(archive, question):
        slug = slug_of(path)
        metadata = {
            "file_path": slug,
            "relative_path": slug,
            "source": source.name,
            "kind": source.kind,
            "origin": origin_of_article(source, path, edition),
        }

        for chunk in closest_chunks(article_chunks(title, html), question, language=language):
            fragments.append((
                f"{slug}::{chunk.start_line}",
                chunk.text,
                {**metadata, "start_line": chunk.start_line, "end_line": chunk.end_line, "label": chunk.label},
            ))

    return fragments


def wikipedia_hits(question: str, source, n_results=5, embedder=None, translated="") -> list:
    """Los mejores fragmentos de los artículos que encuentra question en el .zim de source.

    translated es la pregunta en inglés: en un .zim en inglés los artículos se buscan con
    ella, y los fragmentos se ordenan con las dos, como en las colecciones en inglés.
    """
    from libzim.reader import Archive

    english = translated if source.language == ENGLISH_SOURCE else ""
    searches = [(question, SPANISH)] + ([(english, ENGLISH)] if english else [])
    fragments = article_fragments(Archive(str(Path(source.path))), source, *searches[-1])

    if not fragments:
        return []

    embedder = embedder or OllamaEmbedder()
    documents = [document for _, document, _ in fragments]
    vectors = EmbeddingCache().embed(documents, embedder)
    lists, coverages = [], []

    for text, language in searches:
        query = embedder.embed_query(text)
        found = coverage_of(text, documents, language)
        rows = list(zip(fragments, vectors, found))
        by_distance = sorted(((distance(query, vector), fragment) for fragment, vector, _ in rows), key=lambda row: row[0])
        by_words = sorted(((coverage, fragment) for fragment, _, coverage in rows if coverage), key=lambda row: -row[0])
        lists.append([(key, Hit(document, metadata, distance=near)) for near, (key, document, metadata) in by_distance[:CANDIDATES]])
        lists.append([(key, Hit(document, metadata, keyword_score=score)) for score, (key, document, metadata) in by_words[:CANDIDATES]])
        coverages.append(found)

    hits = merge(*lists, n_results=n_results)
    # La mejor de las dos, como en search_collections.
    covered = dict(zip(documents, (max(values) for values in zip(*coverages))))

    for hit in hits:
        hit.coverage = covered[hit.document]

    return hits
