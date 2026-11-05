"""Las respuestas de debug_project y del archivo protegido de generate_code, sin la sangría de 12 espacios."""
from types import SimpleNamespace

from core.actions import code
from test_confidencial import make_brain


def test_el_diagnostico_de_depuracion_sin_sangria():
    brain = make_brain()
    brain.tool_registry = SimpleNamespace(execute=lambda *a, **k: "línea 1\nlínea 2")

    answer = brain.handle_debug_project("encuentra por qué falla", {})

    assert answer.startswith("Diagnóstico de depuración:\n\nlínea 1\nlínea 2\n\n")
    assert not any(line.startswith(" ") for line in answer.splitlines())


def test_el_archivo_protegido_sin_sangria(monkeypatch, tmp_path):
    brain = make_brain()
    brain.last_debug_report = None
    brain.tool_registry = SimpleNamespace(execute=lambda *a, **k: "")
    brain.provider_router.ask = lambda prompt, **options: "respuesta"
    monkeypatch.setattr(code, "parse_code_response", lambda response: (str(tmp_path / "brain.py"), "x = 1", "explica"))
    monkeypatch.setattr(code, "is_protected_file", lambda path: True)
    monkeypatch.setattr(type(brain), "check_generated_imports", lambda self, prompt, path, c, e: (c, e, None))

    answer = brain.handle_generate_code("cambia brain.py", {"request": "cambia brain.py"})

    assert answer.startswith("Asia generó un cambio para un archivo protegido:\n\n")
    assert not any(line.startswith(" ") for line in answer.splitlines())
