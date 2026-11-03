"""ASIA.md opcional por fuente: en /buscar (sin citarse) y al explicar, revisar y generar código."""
from core.provenance import PUBLICA, RAG, USUARIO, Fragment, current_fragments, labels_of, request_sources
from core.rag.instructions import FILE_NAME, MAX_CHARS, read_notes, source_notes
from core.rag.library import Library
from test_confidencial import make_brain
from test_rag_answer import ANSWER, CONTEXT, brain_with

NOTES = "pt es la carpeta del robot Bolitabot.\nLa ganancia se llama kp."


def bolitabot(tmp_path, notes=NOTES, publica=False):
    folder = tmp_path / "bolitabot"
    folder.mkdir()

    if notes is not None:
        (folder / FILE_NAME).write_text(notes, encoding="utf-8")

    Library().save("Bolitabot", "proyecto", str(folder), 3, publica=publica)
    return folder


def test_las_notas_van_en_la_extraccion(tmp_path):
    bolitabot(tmp_path)
    brain = brain_with()

    brain.process("/buscar qué ganancia tiene")

    extraction = brain.provider_router.prompts[0]
    assert "Notas del usuario sobre las fuentes" in extraction
    assert f"Fuente Bolitabot:\n{NOTES}" in extraction
    # Antes de los fragmentos, una sola vez aunque haya tres fragmentos de la fuente.
    assert extraction.index(NOTES) < extraction.index("Fragmentos encontrados:")
    assert extraction.count(NOTES) == 1


def test_sin_asia_md_el_prompt_no_cambia(tmp_path):
    bolitabot(tmp_path, notes=None)
    brain = brain_with()

    brain.process("/buscar qué ganancia tiene")

    assert "Notas del usuario" not in brain.provider_router.prompts[0]


def test_una_linea_de_las_notas_no_vale_como_cita(tmp_path):
    bolitabot(tmp_path)
    brain = brain_with("[control/pid.py:40-55] La ganancia se llama kp.", ANSWER)

    brain.process("/buscar qué ganancia tiene")

    # Ninguna cita verificada: no hay redacción.
    assert len(brain.provider_router.prompts) == 1


def test_recortado_en_lineas_completas(tmp_path):
    folder = bolitabot(tmp_path, notes="\n".join(["una línea de notas"] * 500))

    text = read_notes(Library().get("Bolitabot"))

    assert len(text) < MAX_CHARS + 60
    assert text.endswith(f"[{FILE_NAME} recortado en {MAX_CHARS} caracteres]")
    assert all(line == "una línea de notas" for line in text.splitlines()[:-1])
    assert (folder / FILE_NAME).exists()


def test_fuente_sin_carpeta_o_desconocida():
    assert read_notes(None) == ""
    assert source_notes(CONTEXT, []) == ""


def test_las_notas_llevan_la_etiqueta_de_la_fuente(tmp_path):
    bolitabot(tmp_path)

    with request_sources(Fragment(USUARIO, "x")):
        source_notes(CONTEXT, Library().all())
        assert labels_of(current_fragments()) == {USUARIO, RAG}


def test_las_de_una_fuente_publica_son_publicas(tmp_path):
    bolitabot(tmp_path, publica=True)

    with request_sources(Fragment(USUARIO, "x")):
        source_notes(CONTEXT, Library().all())
        assert labels_of(current_fragments()) == {USUARIO, PUBLICA}


# --- Explicar, revisar y generar código en el proyecto ------------------------

class Registry:
    def execute(self, action, **kwargs):
        return "def suma(a, b):\n    return a + b\n"


class AskRouter:
    def __init__(self, answer="respuesta"):
        self.prompts = []
        self.answer = answer

    def ask(self, prompt, **options):
        self.prompts.append(prompt)
        return self.answer


def project_brain(tmp_path, monkeypatch, answer="respuesta"):
    from core.session import Session

    folder = bolitabot(tmp_path)
    (folder / "pid.py").write_text("def suma(a, b):\n    return a + b\n", encoding="utf-8")
    monkeypatch.setattr(Session, "user_cwd", folder)
    monkeypatch.chdir(folder)
    brain = make_brain()
    brain.tool_registry = Registry()
    brain.provider_router = AskRouter(answer)
    return brain


def test_explicar_lleva_el_asia_md_de_su_fuente(tmp_path, monkeypatch):
    brain = project_brain(tmp_path, monkeypatch)

    with request_sources(Fragment(USUARIO, "explica pid.py")):
        brain.handle_explain_file("explica pid.py", {"file_path": "pid.py"})
        labels = labels_of(current_fragments())

    [prompt] = brain.provider_router.prompts
    assert prompt.startswith(f"Notas del usuario sobre el proyecto Bolitabot (su {FILE_NAME}; contexto, no las copies):\n{NOTES}")
    assert RAG in labels


def test_revisar_lleva_el_asia_md(tmp_path, monkeypatch):
    brain = project_brain(tmp_path, monkeypatch)

    brain.handle_review_file("revisa pid.py", {"file_path": "pid.py"})

    assert NOTES in brain.provider_router.prompts[0]


def test_generar_codigo_lleva_el_asia_md(tmp_path, monkeypatch):
    brain = project_brain(tmp_path, monkeypatch, answer="sin formato")
    # make_brain no pasa por Brain.__init__.
    brain.last_debug_report = None

    brain.handle_generate_code("corrige pid.py", {"request": "corrige pid.py"})

    assert brain.provider_router.prompts[0].startswith("Notas del usuario sobre el proyecto Bolitabot")


def test_un_archivo_fuera_de_las_fuentes_no_lleva_notas(tmp_path, monkeypatch):
    from core.session import Session

    bolitabot(tmp_path)
    other = tmp_path / "otra"
    other.mkdir()
    monkeypatch.setattr(Session, "user_cwd", other)
    brain = make_brain()
    brain.tool_registry = Registry()
    brain.provider_router = AskRouter()

    brain.handle_explain_file("explica x.py", {"file_path": "x.py"})

    assert "Notas del usuario" not in brain.provider_router.prompts[0]


def test_vale_la_fuente_mas_interna(tmp_path):
    from core.rag.instructions import source_of

    outer = bolitabot(tmp_path)
    inner = outer / "test"
    inner.mkdir()
    Library().save("bolitabot-pruebas", "proyecto", str(inner), 1)

    assert source_of(inner / "test_pid.py", Library().all()).name == "bolitabot-pruebas"
    assert source_of(outer / "pid.py", Library().all()).name == "Bolitabot"
