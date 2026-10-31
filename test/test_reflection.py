"""Reflexión (fase R): resumen al abrir, resumen al salir y sesión. Con modelo simulado."""
import launcher
from core import paths
from core.reflection import first_sentences, load_summary, opening_text, save_summary
from core.tasks import TaskList
from test_launcher import FakeBrain, reader


def opened(capsys, lines=("salir",)):
    launcher.interactive_mode(FakeBrain("hecho"), read=reader(list(lines)))
    return capsys.readouterr().out


# --- Al abrir ----------------------------------------------------------------------

def test_sin_nada_no_muestra_nada(capsys):
    assert opening_text() == ""
    assert "Sesión anterior" not in opened(capsys) and "Pendientes" not in opened(capsys)


def test_muestra_una_o_dos_frases_y_los_pendientes(capsys):
    save_summary("Revisamos el PID. Ajustamos la ganancia a 3.5 por ciento. Quedó probar en el robot.", "modelo", 6)
    TaskList().add("Probar en el robot")
    TaskList().add("Actualizar el reporte")

    out = opened(capsys)

    assert "Revisamos el PID. Ajustamos la ganancia a 3.5 por ciento." in out
    assert "Quedó probar" not in out
    assert "Pendientes:\n1. Probar en el robot\n2. Actualizar el reporte" in out


def test_solo_pendientes_o_solo_resumen():
    TaskList().add("Uno")
    assert opening_text() == "Pendientes:\n1. Uno"

    TaskList().close(1)
    save_summary("Hablamos de grafos.", "modelo", 2)
    assert "Hablamos de grafos." in opening_text() and "Pendientes" not in opening_text()


def test_abrir_no_llama_al_modelo(capsys):
    save_summary("Hablamos de grafos.", "modelo", 2)

    class NoModel(FakeBrain):
        @property
        def provider_router(self):
            raise AssertionError("abrir Asia no debe usar el modelo")

        @provider_router.setter
        def provider_router(self, value):
            pass

    launcher.interactive_mode(NoModel("hecho"), read=reader(["salir"]))

    assert "Hablamos de grafos." in capsys.readouterr().out


def test_archivos_danados_no_impiden_abrir(capsys):
    paths.SESSION_SUMMARY_FILE.parent.mkdir(parents=True)
    paths.SESSION_SUMMARY_FILE.write_text("{ roto", encoding="utf-8")
    paths.TASKS_FILE.write_text("{ roto", encoding="utf-8")

    assert load_summary() is None and opening_text() == ""
    assert "Asia apagada." in opened(capsys)


def test_primeras_frases():
    assert first_sentences("Una. Dos! ¿Tres? Cuatro.", 2) == "Una. Dos!"
    assert first_sentences("Pesa 3.5 GB y ya. Otra.", 1) == "Pesa 3.5 GB y ya."
    assert first_sentences("Sin punto", 2) == "Sin punto"
