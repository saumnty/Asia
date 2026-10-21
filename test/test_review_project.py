from core.brain import Brain


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
            return ["a.py"]

        return "reporte de a.py"


class FakeProviderRouter:
    def __init__(self):
        self.prompts = []

    def ask(self, prompt):
        self.prompts.append(prompt)
        return "síntesis"


class FakeSettings:
    def get(self, key, default=None):
        if key == "context_limits":
            return {"review_project_files": 5, "review_project_file": 100}
        return default


def make_brain(intent):
    brain = Brain.__new__(Brain)
    brain.intent_engine = FakeIntentEngine(intent)
    brain.tool_registry = FakeToolRegistry()
    brain.provider_router = FakeProviderRouter()
    brain.settings = FakeSettings()
    return brain


def test_review_project_no_corre_analisis_estatico():
    brain = make_brain(
        {"action": "review_project", "params": {"folder_path": "."}}
    )

    assert brain.process("revisa el proyecto") == "síntesis"
    assert brain.tool_registry.calls == [
        "select_project_files",
        "review_project_files",
    ]
    assert "reporte de a.py" in brain.provider_router.prompts[0]
