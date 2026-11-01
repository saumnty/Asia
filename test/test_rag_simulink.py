"""Modelos de Simulink: el código de sus bloques entra al índice; el resto del binario, no."""
import zipfile

import pytest

from core.rag import simulink
from core.rag.chunking import chunk_text
from core.rag.exclusions import SourceFilter
from core.rag.indexer import ProjectIndexer
from core.rag.quotes import Quote, verified_lines
from core.rag.simulink import blocks_of, model_text
from test_rag_index import embeddings  # noqa: F401

SCRIPT = """function [v, w] = fcn(t_clock, x_r)
    coder.extrinsic(&apos;get_tramo&apos;);
    v = 0.5 &lt; x_r;

    w = t_clock * 2;
end
"""
# Como simulink/stateflow/chart_20.xml de un modelo real.
CHART = f"""<?xml version="1.0" encoding="utf-8"?>
<chart id="20">
  <P Name="name">Controlador</P>
  <P Name="type">EML_CHART</P>
  <eml>
    <P Name="name">fcn</P>
  </eml>
  <Children>
    <state SSID="1">
      <P Name="labelString">eML_blk_kernel()</P>
      <eml>
        <P Name="isEML">1</P>
        <P Name="script">{SCRIPT}</P>
      </eml>
    </state>
    <transition SSID="2">
      <P Name="labelString">{{eML_blk_kernel();}}</P>
    </transition>
  </Children>
</chart>
"""
MACHINE = '<?xml version="1.0" encoding="utf-8"?>\n<machine id="19"><P Name="created">x</P></machine>\n'


