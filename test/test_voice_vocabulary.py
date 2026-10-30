"""Vocabulario de Asia como initial_prompt de Whisper (core/voice/vocabulary.py)."""
import json

from core.voice import DEFAULT_VOICE_SETTINGS
from core.voice.vocabulary import MAX_CHARS, build_prompt, command_phrases, command_verbs, vocabulary_prompt
from core.voice.stt import FasterWhisperSTT
from test_launcher import FakeSettings
from test_voice_input import session, silence, speech


def data(tmp_path, apps=None, learned=None, projects=()):
    apps_file = tmp_path / "apps.json"
    apps_file.write_text(json.dumps(apps or {"bloc de notas": "notepad.exe"}), encoding="utf-8")

    if learned:
        (tmp_path / "apps_learned.json").write_text(json.dumps(learned), encoding="utf-8")

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    for name in projects:
        (projects_dir / f"{name}.md").write_text("resumen", encoding="utf-8")

    return apps_file, projects_dir


def config(**values):
    return {**DEFAULT_VOICE_SETTINGS, **values}


def test_verbos_de_las_ordenes_de_asia():
    verbs = command_verbs(command_phrases())

    for verb in ("abre", "muestra", "explica", "revisa", "resume", "busca", "recuerda", "activa"):
        assert verb in verbs

    # Ni preguntas ni palabras del JSON del prompt; "explícame" cuenta como "explica".
    for word in ("que", "cuál", "action", "params", "explícame", "muéstrame"):
        assert word not in verbs


def test_prompt_con_apps_aprendidas_proyectos_y_lista_extra(tmp_path):
    apps_file, projects_dir = data(tmp_path, learned={"spotify": "spotify.exe"}, projects=["bolitabot"])
    settings = FakeSettings(active_project="asia", project_name="Asia")

    prompt = build_prompt(settings, config(stt_vocabulary=["ROADMAP", "proyecto activo"]), apps_file, projects_dir)

    assert prompt.startswith("Órdenes para Asia: ")
    assert "Apps: spotify, bloc de notas." in prompt
    # "Asia" y "asia" una sola vez.
    assert "Proyectos: asia, bolitabot." in prompt
    assert prompt.endswith("Palabras: ROADMAP, proyecto activo.")


def test_se_puede_desactivar(tmp_path):
    apps_file, projects_dir = data(tmp_path)

    assert build_prompt(FakeSettings(), config(stt_vocabulary_prompt=False), apps_file, projects_dir) == ""


def test_si_no_cabe_se_recortan_los_verbos():
    apps = [f"app{i}" for i in range(20)]

    prompt = vocabulary_prompt([f"verbo{i}" for i in range(200)], apps, ["asia"], ["ROADMAP"])

    assert len(prompt) <= MAX_CHARS
    assert "verbo0" in prompt and "verbo199" not in prompt
    assert ", ".join(apps) in prompt and prompt.endswith("Palabras: ROADMAP.")


def test_la_sesion_pasa_el_vocabulario_a_whisper():
    voice, stt = session(speech(1) + silence(1))

    voice.listen()

    assert stt.prompts == ["Órdenes para Asia: abre."]


def test_faster_whisper_lo_usa_como_initial_prompt():
    calls = []

    class Model:
        def transcribe(self, audio, **options):
            calls.append(options)
            return [], None

    stt = FasterWhisperSTT(config())
    stt.model = Model()

    stt.transcribe([0.0], "Órdenes para Asia: abre.")
    stt.transcribe([0.0])

    assert calls[0]["initial_prompt"] == "Órdenes para Asia: abre."
    assert calls[1]["initial_prompt"] is None
