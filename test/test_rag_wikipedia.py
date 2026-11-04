"""Wikipedia offline: búsqueda en un .zim real, creado en una carpeta temporal."""
import pytest
from libzim.writer import Creator, Hint, Item, StringProvider

from config.settings_manager import SettingsManager
from core import prompts
from core.prompts import NOT_FOUND, NOT_FOUND_IN_WIKIPEDIA, WIKIPEDIA_MISSING
from core.provenance import PUBLICA
from core.rag.article import article_chunks
from core.rag.chunking import Chunk
from core.rag.embedding_cache import EmbeddingCache
from core.rag.library import Library, Source
from core.rag.quotes import CITED_LINES, Quote, verified_lines
from core.rag.retriever import relevant
from core.rag.wikipedia import (
    ARTICLE_FRAGMENTS,
    closest_chunks,
    coverage_of,
    distance,
    edition_of,
    found_articles,
    slug_of,
    wikipedia_hits,
    zim_summary,
)
from test_confidencial import make_brain
from test_rag_answer import Router
from tools.rag_tool import RagTool

CANBERRA = """<html><head><title>Camberra</title></head><body>
<section data-mw-section-id="0"><p>Camberra es la capital de Australia. Tiene un lago artificial.</p></section>
<section data-mw-section-id="1"><div class="mw-heading mw-heading2"><h2>Historia</h2></div>
<p>La capital de Australia se fundó en 1913.</p></section>
</body></html>"""
OTHER = """<html><head><title>Fotosíntesis</title></head><body>
<section data-mw-section-id="0"><p>La fotosíntesis convierte la luz en energía química.</p></section>
</body></html>"""


class Page(Item):
    def __init__(self, path, title, html):
        super().__init__()
        self.path, self.title, self.html = path, title, html

    def get_path(self):
        return self.path

    def get_title(self):
        return self.title

    def get_mimetype(self):
        return "text/html"

    def get_contentprovider(self):
        return StringProvider(self.html)

    def get_hints(self):
        return {Hint.FRONT_ARTICLE: True}


@pytest.fixture
def zim(tmp_path):
    path = tmp_path / "wiki.zim"

    with Creator(str(path)).config_indexing(True, "spa") as creator:
        creator.set_mainpath("Camberra")
        creator.add_metadata("Date", "2026-10-10")
        creator.add_item(Page("Camberra", "Camberra", CANBERRA))
        creator.add_item(Page("Fotosíntesis", "Fotosíntesis", OTHER))
        creator.add_redirection("Canberra", "Canberra", "Camberra", {Hint.FRONT_ARTICLE: True})

    return path


KANGAROO = """<html><head><title>Kangaroo</title></head><body>
<section data-mw-section-id="0"><p>The kangaroo lives in Australia. It carries its young in a pouch.</p></section>
</body></html>"""


@pytest.fixture
def english_zim(tmp_path):
    path = tmp_path / "wiki_en.zim"

    with Creator(str(path)).config_indexing(True, "eng") as creator:
        creator.set_mainpath("Kangaroo")
        creator.add_item(Page("Kangaroo", "Kangaroo", KANGAROO))

    return path


def archive_of(path):
    from libzim.reader import Archive

    return Archive(str(path))


def wiki(path):
    return Source(
        "wikipedia", "enciclopedia", str(path), "wikipedia", url="https://es.wikipedia.org/wiki/{}",
        license="CC BY-SA 4.0", named_only=True, publica=True,
    )


class Embedder:
    """Cuenta lo que se le pide. El vector dice cuánto habla el texto de la capital."""
    model = "falso"

    def __init__(self):
        self.embedded = []

    def vector(self, text):
        return [float(text.lower().count("capital")), float(len(text) % 7)]

    def embed_documents(self, texts):
        self.embedded += texts
        return [self.vector(text) for text in texts]

    def embed_query(self, text):
        return self.vector(text)


