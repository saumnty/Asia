"""Imágenes en la terminal, primera parte: @ruta.png y /pegar, con el OCR integrado de Windows."""
import sys

import pytest
from PIL import Image, ImageDraw, ImageFont

import launcher
from config.settings_manager import SettingsManager
from core import ocr
from core.attachments import extract_attachments
from core.session import Session
from test_confidencial import make_brain

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="OCR integrado de Windows")


def text_image(path, lines, size=(900, 200)):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 36) if sys.platform == "win32" else ImageFont.load_default()

    for i, line in enumerate(lines):
        draw.text((20, 30 + 70 * i), line, fill="black", font=font)

    image.save(path)
    return path


@windows_only
def test_lee_el_texto_de_una_captura(tmp_path):
    image = text_image(tmp_path / "error.png", ["Traceback (most recent call last):", "ZeroDivisionError: division by zero"])

    text = ocr.image_text(image)

    assert "Traceback" in text and "ZeroDivisionError" in text and len(text.splitlines()) == 2


@windows_only
def test_una_imagen_sin_texto_lo_dice(tmp_path):
    Image.new("RGB", (300, 200), "white").save(tmp_path / "blanco.png")

    _, attachments, warnings = extract_attachments("mira @blanco.png", tmp_path, 1000)

    assert attachments == [] and "no encontré texto en la imagen" in warnings[0]


def test_la_imagen_entra_como_adjunto_con_su_texto(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "image_text", lambda path: "ZeroDivisionError")
    (tmp_path / "error.png").write_bytes(b"\x89PNG")

    text, attachments, warnings = extract_attachments("qué dice @error.png", tmp_path, 1000)

    assert warnings == [] and attachments[0].content == "ZeroDivisionError"
    assert "leído con OCR" in attachments[0].label and str(tmp_path / "error.png") in text


def test_pegar_guarda_la_imagen_del_portapapeles(tmp_path):
    saved = ocr.pasted_image(lambda: Image.new("RGB", (10, 10), "white"), tmp_path)

    assert saved.parent == tmp_path and saved.suffix == ".png" and Image.open(saved).size == (10, 10)
    assert ocr.pasted_image(lambda: None, tmp_path) is None
    assert ocr.pasted_image(lambda: ["C:/a.png"], tmp_path) is None


@pytest.fixture
def pasting(tmp_path, monkeypatch):
    monkeypatch.setattr(Session, "user_cwd", tmp_path)
    monkeypatch.setattr(ocr, "image_text", lambda path: "ZeroDivisionError: division by zero")

    def paste(image=True):
        path = tmp_path / "pegado.png"
        path.write_bytes(b"\x89PNG")
        monkeypatch.setattr(ocr, "pasted_image", lambda: path if image else None)

    return paste


def test_pegar_adjunta_la_imagen_y_va_al_chat(pasting):
    pasting()

    text, attachments, use_actions, _ = launcher.prepare_message(make_brain(), "/pegar qué dice este error")

    assert text.startswith("qué dice este error ") and "pegado.png" in text
    assert attachments[0].content.startswith("ZeroDivisionError") and use_actions is False


def test_pegar_sin_pregunta_pide_leerla(pasting):
    pasting()

    text, _, _, _ = launcher.prepare_message(make_brain(), "/pegar")

    assert text.startswith(launcher.PASTED_IMAGE_REQUEST)


def test_pegar_sin_imagen_no_manda_nada(pasting, capsys):
    pasting(image=False)

    assert launcher.prepare_message(make_brain(), "/pegar qué dice") is None
    assert "No hay una imagen en el portapapeles" in capsys.readouterr().err


def test_el_texto_de_la_imagen_es_adjunto_y_no_sale(pasting):
    pasting()
    SettingsManager.set_overrides({"default_provider": "gemini"})
    brain = make_brain()
    text, attachments, use_actions, label = launcher.prepare_message(brain, "/pegar qué dice este error")

    launcher.respond(brain, text, attachments=attachments, use_actions=use_actions, text_label=label)

    router = brain.provider_router
    assert router.providers["gemini"].received == []
    assert "ZeroDivisionError" in router.providers["ollama"].received[-1][-1]["content"]
    assert "adjunto" in router.history_labels
