"""Cambios confirmados: si el archivo cambió desde la propuesta, no se escribe encima (carpetas temporales)."""
import json
import os
from types import SimpleNamespace

import pytest

from test_confidencial import make_brain
from tools.apply_changes_tool import ApplyChangesTool, file_hash

STALE = "El archivo cambió desde la propuesta"


@pytest.fixture
def tool(tmp_path):
    return ApplyChangesTool(pending_file=tmp_path / "memoria" / "pending.json", backup_dir=tmp_path / "bak")


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "datos.py"
    path.write_text("x = 1\n", encoding="utf-8")
    return path


def pending(tool):
    return json.loads(tool.pending_file.read_text(encoding="utf-8"))


def test_al_proponer_guarda_el_hash_del_archivo(tool, target):
    tool.propose_change(str(target), "x = 2\n")

    assert pending(tool)["old_hash"] == file_hash(target) and len(pending(tool)["old_hash"]) == 64


def test_sin_cambios_en_el_archivo_se_aplica_como_siempre(tool, target):
    tool.propose_change(str(target), "x = 2\n")

    assert tool.apply_pending_change().startswith("Cambio aplicado correctamente")
    assert target.read_text(encoding="utf-8") == "x = 2\n" and not tool.stale
    assert len(list((tool.backup_dir).glob("*.bak"))) == 1 and not tool.pending_file.exists()


def test_si_el_archivo_cambio_no_se_escribe_y_se_avisa(tool, target):
    tool.propose_change(str(target), "x = 2\n")
    target.write_text("x = 1\ny = 5  # lo que añadí yo\n", encoding="utf-8")

    answer = tool.apply_pending_change()

    assert answer.startswith(STALE) and "¿Vuelvo a proponer el cambio con el archivo actual? s/N" in answer
    assert target.read_text(encoding="utf-8") == "x = 1\ny = 5  # lo que añadí yo\n"
    assert tool.stale and tool.pending_file.exists() and not list(tool.backup_dir.glob("*.bak"))


def test_solo_cambia_la_hora_pero_no_el_contenido_se_aplica(tool, target):
    tool.propose_change(str(target), "x = 2\n")
    os.utime(target, (1_000_000_000, 1_000_000_000))

    assert tool.apply_pending_change().startswith("Cambio aplicado")


def test_un_archivo_nuevo_que_alguien_creo_no_se_pisa(tool, tmp_path):
    new = tmp_path / "nuevo.py"
    tool.propose_change(str(new), "x = 1\n")
    new.write_text("lo escribió otro\n", encoding="utf-8")

    assert tool.apply_pending_change().startswith(STALE)
    assert new.read_text(encoding="utf-8") == "lo escribió otro\n"


def test_un_archivo_que_se_borro_tampoco_se_recrea(tool, target):
    tool.propose_change(str(target), "x = 2\n")
    target.unlink()

    assert tool.apply_pending_change().startswith(STALE) and not target.exists()


def test_un_cambio_pendiente_de_antes_del_hash_se_compara_con_el_texto_guardado(tool, target):
    tool.propose_change(str(target), "x = 2\n")
    data = pending(tool)
    del data["old_hash"]
    tool.pending_file.write_text(json.dumps(data), encoding="utf-8")

    target.write_text("otra cosa\n", encoding="utf-8")
    assert tool.apply_pending_change().startswith(STALE)

    target.write_text("x = 1\n", encoding="utf-8")
    assert tool.apply_pending_change().startswith("Cambio aplicado")


def test_volver_a_proponer_usa_el_archivo_actual(tool, target):
    tool.propose_change(str(target), "x = 2\n")
    target.write_text("x = 1\ny = 5\n", encoding="utf-8")
    tool.apply_pending_change()

    proposal = tool.repropose_pending_change()

    assert "Cambio propuesto para" in proposal and "-y = 5" in proposal and "confirmar cambio" in proposal
    assert pending(tool)["old_hash"] == file_hash(target) and not tool.stale
    assert tool.apply_pending_change().startswith("Cambio aplicado") and target.read_text(encoding="utf-8") == "x = 2\n"


def test_volver_a_proponer_sin_cambio_pendiente(tool):
    assert tool.repropose_pending_change() == "No hay ningún cambio pendiente que volver a proponer."


# --- El flujo completo, por el Brain --------------------------------------------------

@pytest.fixture
def brain(tool):
    brain = make_brain()
    brain.tool_registry = SimpleNamespace(get_apply_changes_tool=lambda: tool, app_tool=None)
    return brain


def propose_and_change(tool, target):
    tool.propose_change(str(target), "x = 2\n")
    target.write_text("x = 1\ny = 5\n", encoding="utf-8")


def test_confirmar_cambio_con_el_archivo_cambiado_avisa_y_ofrece_volver_a_proponer(brain, tool, target):
    propose_and_change(tool, target)

    answer = brain.process("confirmar cambio")

    assert answer.startswith(STALE) and "s/N" in answer
    assert target.read_text(encoding="utf-8") == "x = 1\ny = 5\n"


def test_con_un_si_vuelve_a_proponer_y_luego_se_confirma(brain, tool, target):
    propose_and_change(tool, target)
    brain.process("confirmar cambio")

    assert "Cambio propuesto para" in brain.process("sí")
    assert target.read_text(encoding="utf-8") == "x = 1\ny = 5\n"    # proponer no escribe
    assert brain.process("confirmar cambio").startswith("Cambio aplicado correctamente")
    assert target.read_text(encoding="utf-8") == "x = 2\n"


def test_con_un_no_sigue_pendiente_y_no_se_escribe(brain, tool, target):
    propose_and_change(tool, target)
    brain.process("confirmar cambio")

    assert brain.process("no") == "Vale, el cambio sigue pendiente: «cancelar cambio» lo descarta."
    assert tool.pending_file.exists() and target.read_text(encoding="utf-8") == "x = 1\ny = 5\n"
    assert brain.process("cancelar cambio") == "Cambio cancelado."


def test_sin_respuesta_la_pregunta_se_olvida(brain, tool, target):
    propose_and_change(tool, target)
    brain.process("confirmar cambio")

    brain.process("cuéntame un chiste")
    brain.process("sí")

    assert target.read_text(encoding="utf-8") == "x = 1\ny = 5\n"
    assert pending(tool)["old_hash"] != file_hash(target)    # no volvió a proponer


def test_un_cambio_aplicado_no_deja_la_pregunta_pendiente(brain, tool, target):
    tool.propose_change(str(target), "x = 2\n")

    assert brain.process("confirmar cambio").startswith("Cambio aplicado correctamente")
    assert not brain.pending_repropose
