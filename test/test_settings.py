import json

from config.settings_manager import SettingsManager


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
