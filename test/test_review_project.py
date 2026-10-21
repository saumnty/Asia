import pytest

from core.brain import Brain, wants_synthesis


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

        if action == "select_project_files":
            return ["a.py", "b.py"]

        return "reporte de a.py"


class FakeProviderRouter:
    def __init__(self):
        self.prompts = []

    def ask(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return "síntesis"


class FakeSettings:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        if key == "context_limits":
            return {"review_project_files": 5, "review_project_file": 100}
        return self.values.get(key, default)


def make_brain(params, **settings):
    brain = Brain.__new__(Brain)
    brain.intent_engine = FakeIntentEngine(
        {"action": "review_project", "params": params}
    )
    brain.tool_registry = FakeToolRegistry()
    brain.provider_router = FakeProviderRouter()
    brain.settings = FakeSettings(**settings)
    return brain


def test_review_project_no_corre_analisis_estatico():
    brain = make_brain({"folder_path": "."})

    assert brain.process("revisa el proyecto") == "síntesis"
    assert brain.tool_registry.calls == [
        "select_project_files",
        "review_project_files",
    ]
    assert "reporte de a.py" in brain.provider_router.prompts[0]


@pytest.mark.parametrize(
    "text, params",
    [
        ("revisa el proyecto sin síntesis", {"folder_path": "."}),
        ("revisa el proyecto SIN SINTESIS", {"folder_path": "."}),
        ("dame los reportes por archivo", {"folder_path": "."}),
        ("revisa el proyecto", {"folder_path": ".", "synthesis": False}),
        ("revisa el proyecto", {"folder_path": ".", "synthesis": "false"}),
    ],
)
def test_review_project_sin_sintesis_no_llama_al_llm(text, params):
    brain = make_brain(params)

    result = brain.process(text)

    assert brain.provider_router.prompts == []
    assert "sin síntesis" in result
    assert "- a.py\n- b.py" in result
    assert result.endswith("reporte de a.py")


def test_review_project_default_de_config_sin_sintesis():
    brain = make_brain({"folder_path": "."}, review_project_synthesis=False)

    result = brain.process("revisa el proyecto")

    assert brain.provider_router.prompts == []
    assert "reporte de a.py" in result


def test_review_project_param_true_gana_al_default_de_config():
    brain = make_brain(
        {"folder_path": ".", "synthesis": True},
        review_project_synthesis=False,
    )

    assert brain.process("revisa el proyecto") == "síntesis"


def test_wants_synthesis_valores():
    assert wants_synthesis("revisa", {}) is True
    assert wants_synthesis("revisa", {}, default=False) is False
    assert wants_synthesis("revisa", {"synthesis": "no"}) is False
    assert wants_synthesis("revisa", {"synthesis": "true"}) is True
    assert wants_synthesis("revisa", {"synthesis": ""}, default=False) is False
    assert wants_synthesis(None, {}) is True
    # La frase del usuario manda aunque el IntentEngine diga lo contrario.
    assert wants_synthesis("sin síntesis", {"synthesis": True}) is False
