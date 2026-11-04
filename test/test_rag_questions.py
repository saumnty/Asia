"""Preguntas y respuestas de Stack Exchange en .zim (fase H, capa 4): parser, orden, presentación y búsqueda."""
from datetime import date

import pytest
from libzim.writer import Creator

from core import prompts
from core.rag.library import Library
from core.rag.qa_page import card_date, is_stale, license_for, ordered_answers, page_chunks, parse_page, post_origin
from core.rag.questions import closest_posts, edition_date, qa_hits, site_domain, zim_language
from test_rag_answer import Router
from test_rag_wikipedia import Embedder, Page, Tools, archive_of
from test_confidencial import make_brain
from tools.rag_tool import RagTool


def card(action, when, author=None):
    link = f'<a class="s-user-card--link" href="../../users/1/{author}">{author}</a>' if author else ""
    return (f'<div class="s-user-card"><time class="s-user-card--time" datetime="{action} {when}">{action} {when}</time>'
            f'<div class="s-user-card--info">{link}</div></div>')


def answer(answer_id, score, body, when, author, accepted=False):
    kind = "answer accepted-answer" if accepted else "answer"
    return (f'<div id="answer-{answer_id}" class="{kind}" data-score="{score}"><div class="postcell">'
            f'<div class="s-prose js-post-body">{body}</div><div class="mt24">{card("answered", when, author)}</div>'
            "</div></div>")


ACCEPTED_BODY = "<p>Run this capital command:</p><pre><code>ros2 topic pub /chatter std_msgs/msg/String" + chr(10) + "  data: hello</code></pre>"
QUESTION_HTML = f"""<html><body class="question-page">
<div id="question-header"><h1><a href="../../questions/42/como-publicar" class="question-hyperlink">How to publish a capital topic</a></h1></div>
<time itemprop="dateCreated" datetime="2019-03-01T10:00:00.000">Mar 1 '19</time>
<div id="question" class="question" data-score="7"><div class="postcell">
<div class="s-prose js-post-body"><p>I want to publish a message on a topic. Which capital command works?</p></div>
<div class="mb0">{card("asked", "Mar 1 '19 at 10:00", "ana")}</div></div></div>
<div id="answers">
{answer(50, 30, "<p>Use the old tool.</p>", "Mar 2 '19 at 09:00", "bob")}
{answer(51, 3, ACCEPTED_BODY, "Mar 3 '19 at 09:00", "carla", accepted=True)}
{answer(52, 30, "<p>A newer capital way.</p>", "Jan 5 '24 at 09:00", "dani")}
{answer(53, 1, "<p>Low score.</p>", "Jan 6 '24 at 09:00", "eva")}
</div></body></html>"""

USER_PAGE = "<html><body><p>ana capital topic user page</p></body></html>"


@pytest.fixture
def qa_zim(tmp_path):
    path = tmp_path / "robotics.stackexchange.com_en_all_2026-10.zim"

    with Creator(str(path)).config_indexing(True, "eng") as creator:
        creator.set_mainpath("questions/42/como-publicar")
        creator.add_metadata("Date", "2026-10-20")
        creator.add_metadata("Name", "robotics.stackexchange.com_en_all")
        creator.add_metadata("Language", "eng")
        creator.add_metadata("License", "CC-BY-SA")
        creator.add_item(Page("questions/42/como-publicar", "How to publish a capital topic", QUESTION_HTML))
        creator.add_item(Page("users/1/ana", "ana capital topic", USER_PAGE))
        creator.add_item(Page("questions/tagged/topic", "Questions tagged capital topic", USER_PAGE))

    return path


EDITION = date(2026, 10, 20)


def page():
    return parse_page(QUESTION_HTML, EDITION)


def test_la_pregunta_con_su_autor_votos_y_fecha():
    parsed = page()

    assert (parsed.question_id, parsed.title) == ("42", "How to publish a capital topic")
    assert (parsed.question.score, parsed.question.author, parsed.question.posted) == (7, "ana", date(2019, 3, 1))
    assert parsed.question.lines == ["I want to publish a message on a topic.", "Which capital command works?"]


def test_las_respuestas_con_aceptada_votos_fecha_y_autor():
    answers = {a.post_id: a for a in page().answers}

    assert answers["51"].accepted and not answers["50"].accepted
    assert (answers["50"].score, answers["50"].posted, answers["50"].author) == (30, date(2019, 3, 2), "bob")


def test_el_codigo_va_linea_por_linea():
    accepted = next(a for a in page().answers if a.accepted)

    assert accepted.lines == ["Run this capital command:", "ros2 topic pub /chatter std_msgs/msg/String", "  data: hello"]


def test_orden_aceptada_luego_mas_votada_y_a_igual_voto_la_mas_reciente():
    assert [a.post_id for a in ordered_answers(page().answers)] == ["51", "52", "50"]