def test_resume_el_archivo(zim):
    summary = zim_summary(zim)

    assert summary == {"articles": summary["articles"], "searchable": True} and summary["articles"] >= 2


def test_la_edicion_sale_del_metadato(zim):
    assert edition_of(archive_of(zim)) == "2026-10"


def test_una_pregunta_natural_encuentra_el_articulo(zim):
    found = found_articles(archive_of(zim), "cuál es la capital de Australia")

    assert [title for _, title, _ in found] == ["Camberra"]
    assert "<section" in found[0][2]


def test_una_palabra_que_no_sale_en_ningun_articulo_no_deja_sin_nada(zim):
    found = found_articles(archive_of(zim), "capital zzzyyyxxx Australia")

    assert [title for _, title, _ in found] == ["Camberra"]


def test_palabras_que_no_coinciden_en_ningun_articulo_dejan_la_menos_comun(zim):
    found = found_articles(archive_of(zim), "fotosíntesis capital lago Australia")

    assert [title for _, title, _ in found] == ["Camberra"]


def test_sin_resultados_no_hay_articulos(zim):
    assert found_articles(archive_of(zim), "zzzyyyxxx") == []


@pytest.mark.parametrize("question", ["", "   ", "(", '"', "*", "¡!"])
def test_una_pregunta_rara_no_truena(zim, question):
    assert found_articles(archive_of(zim), question) == []


class Result:
    def __init__(self, path):
        self.path = path


class Results:
    def get_results(self, start, count):
        return [Result("Canberra"), Result("Camberra"), Result("Fotosíntesis")]


def test_una_redireccion_no_repite_el_articulo(zim, monkeypatch):
    monkeypatch.setattr("core.rag.wikipedia.search_for", lambda archive, question: Results())

    assert [path for path, _, _ in found_articles(archive_of(zim), "x")] == ["Camberra", "Fotosíntesis"]


def test_el_tope_de_articulos(zim, monkeypatch):
    monkeypatch.setattr("core.rag.wikipedia.search_for", lambda archive, question: Results())

    assert len(found_articles(archive_of(zim), "x", count=1)) == 1


@pytest.mark.parametrize(
    "path, slug",
    [
        ("Camberra", "Camberra.wiki"),
        ("Mercurio_(planeta)", "Mercurio_planeta.wiki"),
        ("Teorema_de_Pitágoras", "Teorema_de_Pitágoras.wiki"),
        ("Node.js", "Node.js.wiki"),
        ("C++", "C.wiki"),
        ("+", "articulo.wiki"),
    ],
)
def test_la_etiqueta_la_reconoce_la_verificacion(path, slug):
    assert slug_of(path) == slug
    assert CITED_LINES.search(f"[{slug}:12]")


def chunk(text, line=1):
    return Chunk(text, line, line, "")


def test_se_quedan_el_principio_y_lo_que_comparte_palabras():
    chunks = [chunk("Introducción sin nada"), chunk("Tema ajeno"), chunk("capital de Australia"), chunk("Otro ajeno")]

    assert closest_chunks(chunks, "capital de Australia", count=2) == [chunks[0], chunks[2]]


def test_un_articulo_largo_no_pasa_del_tope():
    html = '<section data-mw-section-id="0"><p>' + "</p><p>".join(["Una frase. " * 300] * 30) + "</p></section>"

    assert len(closest_chunks(article_chunks("Largo", html), "frase")) == ARTICLE_FRAGMENTS


def test_la_cobertura_pesa_las_palabras_raras():
    documents = ["la capital de Australia", "la capital de Francia", "la capital de Italia"]

    rare, common, _ = coverage_of("capital de Australia", documents)

    assert rare == 1.0 and 0 < common < 0.5


def test_la_cobertura_sin_palabras_es_cero():
    assert coverage_of("de la", ["algo"]) == [0.0]


