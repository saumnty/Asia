import io

import pytest

from core.attachments import (
    STDIN_LABEL,
    build_chat_prompt,
    decode,
    extract_attachments,
    file_attachments,
    history_prompt,
    make_attachment,
    read_stdin,
    truncation_warnings,
)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hola')\n", encoding="utf-8")
    (tmp_path / "con espacios").mkdir()
    (tmp_path / "con espacios" / "notas.txt").write_text("ñandú", encoding="utf-8")
    return tmp_path


def test_ruta_relativa_se_resuelve_contra_la_carpeta_del_usuario(project):
    text, attachments, warnings = extract_attachments("explica @src/app.py", project, 1000)

    app = (project / "src" / "app.py").resolve()
    assert text == f"explica {app}"
    assert [a.path for a in attachments] == [app]
    assert attachments[0].content == "print('hola')\n"
    assert warnings == []


def test_ruta_absoluta_y_ruta_con_espacios_entre_comillas(project):
    notes = (project / "con espacios" / "notas.txt").resolve()
    message = f'compara @{project / "src" / "app.py"} con @"con espacios/notas.txt"'

    text, attachments, _ = extract_attachments(message, project, 1000)

    assert [a.content for a in attachments] == ["print('hola')\n", "ñandú"]
    assert text.endswith(f'con "{notes}"')


def test_puntuacion_pegada_a_la_ruta(project):
    text, attachments, _ = extract_attachments("¿qué hace @src/app.py?", project, 1000)

    assert len(attachments) == 1
    assert text.endswith("app.py?")


def test_correo_no_es_adjunto(project):
    text, attachments, warnings = extract_attachments("escribe a ana@correo.com", project, 1000)

    assert text == "escribe a ana@correo.com"
    assert attachments == [] and warnings == []


def test_archivo_inexistente_queda_igual_con_aviso(project):
    text, attachments, warnings = extract_attachments("explica @no_existe.py", project, 1000)

    assert text == "explica @no_existe.py"
    assert attachments == []
    assert warnings == ["No encontré el archivo adjunto: no_existe.py"]


def test_mismo_archivo_dos_veces_se_adjunta_una(project):
    _, attachments, _ = extract_attachments("@src/app.py y @src\\app.py", project, 1000)

    assert len(attachments) == 1


@pytest.mark.parametrize(
    "name, data, expected",
    [
        ("carpeta", None, "es una carpeta"),
        ("foto.png", b"\x89PNG", "es una imagen"),
        ("prog.exe", b"MZ\x00\x00binario", "parece un archivo binario"),
    ],
)
def test_no_se_adjuntan_carpetas_imagenes_ni_binarios(tmp_path, name, data, expected):
    target = tmp_path / name

    if data is None:
        target.mkdir()
    else:
        target.write_bytes(data)

    _, attachments, warnings = extract_attachments(f"mira @{name}", tmp_path, 1000)

    assert attachments == []
    assert expected in warnings[0]


def test_recorte_con_aviso(tmp_path):
    (tmp_path / "largo.txt").write_text("x" * 50, encoding="utf-8")

    _, attachments, _ = extract_attachments("@largo.txt", tmp_path, 10)

    assert attachments[0].content == "x" * 10
    assert attachments[0].truncated
    assert truncation_warnings(attachments) == [
        f"[Aviso] {attachments[0].label}: se adjuntaron 10 de 50 caracteres "
        "(attachment_max_chars en config)."
    ]


def test_decode_utf8_con_bom_y_cp1252():
    assert decode("ñandú".encode("utf-8-sig")) == "ñandú"
    assert decode("año".encode("cp1252")) == "año"


def test_decode_normaliza_saltos_de_linea():
    assert decode(b"a\r\nb\rc\n") == "a\nb\nc\n"


def test_file_attachments(project):
    attachments, warnings = file_attachments(["src/app.py", "falta.py"], project, 1000)

    assert [a.content for a in attachments] == ["print('hola')\n"]
    assert warnings == ["No encontré el archivo adjunto: falta.py"]


def test_prompt_de_chat_e_historial():
    attachments = [make_attachment("a.py", "x = 1", 1000), make_attachment(STDIN_LABEL, "abc", 2)]

    prompt = build_chat_prompt("explica", attachments)

    assert prompt.startswith("explica\n\nArchivos adjuntos:\n--- a.py ---\nx = 1\n--- fin de a.py ---")
    assert f"--- {STDIN_LABEL} (recortado) ---\nab\n" in prompt

    history = history_prompt("explica", attachments)

    assert "x = 1" not in history
    assert history == (
        "explica\n\n[Adjuntos no incluidos en el historial: "
        f"a.py (5 caracteres), {STDIN_LABEL} (3 caracteres)]"
    )
    assert build_chat_prompt("hola", []) == history_prompt("hola", []) == "hola"


class FakeStdin:
    def __init__(self, data, tty=False):
        self.buffer = io.BytesIO(data)
        self.tty = tty

    def isatty(self):
        return self.tty


def test_read_stdin():
    assert read_stdin(FakeStdin(b"contenido")) == b"contenido"
    assert read_stdin(FakeStdin(b"contenido", tty=True)) is None


from core.attachments import MissingAttachment, suggest_paths


@pytest.fixture
def practice(tmp_path):
    for name in ["moda.py", "modelo.txt", "eliminar.py", "vote.arff", ".oculto.py"]:
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("", encoding="utf-8")
    (tmp_path / "mis notas").mkdir()
    return tmp_path


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("mod", ["moda.py", "modelo.txt"]),
        ("MOD", ["moda.py", "modelo.txt"]),
        ("moda.pi", ["moda.py"]),
        ("elimnar.py", ["eliminar.py"]),
        ("src/ap.py", ["src/app.py"]),
        (r"src\ap", ["src/app.py"]),
        ("mis", ["mis notas/"]),
        ("zzz.py", []),
        ("no_existe/x.py", []),
    ],
)
def test_suggest_paths(practice, raw, expected):
    assert suggest_paths(raw, practice) == expected


def test_suggest_paths_no_sugiere_ocultos(practice):
    assert suggest_paths(".ocul", practice) == []
    assert ".oculto.py" not in suggest_paths("", practice)


def test_aviso_de_adjunto_faltante_con_sugerencias(practice):
    _, attachments, warnings = extract_attachments("explica @mod y @mis", practice, 1000)

    assert attachments == []
    assert all(isinstance(w, MissingAttachment) for w in warnings)
    assert warnings == [
        "No encontré el archivo adjunto: mod\n  ¿Quisiste decir @moda.py, @modelo.txt?",
        'No encontré el archivo adjunto: mis\n  ¿Quisiste decir @"mis notas/"?',
    ]


def test_otros_avisos_no_son_adjunto_faltante(practice):
    _, _, warnings = extract_attachments("mira @src", practice, 1000)

    assert warnings and not isinstance(warnings[0], MissingAttachment)
