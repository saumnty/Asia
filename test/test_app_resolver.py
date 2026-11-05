import hashlib
import json
from types import SimpleNamespace

import pytest

import tools.app_resolver as app_tool_resolver
import tools.app_tool as app_tool
from core.paths import APPS_FILE
from tools.app_resolver import clarification, close_app, is_alias, normalize, resolve_known_app, suggestions
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


SHOWN = {"notepad": "bloc de notas", "calc": "calculadora", "chrome": "chrome", "code": "vscode",
         APPS["spotify"]: "spotify", APPS["whatsapp"]: "whatsapp"}


@pytest.mark.parametrize(
    "name, command",
    [
        # Lo que devolvió qwen3:4b-instruct para "abre el bloc de notas".
        ("notebook", "notepad"),
        ("blocknote", "notepad"),
        ("Bloc de Notas", "notepad"),
        ("notepad", "notepad"),
        ("calculator", "calc"),
        ("google", "chrome"),
        ("editor", "code"),
    ],
)
def test_exacta_o_variante_conocida_abre_y_dice_el_nombre(tool, name, command):
    # "Abriendo notepad." no decía qué app es: se dice el primer nombre de apps.json para ese comando.
    assert tool.open_app(name) == f"Abriendo {SHOWN[command]}."
    assert tool.launched == [command]


@pytest.mark.parametrize(
    "name, command",
    [
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
def test_un_nombre_parecido_pregunta_antes_de_abrir(tool, name, command):
    assert tool.open_app(name) == f"¿Abro {SHOWN[command]}? s/N"
    assert tool.launched == []

    assert tool.open_pending(tool.take_pending()) == f"Abriendo {SHOWN[command]}."
    assert tool.launched == [command] and tool.take_pending() is None


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
    assert tool.open_app("chrome") == "Abriendo chrome."


# --- Menú Inicio: exacto o solo contenido ("look" en "Outlook") -----------------

OUTLOOK = {"name": "Outlook", "appid": "Microsoft.OutlookForWindows!App"}


def test_contenido_en_el_nombre_del_menu_inicio_pregunta_y_no_aprende(tool):
    # Caso real: "abra el look de notas" -> app_name "look" -> abrió Outlook y aprendió "look".
    tool.start_menu["look"] = OUTLOOK

    assert tool.open_app("look") == "¿Abro Outlook? s/N"
    assert tool.launched == [] and tool.load_learned() == {}

    assert tool.open_pending(tool.take_pending()) == "Abriendo Outlook."
    # Con el sí, se aprende el nombre de la app, no la palabra suelta.
    assert tool.load_learned() == {"outlook": "explorer.exe shell:AppsFolder\\Microsoft.OutlookForWindows!App"}


def test_nombre_exacto_del_menu_inicio_abre_y_aprende(tool):
    tool.start_menu["outlook"] = OUTLOOK

    assert tool.open_app("outlook") == "Abriendo Outlook."
    assert list(tool.load_learned()) == ["outlook"]


def test_find_start_app_prefiere_el_nombre_exacto(monkeypatch):
    menu = [{"Name": "WordPad", "AppID": "wordpad"}, {"Name": "Word", "AppID": "word"}]
    monkeypatch.setattr(app_tool_resolver, "get_start_apps", lambda: json.dumps(menu))

    assert app_tool_resolver.find_start_app("word")["appid"] == "word"
    assert app_tool_resolver.find_start_app("wordp")["appid"] == "wordpad"


# --- La confirmación en el Brain, escrita o dicha ---------------------------------

def brain_with(tool):
    from test_confidencial import make_brain

    brain = make_brain()
    brain.tool_registry = SimpleNamespace(app_tool=tool, execute=lambda action, **params: tool.open_app(**params))
    return brain


@pytest.mark.parametrize("yes", ["s", "sí", "Sí.", "Sí, ábrelo.", "dale"])
def test_con_un_si_abre_lo_que_pregunto(tool, yes):
    tool.start_menu["look"] = OUTLOOK
    brain = brain_with(tool)

    assert brain.process("abre look") == "¿Abro Outlook? s/N"
    # "Sí." es lo que escribe Whisper: con voz se confirma igual.
    assert brain.process(yes) == "Abriendo Outlook."
    assert tool.launched == ["explorer.exe shell:AppsFolder\\Microsoft.OutlookForWindows!App"]


@pytest.mark.parametrize("no", ["n", "no", "No."])
def test_con_un_no_no_abre_nada(tool, no):
    brain = brain_with(tool)

    assert brain.process("abre crome") == "¿Abro chrome? s/N"
    assert brain.process(no) == "Vale, no abro chrome."
    assert tool.launched == []


def test_la_pregunta_vale_solo_para_el_mensaje_siguiente(tool):
    brain = brain_with(tool)

    brain.process("abre crome")
    brain.process("cuéntame un chiste")
    brain.process("sí")

    assert tool.launched == []


def test_apps_learned_en_gitignore():
    from core.paths import PROJECT_ROOT

    assert "config/apps_learned.json" in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


# --- Lo dicho, confirmado, como alias ----------------------------------------------

@pytest.mark.parametrize("said", ["block de notas", "bloc notas"])
def test_un_nombre_casi_igual_confirmado_queda_de_alias(tool, said):
    assert tool.open_app(said) == "¿Abro bloc de notas? s/N"
    tool.open_pending(tool.take_pending())

    assert tool.load_learned() == {said: "notepad"}
    # El mismo error de Whisper otra vez: ya no pregunta.
    assert tool.open_app(said) == "Abriendo bloc de notas."
    assert tool.launched == ["notepad", "notepad"]


def test_una_parte_del_nombre_no_queda_de_alias(tool):
    tool.start_menu["look"] = OUTLOOK

    tool.open_app("look")
    tool.open_pending(tool.take_pending())

    assert "look" not in tool.load_learned()
    # Vuelve a preguntar: "look" no es Outlook.
    assert tool.open_app("look") == "¿Abro Outlook? s/N"


def test_un_nombre_del_menu_inicio_casi_igual_queda_de_alias(tool):
    tool.start_menu["outlok"] = OUTLOOK

    assert tool.open_app("outlok") == "¿Abro Outlook? s/N"
    tool.open_pending(tool.take_pending())

    assert set(tool.load_learned()) == {"outlook", "outlok"}


def test_is_alias():
    assert is_alias("block de notas", "bloc de notas") and is_alias("bloc notas", "bloc de notas")
    assert not is_alias("look", "Outlook") and not is_alias("notas", "bloc de notas")
    assert not is_alias("bloc de notas", "Bloc de Notas") and not is_alias("excel", "bloc de notas")