def write_model(path, charts=None, extra=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as model:
        model.writestr("simulink/stateflow/machine.xml", MACHINE)
        model.writestr("simulink/systems/system_root.xml", "<System><P Name='secreto'>no entra</P></System>")
        model.writestr("metadata/thumbnail.png", b"\x89PNG\0\0binario")

        for name, content in (charts or {"chart_20.xml": CHART}).items():
            model.writestr(f"simulink/stateflow/{name}", content)

        for name, content in (extra or {}).items():
            model.writestr(name, content)

    return path


def chart(name, body):
    return f'<chart id="1"><P Name="name">{name}</P><state><eml><P Name="script">{body}</P></eml></state></chart>'


def test_saca_el_codigo_del_bloque(tmp_path):
    [(name, script)] = blocks_of(write_model(tmp_path / "m.slx"))

    assert name == "Controlador"
    assert script.startswith("function [v, w] = fcn(t_clock, x_r)")


def test_el_xml_se_decodifica(tmp_path):
    [(_, script)] = blocks_of(write_model(tmp_path / "m.slx"))

    assert "coder.extrinsic('get_tramo');" in script and "v = 0.5 < x_r;" in script


def test_no_lee_nada_mas_del_modelo(tmp_path):
    text = model_text(write_model(tmp_path / "m.slx"))

    assert "no entra" not in text and "PNG" not in text and "eML_blk_kernel" not in text


def test_varios_bloques_en_orden_estable(tmp_path):
    charts = {"chart_2.xml": chart("Segundo", "b = 2;"), "chart_1.xml": chart("Primero", "a = 1;")}

    assert [name for name, _ in blocks_of(write_model(tmp_path / "m.slx", charts))] == ["Primero", "Segundo"]


def test_un_modelo_sin_bloques_de_codigo(tmp_path):
    assert model_text(write_model(tmp_path / "m.slx", {"chart_1.xml": chart("Vacio", "   ")})) == ""


def test_la_marca_vuelve_a_dar_los_bloques(tmp_path):
    charts = {"chart_1.xml": chart("Uno", "a = 1;"), "chart_2.xml": chart("Dos", "b = 2;\nc = 3;")}
    path = write_model(tmp_path / "m.slx", charts)

    assert simulink.split_blocks(model_text(path)) == [("Uno", "a = 1;"), ("Dos", "b = 2;\nc = 3;")]


@pytest.mark.parametrize("declared", ["<!DOCTYPE lol [<!ENTITY a 'x'>]>", "<!ENTITY a 'x'>"])
def test_no_procesa_xml_con_entidades(tmp_path, declared):
    bomb = f'<?xml version="1.0"?>{declared}{chart("Bomba", "a = 1;")}'

    assert blocks_of(write_model(tmp_path / "m.slx", {"chart_1.xml": bomb})) == []


def test_no_descomprime_un_chart_enorme(tmp_path, monkeypatch):
    monkeypatch.setattr(simulink, "MAX_XML_BYTES", 10)

    assert blocks_of(write_model(tmp_path / "m.slx")) == []


def test_ignora_lo_que_no_es_stateflow(tmp_path):
    path = write_model(tmp_path / "m.slx", extra={"otro/chart_9.xml": chart("Otro", "z = 9;")})

    assert [name for name, _ in blocks_of(path)] == ["Controlador"]


def test_se_trocea_como_un_m_con_el_bloque_de_etiqueta(tmp_path):
    chunks = chunk_text(model_text(write_model(tmp_path / "m.slx")), ".slx")

    assert {chunk.label for chunk in chunks} == {"Controlador"}
    assert "function [v, w]" in chunks[0].text
    assert simulink.BLOCK_MARK not in "".join(chunk.text for chunk in chunks)


def test_las_lineas_son_las_del_bloque(tmp_path):
    charts = {"chart_1.xml": chart("Uno", "a = 1;\nb = 2;"), "chart_2.xml": chart("Dos", "c = 3;")}

    chunks = chunk_text(model_text(write_model(tmp_path / "m.slx", charts)), ".slx")

    assert [(c.label, c.start_line, c.end_line) for c in chunks] == [("Uno", 1, 2), ("Dos", 1, 1)]


def source_filter(root):
    return SourceFilter(root, {".py", ".m"}, set())


def test_un_modelo_real_entra_aunque_sea_binario(tmp_path):
    assert source_filter(tmp_path).allows(write_model(tmp_path / "m.slx"))


def test_un_slx_que_no_es_zip_no_entra(tmp_path):
    path = tmp_path / "falso.slx"
    path.write_bytes(b"\0\0\0 esto no es un zip")

    assert not source_filter(tmp_path).allows(path)


def test_un_modelo_de_mas_de_1_mb_no_entra(tmp_path, monkeypatch):
    monkeypatch.setattr("core.rag.exclusions.MAX_FILE_BYTES", 10)

    assert not source_filter(tmp_path).allows(write_model(tmp_path / "m.slx"))


def test_el_gitignore_tambien_vale_para_modelos(tmp_path):
    (tmp_path / ".gitignore").write_text("*.slx\n", encoding="utf-8")

    assert not source_filter(tmp_path).allows(write_model(tmp_path / "m.slx"))


def test_otros_binarios_siguen_fuera(tmp_path):
    path = tmp_path / "a.m"
    path.write_bytes(b"binario\0")

    assert not source_filter(tmp_path).allows(path)


def test_entra_al_indice_con_su_etiqueta(tmp_path, embeddings):  # noqa: F811
    project = tmp_path / "proyecto"
    project.mkdir()
    write_model(project / "control.slx")
    indexer = ProjectIndexer(str(project), "bolita", persist_dir=tmp_path / "i")

    assert indexer.index_project() >= 1

    indexed = indexer.store.all_documents()
    assert indexed["documents"][0].startswith("control.slx · Controlador\nfunction [v, w]")
    assert indexed["metadatas"][0]["label"] == "Controlador"


def test_un_modelo_sin_cambios_no_se_reindexa(tmp_path, embeddings):  # noqa: F811
    project = tmp_path / "proyecto"
    project.mkdir()
    write_model(project / "control.slx")
    ProjectIndexer(str(project), "bolita", persist_dir=tmp_path / "i").index_project()

    again = ProjectIndexer(str(project), "bolita", persist_dir=tmp_path / "i")
    again.index_project()

    assert (again.changed, again.unchanged) == (0, 1)


def test_un_modelo_danado_no_rompe_la_indexacion(tmp_path, embeddings):  # noqa: F811
    project = tmp_path / "proyecto"
    project.mkdir()
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")
    write_model(project / "roto.slx", {"chart_1.xml": "<chart><sin cerrar"})

    assert ProjectIndexer(str(project), "bolita", persist_dir=tmp_path / "i").index_project() == 1


def test_lineas_de_dos_bloques_no_se_juntan():
    shown = verified_lines([
        Quote("m.slx", 1, "Uno", "a = 1;"),
        Quote("m.slx", 1, "Dos", "b = 2;"),
        Quote("m.slx", 2, "Uno", "c = 3;"),
    ])

    assert "m.slx:1-2 (Uno)\n  a = 1;\n  c = 3;" in shown and "m.slx:1 (Dos)\n  b = 2;" in shown
