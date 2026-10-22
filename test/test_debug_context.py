import pytest

from config.settings_manager import SettingsManager
from providers.ollama_provider import RESPONSE_RESERVE_TOKENS, estimate_tokens
from providers.provider_router import SYSTEM_PROMPT
from tools.debug_agent_tool import UNVERIFIED_DIAGNOSIS, DebugAgentTool
from tools.debug_context import FileHits, issue_terms, verify_citations

ISSUE = "encuentra por qué aparece Asia None"


class FakeProviderRouter:
    def __init__(self, response="SUMMARY:\nx\n"):
        self.prompts = []
        self.response = response

    def ask(self, prompt, review=False):
        self.prompts.append(prompt)
        return self.response


def run(folder, response="SUMMARY:\nx\n", issue=ISSUE):
    router = FakeProviderRouter(response)
    report = DebugAgentTool(None, router).debug_project(issue, str(folder))
    return report, router.prompts[0]


@pytest.fixture
def big_project(tmp_path):
    # 300 archivos de ~6000 caracteres con coincidencias: no caben enteros.
    for i in range(300):
        body = "\n".join(f"def f{n}():\n    print('x')\n    return None" for n in range(150))
        (tmp_path / f"mod_{i:03}.py").write_text(body, encoding="utf-8")

    (tmp_path / "zz_asia.py").write_text("def responder():\n    return f'Asia {None}'\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "num_ctx, own, limit",
    [
        (4096, 6000, "ollama_num_ctx, 3072 tokens"),
        (16384, 6000, "context_limits.debug_project_tokens, 6000 tokens"),
        (16384, 50000, "ollama_num_ctx, 15360 tokens"),
    ],
)
def test_prompt_cabe_en_el_contexto_con_un_proyecto_grande(big_project, num_ctx, own, limit):
    SettingsManager.set_overrides({"ollama_num_ctx": num_ctx, "context_limits": {"debug_project_tokens": own}})

    report, prompt = run(big_project)

    messages = [{"content": SYSTEM_PROMPT}, {"content": prompt}]
    assert estimate_tokens(messages) + RESPONSE_RESERVE_TOKENS <= num_ctx
    assert estimate_tokens(messages) <= own
    assert "--- Archivo: " in prompt
    assert f"Omitidos por el límite de contexto ({limit}): " in report
    assert " más." in report  # más de 10 omitidos: solo se nombran 10


def test_archivos_ordenados_por_coincidencias_con_el_problema(big_project):
    SettingsManager.set_overrides({"ollama_num_ctx": 4096})

    report, prompt = run(big_project)

    # zz_asia.py es el único con "Asia" y va primero aunque tenga menos líneas.
    assert prompt.index("--- Archivo: zz_asia.py") < prompt.index("--- Archivo: mod_")
    assert "Archivos leídos (" in report and ": zz_asia.py, " in report


def test_el_problema_va_al_principio_y_al_final(tmp_path):
    (tmp_path / "a.py").write_text("x = None\n", encoding="utf-8")

    _, prompt = run(tmp_path)

    assert prompt.index(ISSUE) < prompt.index("Evidencia encontrada")
    assert prompt.rstrip().endswith(f"Recuerda: el problema reportado es: {ISSUE}")


def test_reporte_dice_que_no_esta_verificado_y_sin_omitidos(tmp_path):
    (tmp_path / "a.py").write_text("x = None\n", encoding="utf-8")

    report, _ = run(tmp_path)

    assert report.startswith(UNVERIFIED_DIAGNOSIS)
    assert "Archivos leídos (1, por coincidencias con el problema): a.py." in report
    assert "Omitidos" not in report


def test_sin_pruebas_ni_archivos_que_no_son_codigo(tmp_path):
    (tmp_path / "a.py").write_text("x = None\n", encoding="utf-8")
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "test_a.py").write_text("assert None is None\n", encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text("Asia None\n", encoding="utf-8")

    report, prompt = run(tmp_path)

    assert "Archivos leídos (1, por coincidencias con el problema): a.py." in report
    assert "test_a.py" not in prompt and "ROADMAP" not in prompt


def test_carpeta_inexistente(tmp_path):
    router = FakeProviderRouter()

    report = DebugAgentTool(None, router).debug_project(ISSUE, str(tmp_path / "no"))

    assert report.startswith("No encontré la carpeta")
    assert router.prompts == []


def test_issue_terms():
    assert issue_terms(ISSUE) == ["Asia", "None"]
    assert issue_terms("Arregla generate_code en core/brain.py.") == ["generate_code", "brain.py"]
    assert issue_terms("Encuentra el error") == []


# --- Citas de EVIDENCIA -------------------------------------------------------

FILES = [
    FileHits(relative="core/brain.py", content="a = 1\n\ndef process(text):\n    return None\n"),
]

RESPONSE = """SUMMARY:
devuelve None

EVIDENCIA:
- core/brain.py:1 | return None
- `core/brain.py` | return respuesta_inventada()
- tools/fantasma.py | x = 1 + 2 + 3
algo sin formato

RECOMMENDED_NEXT_STEP:
revisar core/brain.py
"""


def test_citas_comprobadas_contra_el_archivo():
    report = verify_citations(RESPONSE, FILES)

    assert "EVIDENCIA (cada cita comprobada sin LLM contra el archivo):" in report
    # Línea corregida: el modelo dijo 1, la cita está en la 4.
    assert "- core/brain.py:4 | return None  [cita encontrada en el archivo]" in report
    assert "- core/brain.py | return respuesta_inventada()  [la cita NO está en el archivo: descartada]" in report
    assert "- tools/fantasma.py | x = 1 + 2 + 3  [el archivo no está entre los analizados: descartada]" in report
    assert "algo sin formato  [sin formato ruta | cita: no comprobada]" in report
    assert report.index("SUMMARY:") < report.index("EVIDENCIA") < report.index("RECOMMENDED_NEXT_STEP:")


def test_sin_seccion_evidencia():
    report = verify_citations("SUMMARY:\nx", FILES)

    assert report.endswith("el modelo no citó líneas; no hay nada comprobado.")


def test_las_citas_del_reporte_completo_se_comprueban(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return None\n", encoding="utf-8")

    report, _ = run(tmp_path, "SUMMARY:\nx\n\nEVIDENCIA:\na.py | return None\na.py | return 42\n")

    assert "- a.py:2 | return None  [cita encontrada en el archivo]" in report
    assert "- a.py | return 42  [la cita NO está en el archivo: descartada]" in report
