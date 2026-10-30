import hashlib
import json

import pytest

import tools.app_tool as app_tool
from core.paths import APPS_FILE
from tools.app_resolver import clarification, close_app, normalize, resolve_known_app, suggestions
from tools.app_tool import AppTool

# Lista con las mismas claves que config/apps.json (no se lee ni se modifica
# el archivo real: las pruebas usan una copia en tmp_path).
APPS = {
    "chrome": "chrome",
    "google": "chrome",
    "navegador": "chrome",
    "vscode": "code",
    "visual studio code": "code",
    "visual": "code",
    "editor": "code",
    "bloc de notas": "notepad",
    "notepad": "notepad",
    "calculadora": "calc",
    "calculator": "calc",
    "spotify": "explorer.exe shell:AppsFolder\\SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
    "whatsapp": "explorer.exe shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
}


@pytest.fixture
def tool(tmp_path, monkeypatch):
    real_hash = hashlib.sha256(APPS_FILE.read_bytes()).hexdigest() if APPS_FILE.exists() else None
    config = tmp_path / "apps.json"
    config.write_text(json.dumps(APPS, ensure_ascii=False, indent=4), encoding="utf-8")
    launched = []
    start_menu = {}

    monkeypatch.setattr(app_tool, "launch", launched.append)
    monkeypatch.setattr(app_tool, "find_start_app", lambda name: start_menu.get(name))

    t = AppTool(config_file=config)
    t.launched, t.start_menu = launched, start_menu
    yield t

    if real_hash:
        assert hashlib.sha256(APPS_FILE.read_bytes()).hexdigest() == real_hash


@pytest.mark.parametrize(
    "name, command",
    [
        # Lo que devolvió qwen3:4b-instruct para "abre el bloc de notas".
        ("notebook", "notepad"),
        ("blocknote", "notepad"),
        ("Bloc de Notas", "notepad"),
        ("block de notas", "notepad"),
        ("bloc notas", "notepad"),
        ("blocdenotas", "notepad"),
        ("calculadra", "calc"),
        ("crome", "chrome"),
        ("spotfy", APPS["spotify"]),
        ("whatsap", APPS["whatsapp"]),
        ("vs code", "code"),
    ],
)
def test_variantes_cercanas_abren_la_app_correcta(tool, name, command):
    assert tool.open_app(name) == f"Abriendo {name}."
    assert tool.launched == [command]


def test_variante_aproximada_no_escribe_apps_json(tool):
    before = tool.config_file.read_text(encoding="utf-8")

    tool.open_app("calculadra")

    assert tool.config_file.read_text(encoding="utf-8") == before


def test_el_menu_inicio_va_antes_que_el_parecido(tool):
    # notepad++ instalado: no debe abrirse el Bloc de notas.
    tool.start_menu["notepad++"] = {"appid": "Notepad++.App"}

    tool.open_app("notepad++")

    assert tool.launched == ["explorer.exe shell:AppsFolder\\Notepad++.App"]


@pytest.mark.parametrize("name", ["visio", "excel", "word"])
def test_sin_coincidencia_pide_aclaracion_y_no_abre_nada(tool, name):
    message = tool.open_app(name)

    assert message.startswith(f"No encontré la aplicación '{name}'")
    assert tool.launched == []


def test_aclaracion_con_nombres_parecidos():
    # Una sugerencia por programa: "vscode" y "visual" abren lo mismo.
    assert suggestions("visio", APPS) == ["vscode"]
    assert clarification("visio", APPS) == (
        "No encontré la aplicación 'visio'. ¿Te refieres a \"vscode\"? "
        "Escribe, por ejemplo: abre vscode."
    )


def test_aclaracion_sin_nada_parecido_lista_las_conocidas():
    message = clarification("photoshop", APPS)

    assert "ni nada parecido" in message and "bloc de notas" in message
    assert "config/apps.json" in message


def test_resolve_y_close():
    assert normalize("  Bloc  de NÓTAS ") == "bloc de notas"
    assert resolve_known_app("NOTEBOOK", APPS) == "bloc de notas"
    # La variante solo vale si su destino existe en apps.json.
    assert resolve_known_app("notebook", {"chrome": "chrome"}) is None
    assert close_app("excel", APPS) is None
    # calculadora y calculator abren lo mismo: no es ambiguo.
    assert close_app("calculadra", APPS) in {"calculadora", "calculator"}


def test_nombre_vacio(tool):
    assert tool.open_app("  ") == "No encontré qué aplicación abrir."


# --- Apps aprendidas del menú Inicio, fuera de apps.json --------------------------

def test_lo_aprendido_va_a_apps_learned_y_no_a_apps_json(tool):
    before = tool.config_file.read_bytes()
    tool.start_menu["excel"] = {"appid": "Microsoft.Office.EXCEL.EXE.15"}

    assert tool.open_app("excel") == "Abriendo excel."

    assert tool.config_file.read_bytes() == before
    assert tool.learned_file == tool.config_file.with_name("apps_learned.json")
    assert json.loads(tool.learned_file.read_text(encoding="utf-8")) == {
        "excel": "explorer.exe shell:AppsFolder\Microsoft.Office.EXCEL.EXE.15"
    }


def test_lo_aprendido_se_usa_sin_volver_al_menu_inicio(tool):
    tool.start_menu["excel"] = {"appid": "Excel.App"}
    tool.open_app("excel")
    tool.start_menu.clear()

    tool.open_app("Excel")

    assert tool.launched == ["explorer.exe shell:AppsFolder\Excel.App"] * 2


def test_apps_json_gana_a_lo_aprendido(tool):
    tool.learned_file.write_text(json.dumps({"chrome": "otro.exe", "visio": "visio.exe"}), encoding="utf-8")

    tool.open_app("chrome")
    tool.open_app("visio")

    assert tool.launched == ["chrome", "visio.exe"]


def test_apps_learned_roto_o_ausente(tool):
    assert tool.load_learned() == {}
    tool.learned_file.write_text("{ no es json", encoding="utf-8")

    assert tool.load_learned() == {}
    assert tool.open_app("crome") == "Abriendo crome."


def test_apps_learned_en_gitignore():
    from core.paths import PROJECT_ROOT

    assert "config/apps_learned.json" in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
