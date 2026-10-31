"""Arranque rápido: las librerías pesadas se cargan al usarse, no al abrir Asia."""
import subprocess
import sys

import pytest

from core.intent_engine import IntentEngine
from core.paths import PROJECT_ROOT
from providers.ollama_provider import OllamaProvider

HEAVY = ("ollama", "httpx", "chromadb", "google.genai", "requests")


def loaded_after(code):
    """Módulos pesados cargados tras ejecutar code en un proceso nuevo."""
    check = f"import sys\n{code}\nprint([m for m in {HEAVY!r} if m in sys.modules])"
    result = subprocess.run(
        [sys.executable, "-c", check], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


def test_importar_asia_no_las_carga():
    assert loaded_after("import launcher") == "[]"


def test_crear_brain_no_las_carga():
    assert loaded_after("import launcher\nfrom core.brain import Brain\nBrain()") == "[]"


def test_help_no_las_carga():
    code = "import launcher\ntry:\n    launcher.main(['--help'])\nexcept SystemExit:\n    pass"

    assert loaded_after(code) == "[]"


def test_ollama_se_importa_al_primer_uso_del_cliente():
    code = "from core.intent_engine import IntentEngine\nIntentEngine().client"

    assert "'ollama'" in loaded_after(code)


def test_la_precarga_del_interactivo_lo_importa_en_su_hilo():
    code = (
        "import threading\n"
        "from core.brain import Brain\n"
        "brain = Brain()\n"
        "main = threading.current_thread()\n"
        "seen = []\n"
        "brain.intent_engine.preload = lambda: (seen.append(threading.current_thread()), brain.intent_engine.client)\n"
        "brain.preload_in_background().join()\n"
        "assert seen[0] is not main\n"
    )

    assert "'ollama'" in loaded_after(code)


@pytest.mark.parametrize("cls", [IntentEngine, OllamaProvider])
def test_un_cliente_asignado_se_usa_tal_cual(cls):
    instance = cls()
    fake = object()

    instance.client = fake

    assert instance.client is fake


def test_el_router_no_crea_los_proveedores_al_arrancar():
    assert loaded_after("from providers.provider_router import ProviderRouter\nProviderRouter()") == "[]"
