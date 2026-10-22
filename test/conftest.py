import pytest

from config.settings_manager import SettingsManager


@pytest.fixture(autouse=True)
def no_session_overrides(monkeypatch):
    """Los flags de la CLI (SettingsManager.overrides) no pasan de una prueba a otra."""
    monkeypatch.setattr(SettingsManager, "overrides", {})