def test_la_distancia_es_l2_al_cuadrado():
    assert distance([0.0, 0.0], [3.0, 4.0]) == 25.0


def test_los_hits_son_como_los_de_una_coleccion(zim):
    hits = wikipedia_hits("capital de Australia", wiki(zim), embedder=Embedder())

    by_label = {hit.metadata["label"]: hit.metadata for hit in hits}

    assert set(by_label) == {"Camberra", "Camberra > Historia"}
    assert by_label["Camberra"]["start_line"] == 1 and by_label["Camberra > Historia"]["start_line"] == 3
    assert by_label["Camberra"]["relative_path"] == "Camberra.wiki"
    assert by_label["Camberra"]["origin"] == "Wikipedia · https://es.wikipedia.org/wiki/Camberra · CC BY-SA 4.0 · edición 2026-10"
    assert by_label["Camberra"]["source"] == "wikipedia" and by_label["Camberra"]["kind"] == "enciclopedia"


def test_el_filtro_de_siempre_funciona_con_estos_hits(zim):
    hits = wikipedia_hits("capital de Australia", wiki(zim), embedder=Embedder())

    assert all(hit.distance is not None for hit in hits)
    assert relevant(hits, 0.3, None)


def test_sin_articulos_ni_se_embebe(zim):
    embedder = Embedder()

    assert wikipedia_hits("zzzyyyxxx", wiki(zim), embedder=embedder) == []
    assert embedder.embedded == []


def test_la_segunda_vez_no_vuelve_a_embeber(zim):
    embedder = Embedder()

    first = wikipedia_hits("capital de Australia", wiki(zim), embedder=embedder)
    embedded = len(embedder.embedded)
    second = wikipedia_hits("capital de Australia", wiki(zim), embedder=embedder)

    assert embedded and len(embedder.embedded) == embedded
    assert [hit.document for hit in first] == [hit.document for hit in second]


def test_la_cache_guarda_y_devuelve_los_vectores(tmp_path):
    cache, embedder = EmbeddingCache(tmp_path / "c.sqlite3"), Embedder()

    stored = cache.embed(["capital uno", "dos"], embedder)
    again = cache.embed(["dos", "capital uno"], embedder)

    assert again == stored[::-1]
    assert embedder.embedded == ["capital uno", "dos"]


def test_la_cache_separa_los_modelos(tmp_path):
    cache, one, other = EmbeddingCache(tmp_path / "c.sqlite3"), Embedder(), Embedder()
    other.model = "otro"

    cache.embed(["texto"], one)
    cache.embed(["texto"], other)

    assert other.embedded == ["texto"]


def test_un_texto_repetido_se_embebe_una_vez(tmp_path):
    embedder = Embedder()

    vectors = EmbeddingCache(tmp_path / "c.sqlite3").embed(["igual", "igual"], embedder)

    assert embedder.embedded == ["igual"] and vectors[0] == vectors[1]


def test_la_cache_tiene_tope_y_sale_lo_mas_viejo(tmp_path, monkeypatch):
    cache, embedder = EmbeddingCache(tmp_path / "c.sqlite3", limit=2), Embedder()
    clock = iter(range(100))
    monkeypatch.setattr("core.rag.embedding_cache.time.time", lambda: next(clock))

    for text in ("uno", "dos", "tres"):
        cache.embed([text], embedder)

    cache.embed(["uno"], embedder)

    assert cache.count() == 2
    assert embedder.embedded == ["uno", "dos", "tres", "uno"]


class Tools:
    """El registro, con la herramienta real."""
    def execute(self, action, **kwargs):
        tool = RagTool()
        return tool.index_project(**kwargs) if action == "index_project_rag" else tool.search_project(**kwargs)


def brain_with(*answers):
    brain = make_brain()
    brain.tool_registry = Tools()
    brain.provider_router = Router(*answers)
    return brain


