import pytest

from config.settings_manager import SettingsManager


@pytest.fixture(autouse=True)
def no_session_overrides(monkeypatch):
    """Los flags de la CLI (SettingsManager.overrides) no pasan de una prueba a otra."""
    monkeypatch.setattr(SettingsManager, "overrides", {})


@pytest.fixture(autouse=True)
def audit_in_tmp(tmp_path, monkeypatch):
    """La bitácora de envíos externos de las pruebas no va a logs/ real."""
    from core import paths

    monkeypatch.setattr(paths, "EXTERNAL_AUDIT_FILE", tmp_path / "logs" / "external_audit.jsonl")


@pytest.fixture(autouse=True)
def no_preload(monkeypatch):
    """El modo interactivo precarga el modelo en Ollama: en las pruebas, no."""
    from core.brain import Brain

    monkeypatch.setattr(Brain, "preload_in_background", lambda self: None)