def test_licencia_segun_la_fecha():
    assert license_for(date(2010, 1, 1)) == "CC BY-SA 2.5"
    assert license_for(date(2015, 1, 1)) == "CC BY-SA 3.0"
    assert license_for(date(2019, 3, 3)) == "CC BY-SA 4.0"


def test_desactualizada_si_tiene_mas_de_5_anos_frente_a_la_edicion():
    assert is_stale(date(2019, 3, 3), EDITION)
    assert not is_stale(date(2024, 1, 5), EDITION)
    assert not is_stale(None, EDITION)


@pytest.mark.parametrize(
    "text, expected",
    [("answered Oct 21 '25 at 06:37", date(2025, 10, 21)), ("asked Jul 13 '23 at 12:34", date(2023, 7, 13)),
     ("answered Jan 5 at 09:00", date(2026, 1, 5)), ("nada", None)],
)
def test_fecha_de_la_tarjeta(text, expected):
    assert card_date(text, EDITION) == expected


def test_lo_que_se_muestra_de_cada_respuesta():
    parsed = page()
    accepted = next(a for a in parsed.answers if a.accepted)

    origin = post_origin(parsed, accepted, "robotics.stackexchange.com", EDITION)

    assert origin == (
        "«How to publish a capital topic» · https://robotics.stackexchange.com/a/51 · respuesta aceptada de carla, "
        "3 votos · 2019-03-03 (puede estar desactualizada) · CC BY-SA 4.0"
    )
    assert post_origin(parsed, parsed.question, "robotics.stackexchange.com", EDITION).startswith(
        "«How to publish a capital topic» · https://robotics.stackexchange.com/q/42 · pregunta de ana · 2019-03-01 ·"
    )


def test_fragmentos_de_la_pregunta_y_de_tres_respuestas_con_las_lineas_de_toda_la_pagina():
    chunks = page_chunks(page())

    assert [post.post_id for post, _ in chunks] == ["42", "51", "52", "50"]
    assert chunks[0][1].start_line == 1 and chunks[1][1].start_line == 3
    assert chunks[1][1].label == "How to publish a capital topic > Respuesta aceptada"


def test_siempre_entran_la_pregunta_y_la_mejor_respuesta():
    chunks = page_chunks(page())

    chosen = closest_posts(chunks, "newer way", count=2)

    assert [post.post_id for post, _ in chosen] == ["42", "51"]


def test_metadatos_del_zim(qa_zim):
    archive = archive_of(qa_zim)

    assert site_domain(archive) == "robotics.stackexchange.com"
    assert edition_date(archive) == EDITION
    assert zim_language(archive) == "en"


def source_of(path):
    from core.rag.library import Source

    return Source("robotics", "preguntas", str(path), "robotics", named_only=True, publica=True, language="en")


def test_busca_solo_paginas_de_pregunta(qa_zim):
    hits = qa_hits("capital topic", source_of(qa_zim), embedder=Embedder())

    assert hits and all(hit.metadata["relative_path"] == "robotics_42.qa" for hit in hits)
    assert all("users" not in hit.metadata["origin"] for hit in hits)


@pytest.fixture
def registered(qa_zim, monkeypatch):
    answer_text = RagTool().index_project("robotics", str(qa_zim), "preguntas")
    assert "lista" in answer_text and "páginas" in answer_text
    monkeypatch.setattr("core.rag.wikipedia.OllamaEmbedder", Embedder)
    return qa_zim


def test_indexar_registra_el_sitio(registered):
    source = Library().get("robotics")

    assert (source.kind, source.named_only, source.publica, source.language) == ("preguntas", True, True, "en")
    assert "CC BY-SA" in source.license


def test_buscar_en_el_sitio_muestra_autor_votos_fecha_enlace_y_licencia(registered):
    brain = make_brain()
    brain.tool_registry = Tools()
    brain.provider_router = Router(
        "[robotics_42.qa:3-5] ros2 topic pub /chatter std_msgs/msg/String", "Usa ros2 topic pub [robotics_42.qa:4]."
    )

    shown = brain.process("/buscar which capital command publishes a topic en robotics")

    assert prompts.FROM_QA in shown
    assert "https://robotics.stackexchange.com/a/51 · respuesta aceptada de carla, 3 votos · 2019-03-03" in shown
    assert "(puede estar desactualizada) · CC BY-SA 4.0" in shown
    assert "ros2 topic pub /chatter std_msgs/msg/String" in shown


def test_sin_archivo_lo_dice(registered):
    registered.unlink()

    assert RagTool().search_project("algo en robotics", "asia") == prompts.QA_MISSING


def test_fuentes_lo_cuenta_en_paginas(registered):
    assert "páginas" in make_brain().process("/fuentes")
