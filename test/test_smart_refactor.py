import pytest

from core.brain import Brain
from core.paths import PROJECT_ROOT


class FakeIntentEngine:
    def __init__(self, intent):
        self.intent = intent

    def detect(self, text):
        return self.intent


class FakeToolRegistry:
    def __init__(self):
        self.calls = []

    def execute(self, action, **kwargs):
        self.calls.append(action)
        return "contenido"


class FakeProviderRouter:
    def __init__(self):
        self.prompts = []

    def ask(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return "respuesta sin código"


def make_brain(file_path):
    brain = Brain.__new__(Brain)
    brain.intent_engine = FakeIntentEngine(
        {"action": "smart_refactor", "params": {"file_path": str(file_path)}}
    )
    brain.tool_registry = FakeToolRegistry()
    brain.provider_router = FakeProviderRouter()
    return brain


@pytest.mark.parametrize(
    "file_path",
    [
        PROJECT_ROOT / "core" / "brain.py",
        "core/brain.py",
        "./CORE/Intent_Engine.py",
        "tools\\tool_registry.py",
    ],
)
def test_smart_refactor_rechaza_archivo_protegido(monkeypatch, file_path):
    monkeypatch.chdir(PROJECT_ROOT)
    brain = make_brain(file_path)

    result = brain.process("refactoriza el archivo")

    assert "archivo protegido" in result
    assert brain.provider_router.prompts == []
    assert brain.tool_registry.calls == []


def test_smart_refactor_archivo_normal_llega_al_llm(monkeypatch, tmp_path):
    # Un core/brain.py de otro proyecto no está protegido.
    other = tmp_path / "core" / "brain.py"
    other.parent.mkdir()
    other.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    brain = make_brain("core/brain.py")

    result = brain.process("refactoriza core/brain.py")

    assert "archivo protegido" not in result
    assert len(brain.provider_router.prompts) == 1
    assert "No pude extraer CODE" in result
