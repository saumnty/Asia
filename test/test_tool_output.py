"""Salidas largas de herramientas: el principio al prompt, el resto a data/salidas con retención de 7 días."""
import os
import time

from core import paths
from core.tool_output import RETENTION_DAYS, clip, prune
from test_confidencial import make_brain


def saved_files():
    return sorted(paths.TOOL_OUTPUT_DIR.glob("*.txt"))


def test_lo_que_cabe_queda_igual_y_no_guarda_nada():
    assert clip("corto\n", 100, "x") == "corto\n"
    assert not paths.TOOL_OUTPUT_DIR.exists()


def test_lo_largo_se_recorta_en_lineas_completas_con_aviso():
    text = "\n".join(f"línea {i}" for i in range(100))

    shown = clip(text, 50, "search_text-foo")

    head, notice = shown.rsplit("\n", 1)
    assert head.splitlines() == [f"línea {i}" for i in range(len(head.splitlines()))]
    assert len(head) <= 50
    [saved] = saved_files()
    assert notice == f"[Salida recortada: {len(head.splitlines())} de 100 líneas. Completa en {saved}]"
    assert saved.read_text(encoding="utf-8") == text
    assert saved.name.endswith("-search_text-foo.txt")


def test_el_nombre_del_archivo_no_lleva_caracteres_raros():
    clip("a\n" * 100, 10, "search_text-../../x y")

    [saved] = saved_files()
    assert saved.parent == paths.TOOL_OUTPUT_DIR and "/" not in saved.name and " " not in saved.name


def test_se_borran_las_de_mas_de_7_dias():
    folder = paths.TOOL_OUTPUT_DIR
    folder.mkdir(parents=True)
    old, new = folder / "vieja.txt", folder / "nueva.txt"
    old.write_text("x", encoding="utf-8")
    new.write_text("x", encoding="utf-8")
    eight_days = time.time() - (RETENTION_DAYS + 1) * 86400
    os.utime(old, (eight_days, eight_days))

    prune(folder)

    assert not old.exists() and new.exists()


def test_al_guardar_una_nueva_se_limpian_las_viejas():
    folder = paths.TOOL_OUTPUT_DIR
    folder.mkdir(parents=True)
    old = folder / "vieja.txt"
    old.write_text("x", encoding="utf-8")
    os.utime(old, (0, 0))

    clip("a\n" * 100, 10, "sandbox")

    assert not old.exists() and len(saved_files()) == 1


class Registry:
    def __init__(self, results):
        self.results = results

    def execute(self, action, **kwargs):
        return self.results


class Router:
    def __init__(self):
        self.prompts = []

    def ask(self, prompt, **options):
        self.prompts.append(prompt)
        return "respuesta"


def test_search_text_entra_recortado_al_prompt(monkeypatch):
    brain = make_brain()
    brain.tool_registry = Registry("\n".join(f"core/x.py:{i}: foo()" for i in range(2000)))
    brain.provider_router = Router()
    real = brain.settings.get
    monkeypatch.setattr(brain.settings, "get",
                        lambda key, default=None: {"search_text": 500} if key == "context_limits" else real(key, default))

    brain.handle_find_references("dónde se usa foo", {"query": "foo"})

    [prompt] = brain.provider_router.prompts
    assert "core/x.py:1999" not in prompt and "[Salida recortada: " in prompt
    assert "core/x.py:1999" in saved_files()[0].read_text(encoding="utf-8")
