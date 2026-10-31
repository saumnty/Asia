"""/pendiente, /pendientes y /hecho: en carpetas temporales, sin modelo."""
import json

import pytest

from core import paths
from core.commands import COMMANDS, options_text
from core.provenance import USUARIO
from core.tasks import TaskList
from test_confidencial import make_brain


def test_anota_lista_y_cierra_por_numero():
    brain = make_brain()

    assert brain.process("/pendiente Revisar el PID del Bolitabot") == "Anotado: Revisar el PID del Bolitabot"
    brain.process("/pendiente Llamar al asesor")

    assert brain.process("/pendientes") == "Pendientes:\n1. Revisar el PID del Bolitabot\n2. Llamar al asesor"
    assert brain.process("/hecho 1") == "Hecho: Revisar el PID del Bolitabot"
    # Los números se recorren: son los de la lista abierta.
    assert brain.process("/pendientes") == "Pendientes:\n1. Llamar al asesor"


def test_se_guarda_con_origen_usuario_y_el_cerrado_no_se_borra():
    brain = make_brain()

    brain.process("/pendiente Comprar cables")
    brain.process("/hecho 1")

    [task] = json.loads(paths.TASKS_FILE.read_text(encoding="utf-8"))
    assert task["texto"] == "Comprar cables" and task["origen"] == USUARIO
    assert task["creado"] and task["hecho"]
    assert brain.process("/pendientes") == "No hay pendientes abiertos."


def test_no_llaman_al_modelo():
    brain = make_brain()

    def forbidden(text):
        raise AssertionError("no debe pasar por el IntentEngine")

    brain.intent_engine.detect = forbidden

    for command in ("/pendiente algo", "/pendientes", "/hecho 1"):
        brain.process(command)


@pytest.mark.parametrize(
    "command, expected",
    [
        ("/pendiente", "Escribe el pendiente"),
        ("/hecho", "Di qué número"),
        ("/hecho dos", "Di qué número"),
        ("/hecho 7", "No hay un pendiente 7"),
        ("/hecho 0", "No hay un pendiente 0"),
    ],
)
def test_errores_de_uso(command, expected):
    assert expected in make_brain().process(command)


def test_conserva_mayusculas_y_acentos_en_el_archivo():
    make_brain().process("/pendiente Enviar el Reporte de Física")

    assert "Enviar el Reporte de Física" in paths.TASKS_FILE.read_text(encoding="utf-8")


def test_escritura_atomica_un_fallo_deja_el_archivo_intacto(monkeypatch):
    tasks = TaskList()
    tasks.add("primero")
    before = paths.TASKS_FILE.read_bytes()

    def broken(path, target):
        raise OSError("disco lleno")

    monkeypatch.setattr("core.atomic_write.os.replace", broken)

    with pytest.raises(OSError):
        tasks.add("segundo")

    assert paths.TASKS_FILE.read_bytes() == before
    assert [p.name for p in paths.TASKS_FILE.parent.iterdir()] == [paths.TASKS_FILE.name]


def test_archivo_danado_no_se_sobrescribe():
    paths.TASKS_FILE.parent.mkdir(parents=True)
    paths.TASKS_FILE.write_text("{ roto", encoding="utf-8")
    brain = make_brain()

    assert "No pude leer los pendientes" in brain.process("/pendiente algo")
    assert "No pude leer los pendientes" in brain.process("/pendientes")
    assert paths.TASKS_FILE.read_text(encoding="utf-8") == "{ roto"


def test_estan_en_la_tabla_de_opciones():
    for slash in ("/pendiente <texto>", "/pendientes", "/hecho <n>"):
        assert any(c.slash == slash and c.group == "pendientes" for c in COMMANDS)
        assert slash in options_text()
