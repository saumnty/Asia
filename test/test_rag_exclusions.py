"""Nada privado, secreto o binario entra al índice, aunque la ruta lo incluya."""
import pytest

from config.settings_manager import SettingsManager
from core import paths
from core.rag.exclusions import MAX_FILE_BYTES, GitIgnore, SourceFilter, is_secret
from core.rag.indexer import ProjectIndexer
from test_rag_index import embeddings  # noqa: F401


def source_filter(root):
    settings = SettingsManager()
    return SourceFilter(root, settings.text_extensions(), settings.ignored_dirs(include_tests=True))


def files_of(root):
    return sorted(p.relative_to(root).as_posix() for p in source_filter(root).files())


def write(root, relative, text="x = 1\n"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "fuente"
    root.mkdir()
    write(root, "main.py")
    return root


@pytest.mark.parametrize(
    "name",
    [".env", ".env.local", "produccion.env", "servidor.key", "cert.pem", "id_rsa", "id_rsa.pub", "id_ed25519",
     "almacen.p12", "credentials.json", "secrets.json", "llave.ppk"],
)
def test_secretos_nunca_entran(source, name):
    write(source, name, "CLAVE=abc\n")
    write(source, f"sub/{name}", "CLAVE=abc\n")

    assert is_secret(source / name)
    assert files_of(source) == ["main.py"]


def test_un_secreto_con_extension_de_texto_tampoco(source):
    # .txt y .json son indexables: el nombre es lo que lo excluye.
    write(source, "id_rsa.txt", "clave\n")
    write(source, "credentials.json", "{}\n")

    assert files_of(source) == ["main.py"]


def test_binarios_aunque_tengan_extension_de_texto(source):
    (source / "datos.py").write_bytes(b"x = 1\0\0\0binario")
    (source / "imagen.png").write_bytes(b"\x89PNG\0")

    assert files_of(source) == ["main.py"]


def test_mas_de_1_mb_no_entra(source):
    write(source, "enorme.py", "x" * (MAX_FILE_BYTES + 1))
    write(source, "justo.py", "x" * MAX_FILE_BYTES)

    assert files_of(source) == ["justo.py", "main.py"]


def test_datos_de_asia_aunque_la_fuente_los_incluya():
    """La fuente es C:\\Asia entera: data/, memory/, logs/ y settings.json se quedan fuera."""
    root = paths.PROJECT_ROOT
    filter_ = source_filter(root)

    assert not filter_.allows(paths.SETTINGS_FILE)
    assert not filter_.allows(paths.MEMORY_FILE)
    assert filter_.skip_folder(paths.DATA_DIR)
    assert filter_.skip_folder(paths.MEMORY_DIR)
    assert filter_.skip_folder(paths.LOGS_DIR)
    assert filter_.allows(root / "launcher.py")


def test_el_codigo_de_asia_no_incluye_nada_privado():
    files = {p.relative_to(paths.PROJECT_ROOT).as_posix() for p in source_filter(paths.PROJECT_ROOT).files()}

    assert "launcher.py" in files and "core/rag/exclusions.py" in files
    assert not any(f.startswith(("data/", "memory/", "logs/", ".venv/")) for f in files)
    assert "config/settings.json" not in files and "config/apps_learned.json" not in files


# --- .gitignore --------------------------------------------------------------------

@pytest.mark.parametrize(
    "rule, ignored, kept",
    [
        ("*.log", ["a.log", "sub/a.log"], ["a.py"]),
        ("/solo_raiz.py", ["solo_raiz.py"], ["sub/solo_raiz.py"]),
        ("build/", ["build/a.py", "sub/build/a.py"], ["build.py"]),
        ("docs/*.md", ["docs/a.md"], ["docs/sub/a.md", "a.md"]),
        ("**/generado.py", ["generado.py", "a/b/generado.py"], ["generados.py"]),
        ("salida/**", ["salida/a/b.py"], ["salida.py"]),
        ("dato?.txt", ["dato1.txt"], ["dato12.txt"]),
    ],
)
def test_reglas_del_gitignore(source, rule, ignored, kept):
    write(source, ".gitignore", f"# comentario\n\n{rule}\n")

    for name in [*ignored, *kept]:
        write(source, name)

    files = files_of(source)
    assert not set(ignored) & set(files)
    assert set(kept) <= set(files)


def test_negacion_reincluye():
    rules = GitIgnore("*.py\n!importante.py\n")

    assert rules.state("a.py", False) is True
    assert rules.state("importante.py", False) is False
    assert rules.state("a.md", False) is None


def test_gitignore_de_una_subcarpeta_solo_vale_ahi(source):
    write(source, "sub/.gitignore", "local.py\n")
    write(source, "sub/local.py")
    write(source, "local.py")

    assert "local.py" in files_of(source) and "sub/local.py" not in files_of(source)


def test_carpetas_ignoradas_no_se_recorren(source, monkeypatch):
    write(source, ".gitignore", "vendor/\n")
    write(source, "vendor/a.py")

    assert source_filter(source).skip_folder(source / "vendor")


# --- De punta a punta --------------------------------------------------------------

def test_nada_de_eso_entra_al_indice(tmp_path, source, embeddings):  # noqa: F811
    write(source, ".gitignore", "ignorado.py\ncarpeta/\n")
    write(source, "ignorado.py", "SECRETO_GITIGNORE\n")
    write(source, "carpeta/a.py", "SECRETO_CARPETA\n")
    write(source, ".env", "SECRETO_ENV\n")
    write(source, "servidor.key", "SECRETO_KEY\n")
    write(source, "enorme.py", "SECRETO_GRANDE" + "x" * MAX_FILE_BYTES)
    (source / "binario.txt").write_bytes(b"SECRETO_BINARIO\0")

    indexer = ProjectIndexer(str(source), "prueba", persist_dir=tmp_path / "indice")
    assert indexer.index_project() == 1

    stored = indexer.store.collection.get(include=["documents", "metadatas"])
    assert [m["relative_path"] for m in stored["metadatas"]] == ["main.py"]
    assert not any("SECRETO" in document for document in stored["documents"])