@pytest.fixture
def registered(zim, monkeypatch):
    """Wikipedia en la biblioteca, sin Ollama: el embedder de las pruebas.

    Sin palabras clave de qwen3: las prueba test_zim_keywords.py; aquí cada respuesta
    del modelo simulado es la extracción o la respuesta.
    """
    SettingsManager.set_overrides({"rag": {**SettingsManager().get("rag"), "zim_keywords": False}})
    assert "lista" in RagTool().index_project("wikipedia", str(zim), "enciclopedia")
    monkeypatch.setattr("core.rag.wikipedia.OllamaEmbedder", Embedder)
    return zim


def wikipedia_quote():
    return "[Camberra.wiki:1] Camberra es la capital de Australia."


def test_indexar_solo_registra_el_archivo(registered, monkeypatch):
    source = Library().get("wikipedia")

    assert (source.kind, source.named_only, source.publica) == ("enciclopedia", True, True)
    assert source.url == "https://es.wikipedia.org/wiki/{}" and source.license == "CC BY-SA 4.0"
    assert source.path == registered.as_posix() and source.fragments >= 2


def test_el_comando_registra_la_ruta_y_el_tipo(zim):
    answer = brain_with().process(f"/indexar wikipedia {zim} enciclopedia")

    assert "lista" in answer and Library().get("wikipedia").kind == "enciclopedia"


def test_fuentes_la_muestra_en_articulos(registered):
    assert "artículos" in make_brain().process("/fuentes")


def test_reindexar_conserva_lo_que_dijo_publica(registered):
    Library().set_public("wikipedia", False)

    RagTool().index_project("wikipedia")

    assert Library().get("wikipedia").publica is False


def english_wiki(path):
    return Source("wiki-en", "enciclopedia", str(path), "wiki-en", named_only=True, language="en", publica=True)


def test_en_ingles_busca_con_la_pregunta_traducida(english_zim):
    hits = wikipedia_hits(
        "dónde vive el canguro", english_wiki(english_zim), embedder=Embedder(), translated="where does the kangaroo live"
    )

    assert [hit.metadata["label"] for hit in hits] == ["Kangaroo"]
    assert hits[0].coverage > 0


def test_en_ingles_sin_traduccion_no_lo_encuentra(english_zim):
    assert wikipedia_hits("dónde vive el canguro", english_wiki(english_zim), embedder=Embedder()) == []


def test_en_espanol_no_usa_la_traduccion(zim):
    hits = wikipedia_hits("capital de Australia", wiki(zim), embedder=Embedder(), translated="zzzyyyxxx")

    assert {hit.metadata["label"] for hit in hits} == {"Camberra", "Camberra > Historia"}


def test_buscar_en_una_wikipedia_en_ingles_traduce(english_zim, monkeypatch):
    monkeypatch.setattr("core.rag.wikipedia.OllamaEmbedder", Embedder)
    RagTool().index_project("wiki-en", str(english_zim), "enciclopedia", language="en")
    brain = brain_with(
        "where does the kangaroo live",
        "[Kangaroo.wiki:1] The kangaroo lives in Australia.",
        "El canguro vive en Australia [Kangaroo.wiki:1].",
    )

    shown = brain.process("/buscar dónde vive el canguro en wiki-en")

    assert "The kangaroo lives in Australia." in shown and "en.wikipedia.org/wiki/Kangaroo" in shown


def test_otro_idioma_apunta_a_su_wikipedia(zim):
    RagTool().index_project("wiki-en", str(zim), "enciclopedia", language="en")

    assert Library().get("wiki-en").url == "https://en.wikipedia.org/wiki/{}"


@pytest.mark.parametrize("path", ["no_existe.zim", "C:/Asia/README.md"])
def test_no_registra_lo_que_no_es_un_zim(path):
    assert "No encuentro" in RagTool().index_project("wikipedia", path, "enciclopedia")
    assert Library().get("wikipedia") is None


