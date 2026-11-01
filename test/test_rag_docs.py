"""Documentación como fuente: secciones de .rst y páginas públicas en las citas."""
from core import prompts
from core.rag.chunking import chunk_text
from core.rag.indexer import ProjectIndexer
from core.rag.library import Library, origin_of
from core.rag.quotes import best_fragments, verified_lines, verify_quotes
from test_confidencial import make_brain
from test_rag_index import embeddings  # noqa: F401
from tools.rag_tool import RagTool

RST = """.. redirect-from::

    Tutorials/Viejo

Topics
======

Introducción al tema.

Publicar un mensaje
-------------------

Corre esto:

.. code-block:: console

  ros2 topic pub /cmd_vel geometry_msgs/msg/Twist
  --------------------------------------

Detalles
^^^^^^^^

Más texto.

Escuchar
--------

Otro texto.
"""

ROS2_URL = "https://docs.ros.org/en/jazzy/{}.html"
PAGE = "https://docs.ros.org/en/jazzy/Tutorials/Topics.html"
CONTEXT = f"""
--- [Tutorials/Topics.rst:10-20] Topics > Publicar ---
Fuente: ros2 (documentacion)
Página: {PAGE} · CC BY 4.0
Contenido:
Tutorials/Topics.rst · Topics > Publicar
Publicar un mensaje
Corre ros2 topic pub con un Twist.
"""


def labels(text):
    return [chunk.label for chunk in chunk_text(text, ".rst")]


def test_rst_por_secciones_con_su_ruta():
    assert labels(RST) == [
        "",
        "Topics",
        "Topics > Publicar un mensaje",
        "Topics > Publicar un mensaje > Detalles",
        "Topics > Escuchar",
    ]


def test_la_seccion_empieza_en_su_titulo():
    chunk = chunk_text(RST, ".rst")[2]

    assert chunk.text.startswith("Publicar un mensaje\n----") and chunk.start_line == 10


def test_una_linea_de_guiones_en_un_bloque_indentado_no_es_un_titulo():
    assert "ros2 topic pub" in chunk_text(RST, ".rst")[2].text


def test_el_nivel_lo_da_el_orden_de_aparicion():
    text = "Uno\n----\n\nDos\n====\n\nTres\n----\n"

    assert labels(text) == ["Uno", "Uno > Dos", "Tres"]


def test_titulo_con_linea_arriba():
    text = "======\nTitulo\n======\n\nTexto.\n\nOtro\n----\n\nMas.\n"

    assert labels(text) == ["Titulo", "Titulo > Otro"]
    assert chunk_text(text, ".rst")[0].start_line == 1


def test_un_subrayado_corto_no_es_un_titulo():
    assert labels("Un titulo largo\n---\n\nTexto.\n") == [""]


def test_rst_sin_secciones_va_por_bloques():
    assert labels("Solo texto.\n\nMas texto.\n") == [""]


def test_la_pagina_de_un_archivo():
    assert origin_of("Tutorials/Topics.rst", ROS2_URL, "CC BY 4.0") == f"{PAGE} · CC BY 4.0"
    assert origin_of("a.rst", "https://x.org/{}/", "") == "https://x.org/a/"
    assert origin_of("a.py", "", "") == ""


def test_el_fragmento_guarda_su_pagina(tmp_path, embeddings):  # noqa: F811
    docs = tmp_path / "docs" / "Tutorials"
    docs.mkdir(parents=True)
    (docs / "Topics.rst").write_text(RST, encoding="utf-8")

    indexer = ProjectIndexer(str(tmp_path / "docs"), "ros2", persist_dir=tmp_path / "i", url=ROS2_URL, license="CC BY 4.0")
    indexer.index_project()

    [metadata, *_] = indexer.store.all_documents()["metadatas"]
    assert metadata["origin"] == f"{PAGE} · CC BY 4.0"


def test_un_proyecto_no_tiene_pagina(tmp_path, embeddings):  # noqa: F811
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

    indexer = ProjectIndexer(str(tmp_path), "bolita", persist_dir=tmp_path / "i")
    indexer.index_project()

    assert indexer.store.all_documents()["metadatas"][0]["origin"] == ""


def test_las_lineas_verificadas_muestran_la_pagina():
    quotes = verify_quotes("[Tutorials/Topics.rst:10-20] Publicar un mensaje", CONTEXT)

    shown = verified_lines(quotes)

    assert f"{PAGE} · CC BY 4.0 (Topics > Publicar)\n  Publicar un mensaje" in shown
    assert "Topics.rst" not in shown


def test_el_verificador_sigue_usando_la_etiqueta():
    [quote] = verify_quotes("[Tutorials/Topics.rst:10-20] Corre ros2 topic pub con un Twist.", CONTEXT)

    assert quote.cite == "Tutorials/Topics.rst:11"


def test_los_fragmentos_de_respaldo_muestran_la_pagina():
    shown = best_fragments(CONTEXT)

    assert f"[{PAGE} · CC BY 4.0] Topics > Publicar" in shown


def test_el_codigo_sin_pagina_sigue_con_archivo_y_lineas():
    context = "\n--- [a.py:1-3] ---\nFuente: x (proyecto)\nContenido:\na.py\nself.kp = 2.5\n"

    assert "a.py:1\n  self.kp = 2.5" in verified_lines(verify_quotes("[a.py:1-3] self.kp = 2.5", context))


def test_indexar_guarda_la_url_y_la_licencia(tmp_path, embeddings, monkeypatch):  # noqa: F811
    monkeypatch.setattr("tools.rag_tool.unload_chat_models", lambda: None)
    monkeypatch.setattr(
        "tools.rag_tool.ProjectIndexer",
        lambda **kwargs: ProjectIndexer(persist_dir=tmp_path / "i", **kwargs),
    )
    (tmp_path / "a.rst").write_text("Titulo\n======\n\nTexto.\n", encoding="utf-8")

    RagTool().index_project("ros2", str(tmp_path), "documentacion", ROS2_URL, "CC BY 4.0")
    RagTool().index_project("ros2", str(tmp_path), "documentacion")

    source = Library().get("ros2")
    assert (source.url, source.license) == (ROS2_URL, "CC BY 4.0")


def test_una_fuente_vieja_sin_url_se_sigue_leyendo():
    library = Library()
    library.path.parent.mkdir(parents=True)
    library.path.write_text(
        '[{"name": "a", "kind": "proyecto", "path": "C:/a", "collection": "aaa", "fragments": 1, "indexed": "x"}]',
        encoding="utf-8",
    )

    assert library.get("a").url == ""


def test_fuentes_muestra_la_url():
    Library().save("ros2", "documentacion", "C:/docs", 10, ROS2_URL, "CC BY 4.0")

    assert ROS2_URL in make_brain().process("/fuentes")


def test_el_tipo_documentacion_existe():
    assert "documentacion" in make_brain().process("/indexar")


def test_el_prompt_de_extraccion_no_cambia_con_la_pagina():
    assert PAGE in prompts.extract_quotes("x", CONTEXT)
