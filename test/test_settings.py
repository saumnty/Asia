import json

from config.settings_manager import SettingsManager, read_json


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def make_settings(tmp_path, defaults, local=None):
    defaults_path = tmp_path / "defaults.json"
    settings_path = tmp_path / "settings.json"

    write_json(defaults_path, defaults)

    if local is not None:
        write_json(settings_path, local)

    return SettingsManager(defaults_path, settings_path)


def test_sin_settings_local_usa_defaults(tmp_path):
    settings = make_settings(tmp_path, {"default_provider": "ollama"})

    assert settings.get("default_provider") == "ollama"
    assert settings.get("no_existe", "x") == "x"


def test_local_tiene_prioridad_y_diccionarios_se_combinan(tmp_path):
    settings = make_settings(
        tmp_path,
        {"default_provider": "ollama", "context_limits": {"a": 1, "b": 2}},
        {"default_provider": "gemini", "context_limits": {"b": 20}},
    )

    assert settings.get("default_provider") == "gemini"
    assert settings.get("context_limits") == {"a": 1, "b": 20}


def test_set_escribe_solo_settings_local(tmp_path):
    settings = make_settings(tmp_path, {"active_project": "asia", "otro": 1})

    settings.set("active_project", "practica2")

    assert settings.get("active_project") == "practica2"
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8")) == {
        "active_project": "practica2"
    }
    assert json.loads((tmp_path / "defaults.json").read_text(encoding="utf-8")) == {
        "active_project": "asia",
        "otro": 1,
    }


def test_ignored_dirs_en_minusculas_y_con_tests(tmp_path):
    settings = make_settings(
        tmp_path,
        {"ignored_dirs": [".Git", "Target"], "test_dirs": ["Tests"]},
    )

    assert settings.ignored_dirs() == {".git", "target"}
    assert settings.ignored_dirs(include_tests=True) == {".git", "target", "tests"}


def test_text_extensions_incluye_codigo(tmp_path):
    settings = make_settings(
        tmp_path,
        {"code_extensions": [".PY"], "text_extensions": [".md"]},
    )

    assert settings.text_extensions() == {".py", ".md"}


def test_overrides_de_sesion_ganan_y_no_se_escriben(tmp_path):
    settings = make_settings(
        tmp_path,
        {"default_provider": "ollama", "stream_output": True},
        {"default_provider": "gemini"},
    )

    SettingsManager.set_overrides({"default_provider": "ollama", "stream_output": False})

    assert settings.get("default_provider") == "ollama"
    assert settings.get("stream_output") is False
    # Otro SettingsManager (otra parte de Asia) ve lo mismo.
    assert SettingsManager(tmp_path / "defaults.json", tmp_path / "settings.json").get("stream_output") is False
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8")) == {
        "default_provider": "gemini"
    }


def test_set_explicito_gana_al_override(tmp_path):
    settings = make_settings(tmp_path, {"default_provider": "ollama"})
    SettingsManager.set_overrides({"default_provider": "ollama", "stream_output": False})

    settings.set("default_provider", "gemini")

    assert settings.get("default_provider") == "gemini"
    assert settings.get("stream_output") is False


def test_streaming_activado_por_defecto():
    from core.paths import DEFAULTS_FILE

    assert read_json(DEFAULTS_FILE)["stream_output"] is True
