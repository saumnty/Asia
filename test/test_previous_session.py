"""Sesión anterior con el resumen de sesión (fase R), y el resumen del proyecto con su fecha."""
import os
from datetime import date, datetime

import pytest

from core.reflection import asks_previous_session, previous_session_text, save_summary
from memory.project_memory import STALE_DAYS, ProjectMemory, age_notice
from test_confidencial import make_brain


@pytest.mark.parametrize(
    "text", ["¿Qué hicimos en la sesión anterior?", "¿de qué hablamos la última vez?", "qué hicimos ayer", "¿Qué hicimos?"]
)
def test_pregunta_por_la_sesion_anterior(text):
    assert asks_previous_session(text)


@pytest.mark.parametrize("text", ["¿qué hicimos mal en el código?", "resume el proyecto", "hola"])
def test_no_pregunta_por_la_sesion_anterior(text):
    assert not asks_previous_session(text)


class NoModel:
    def detect(self, text, model=None):
        raise AssertionError("no debía ir al IntentEngine")


def test_responde_con_el_resumen_de_la_sesion_anterior():
    save_summary("Hablamos de PID y del trébol.", "modelo", 6)
    brain = make_brain()
    brain.intent_engine = NoModel()
    brain.previous_session = None

    answer = brain.process("¿Qué hicimos en la sesión anterior?")

    assert answer.startswith("En la sesión anterior (") and answer.endswith("Hablamos de PID y del trébol.")


def test_vale_el_de_al_abrir_aunque_el_archivo_ya_sea_de_esta_sesion():
    brain = make_brain()
    brain.previous_session = {"fecha": "2026-11-02T10:00:00", "resumen": "Lo de ayer."}
    save_summary("Lo de hoy.", "modelo", 2)

    assert brain.process("¿qué hicimos la última vez?") == "En la sesión anterior (2026-11-02 10:00): Lo de ayer."


def test_sin_resumen():
    assert previous_session_text(None) == "No tengo resumen de la sesión anterior."


def test_fecha_del_resumen_del_proyecto(tmp_path):
    projects = ProjectMemory(projects_dir=tmp_path)
    path = projects.save_project_summary("asia", "ToolRegistry, GUI")
    old = datetime(2026, 6, 5).timestamp()
    os.utime(path, (old, old))

    saved = projects.summary_date("asia")

    assert saved == date(2026, 6, 5)
    assert projects.summary_date("otro") is None
    notice = age_notice(saved, today=date(2026, 11, 3))
    assert notice.startswith("Resumen del proyecto guardado el 2026-06-05 (hace 151 días): puede estar desactualizado.")
    assert "«resume el proyecto y guarda el resumen»" in notice
    assert age_notice(date(2026, 11, 1), today=date(2026, 11, 3)) == "Resumen del proyecto guardado el 2026-11-01."
    assert age_notice(date(2026, 10, 1), today=date(2026, 10, 1 + STALE_DAYS)) .endswith("10-01.")


class Router:
    def ask(self, prompt, **options):
        return "Falta la GUI."


def test_ask_project_memory_dice_la_fecha(tmp_path):
    projects = ProjectMemory(projects_dir=tmp_path)
    projects.save_project_summary("asia", "ToolRegistry, GUI")
    brain = make_brain()
    brain.project_memory = projects
    brain.provider_router = Router()
    brain.active_project = lambda: "asia"

    answer = brain.handle_ask_project_memory("según mi proyecto, qué falta?", {"question": "qué falta"})

    assert answer == f"Resumen del proyecto guardado el {date.today().isoformat()}.\n\nFalta la GUI."


def test_el_chat_recibe_el_resumen_con_su_fecha(tmp_path):
    from test_provenance import make_router

    projects = ProjectMemory(projects_dir=tmp_path)
    projects.save_project_summary("asia", "ToolRegistry, GUI")
    router = make_router(project="x")
    router.project_memory = projects

    assert router.build_project_context() == f"(Resumen del proyecto guardado el {date.today().isoformat()}.)\nToolRegistry, GUI"
