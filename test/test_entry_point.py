"""jarvis.exe (fase I): el entry point de pyproject.toml y lo que necesita para funcionar igual."""
import importlib
import inspect
import tomllib

import launcher
from core.paths import PROJECT_ROOT


def project():
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_jarvis_apunta_a_launcher_main():
    module, function = project()["project"]["scripts"]["jarvis"].split(":")

    assert getattr(importlib.import_module(module), function) is launcher.main


def test_main_se_puede_llamar_sin_argumentos():
    # El .exe hace sys.exit(main()): los argumentos los lee argparse de sys.argv.
    parameters = inspect.signature(launcher.main).parameters.values()

    assert all(p.default is not inspect.Parameter.empty for p in parameters)


def test_el_nombre_en_la_ayuda_no_depende_del_exe():
    assert launcher.build_parser().prog == "jarvis"


def test_incluye_el_codigo_de_asia():
    tool = project()["tool"]["setuptools"]

    assert tool["py-modules"] == ["launcher"]

    for package in ("core", "config", "providers", "memory", "tools"):
        assert any(pattern.startswith(package) for pattern in tool["packages"]["find"]["include"])
