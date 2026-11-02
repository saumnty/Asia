"""Artículos de Wikipedia a fragmentos, con la estructura real de mwoffliner."""
from core.rag.article import SEPARATOR, article_chunks
from core.rag.chunking import MAX_CHARS

REFERENCE = (
    '<sup class="mw-ref reference" id="cite_ref-5"><a href="#cite_note-5"><span class="mw-reflink-text">'
    '<span class="cite-bracket">[</span>5<span class="cite-bracket">]</span></span></a></sup>'
)
MATH = (
    '<span class="mwe-math-element"><span class="mwe-math-mathml-a11y" style="display: none;">'
    '<math alttext="{\\displaystyle a^{2}+b^{2}=c^{2}}"><semantics><mi>a</mi>'
    '<annotation encoding="application/x-tex">{\\displaystyle a^{2}}</annotation></semantics></math></span>'
    '<img alt="x"></span>'
)
ARTICLE = f"""
<html><head><title>Camberra</title><script>RLCONF = {{"x": 1}}</script></head><body>
<header><h1 id="firstHeading">Camberra</h1></header>
<div class="mw-content-ltr mw-parser-output">
<section data-mw-section-id="0" id="mwAQ">
<span class="mw-empty-elt"><style>.infobox {{ color: red }}</style></span>
<table class="infobox geography vcard"><tbody>
<tr><th colspan="3">Camberra<br/><span>Canberra</span></th></tr>
<tr><th>País</th><td>Australia</td></tr>
</tbody></table>
<p><b>Camberra</b>{REFERENCE} es la capital de Australia. Tiene unos&nbsp;450 000 habitantes.</p>
<figure><figcaption>Una foto del lago.</figcaption></figure>
</section>
<section data-mw-section-id="1" aria-labelledby="Historia">
<div class="mw-heading mw-heading2"><h2 id="Historia">Historia</h2></div>
<p>Se fundó en 1913.</p>
<ul><li>Primera entrada<ul><li>Anidada</li></ul></li></ul>
<section data-mw-section-id="2" aria-labelledby="Siglo_XX">
<div class="mw-heading mw-heading3"><h3 id="Siglo_XX">Siglo&nbsp;XX</h3></div>
<p>Creció después de la guerra. {MATH}</p>
<table class="wikitable"><tr><th>Año</th><th>Censo</th><th>Nota</th></tr></table>
</section>
</section>
<section data-mw-section-id="3" aria-labelledby="Referencias">
<div class="mw-heading mw-heading2"><h2 id="Referencias">Referencias</h2></div>
<ol class="references"><li>Una cita de un libro.</li></ol>
<section data-mw-section-id="4"><div class="mw-heading mw-heading3"><h3>Libros</h3></div><p>Otro libro.</p></section>
</section>
<table class="hlist navbox-inner navbox"><tr><td>Plantilla de navegación</td></tr></table>
</div></body></html>
"""


def lines_of(chunk):
    return chunk.text.splitlines()[1:]


def by_label(html=ARTICLE):
    return {chunk.label: chunk for chunk in article_chunks("Camberra", html)}


def test_una_seccion_por_fragmento_con_su_ruta():
    assert list(by_label()) == ["Camberra", "Camberra > Historia", "Camberra > Historia > Siglo XX"]


def test_el_texto_empieza_por_donde_vive():
    assert by_label()["Camberra > Historia"].text.splitlines()[0] == "Camberra > Historia"


def test_cada_frase_es_una_linea():
    assert "Tiene unos 450 000 habitantes." in lines_of(by_label()["Camberra"])
    assert "Camberra es la capital de Australia." in lines_of(by_label()["Camberra"])


def test_los_numeros_de_linea_siguen_por_todo_el_articulo():
    chunks = article_chunks("Camberra", ARTICLE)

    assert chunks[0].start_line == 1
    assert [chunk.start_line for chunk in chunks[1:]] == [chunks[0].end_line + 1, chunks[1].end_line + 1]
    assert all(chunk.end_line - chunk.start_line + 1 == len(lines_of(chunk)) for chunk in chunks)


def test_quita_referencias_estilos_figuras_y_navegacion():
    text = "\n".join(chunk.text for chunk in article_chunks("Camberra", ARTICLE))

    for noise in ("[5]", ".infobox", "Una foto", "Plantilla de navegación", "RLCONF"):
        assert noise not in text


def test_el_infobox_queda_como_clave_y_valor():
    lines = lines_of(by_label()["Camberra"])

    assert "País: Australia" in lines
    assert "Camberra Canberra" in lines


def test_una_fila_no_se_parte_por_los_puntos():
    html = '<section data-mw-section-id="0"><table><tr><th>Altitud</th><td>564 m s. n. m.</td></tr></table></section>'

    assert lines_of(article_chunks("Camberra", html)[0]) == ["Altitud: 564 m s. n. m."]


def test_una_tabla_con_mas_columnas_las_separa():
    assert "Año | Censo | Nota" in lines_of(by_label()["Camberra > Historia > Siglo XX"])


def test_una_lista_anidada_no_se_repite():
    lines = lines_of(by_label()["Camberra > Historia"])

    assert lines.count("Primera entradaAnidada") == 1 and "Anidada" not in lines


def test_las_frases_de_una_subseccion_no_estan_en_la_de_arriba():
    assert "Creció después de la guerra." not in lines_of(by_label()["Camberra > Historia"])


def test_una_formula_queda_como_tex():
    assert "a^{2}+b^{2}=c^{2}" in by_label()["Camberra > Historia > Siglo XX"].text


def test_salta_referencias_y_sus_subsecciones():
    text = "\n".join(chunk.text for chunk in article_chunks("Camberra", ARTICLE))

    assert "Una cita" not in text and "Otro libro" not in text


def test_una_seccion_larga_se_parte_sin_pasar_del_limite():
    sentences = " ".join(f"Frase numero {i} con algo de relleno para ocupar sitio." for i in range(200))
    html = f'<section data-mw-section-id="0"><p>{sentences}</p></section>'

    chunks = article_chunks("Largo", html)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= MAX_CHARS for chunk in chunks)
    assert chunks[1].start_line == chunks[0].end_line + 1
    assert all(chunk.text.startswith("Largo\n") for chunk in chunks)


def test_una_frase_mas_larga_que_el_limite_se_corta():
    html = f'<section data-mw-section-id="0"><p>{"palabra " * 400}</p></section>'

    assert all(len(chunk.text) <= MAX_CHARS for chunk in article_chunks("Largo", html))


def test_sin_secciones_no_hay_fragmentos():
    assert article_chunks("Vacío", "<html><body><p>Fuera de una sección.</p></body></html>") == []


def test_el_separador_es_el_de_las_secciones_de_un_documento():
    assert SEPARATOR == " > "