def test_no_registra_un_zim_sin_indice(tmp_path, zim, monkeypatch):
    monkeypatch.setattr("tools.rag_tool.zim_summary", lambda path: {"articles": 3, "searchable": False})

    assert "índice" in RagTool().index_project("wikipedia", str(zim), "enciclopedia")


def test_una_busqueda_general_no_entra_en_wikipedia(registered, monkeypatch):
    seen = {}

    def search(query, collections, **kwargs):
        seen["collections"] = collections
        return []

    monkeypatch.setattr("tools.rag_tool.search_collections", search)

    assert RagTool().search_project("capital de Australia", "asia") == NOT_FOUND
    assert "wikipedia" not in seen["collections"]


def test_el_contexto_lleva_la_etiqueta_y_el_origen(registered):
    context = RagTool().search_project("capital de Australia en wikipedia", "asia")

    assert "--- [Camberra.wiki:" in context and "es.wikipedia.org/wiki/Camberra" in context


def test_la_busqueda_en_wikipedia_es_publica(registered):
    assert RagTool().search_project("capital de Australia en wikipedia", "asia").label == PUBLICA


def test_marcada_privada_no_es_exportable(registered):
    Library().set_public("wikipedia", False)

    assert RagTool().search_project("capital de Australia en wikipedia", "asia").label != PUBLICA


def test_sin_articulos_dice_wikipedia_y_no_proyectos(registered):
    assert RagTool().search_project("zzzyyyxxx en wikipedia", "asia") == NOT_FOUND_IN_WIKIPEDIA


def test_sin_el_archivo_lo_dice(registered):
    source = Library().get("wikipedia")
    source.path = "C:/no/existe.zim"
    Library().write([source])

    assert RagTool().search_project("capital de Australia en wikipedia", "asia") == WIKIPEDIA_MISSING


def test_sin_articulos_ni_se_llama_al_modelo(registered):
    brain = brain_with()

    assert brain.process("/buscar zzzyyyxxx en wikipedia") == NOT_FOUND_IN_WIKIPEDIA
    assert brain.provider_router.prompts == []


def test_sin_el_archivo_ni_se_llama_al_modelo(registered):
    source = Library().get("wikipedia")
    source.path = "C:/no/existe.zim"
    Library().write([source])
    brain = brain_with()

    assert brain.process("/buscar capital de Australia en wikipedia") == WIKIPEDIA_MISSING
    assert brain.provider_router.prompts == []


def test_de_punta_a_punta_con_cita_de_articulo(registered):
    brain = brain_with(wikipedia_quote(), "Camberra es la capital de Australia [Camberra.wiki:1].")

    shown = brain.process("/buscar capital de Australia en wikipedia")

    assert prompts.FROM_WIKIPEDIA in shown
    assert "Wikipedia · https://es.wikipedia.org/wiki/Camberra · CC BY-SA 4.0 · edición 2026-10" in shown
    assert "Camberra es la capital de Australia." in shown
    assert prompts.UNCITED not in shown.partition(prompts.UNVERIFIED_SUMMARY)[2]


def test_una_cita_inventada_no_pasa(registered):
    brain = brain_with("[Camberra.wiki:1] Sídney es la capital de Australia.", "no se usa")

    shown = brain.process("/buscar capital de Australia en wikipedia")

    assert shown.startswith(prompts.NO_DIRECT_ANSWER)
    assert prompts.FROM_WIKIPEDIA in shown and "Sídney" not in shown


def test_lo_de_tus_proyectos_no_lleva_el_aviso_de_wikipedia():
    quote = Quote("core/brain.py", 4, "", "x = 1")

    assert prompts.FROM_WIKIPEDIA not in verified_lines([quote])


def test_el_prompt_no_dice_que_wikipedia_son_sus_proyectos():
    assert "proyectos" not in prompts.answer_from_quotes("q", "[a.wiki:1] línea")
