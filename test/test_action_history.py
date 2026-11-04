"""El resultado de una acción queda en el historial de la charla, recortado y con su etiqueta."""
from core.provenance import RAG, USUARIO, Fragment, record
from providers.provider_router import ACTION_RESULT_CHARS
from test_confidencial import make_brain


class SearchIntent:
    def detect(self, text, model=None):
        return {"action": "search_project_rag", "params": {"question": text}}


def brain_with_search(result):
    brain = make_brain()

    def search(text, params):
        brain.last_action = "search_project_rag"
        record(Fragment(RAG, result))
        return result

    brain.handle_search_project_rag = search
    return brain


def test_buscar_queda_en_el_historial_con_la_etiqueta_rag():
    brain = brain_with_search("Líneas verificadas: el pid usa kp = 2.5")

    brain.process("/buscar qué ganancia tiene el pid")

    router = brain.provider_router
    assert router.history == [
        {"role": "user", "content": "/buscar qué ganancia tiene el pid"},
        {"role": "assistant", "content": "Líneas verificadas: el pid usa kp = 2.5"},
    ]
    assert router.history_labels == [RAG, RAG]


def test_la_pregunta_siguiente_lo_recibe():
    brain = brain_with_search("Líneas verificadas: el pid usa kp = 2.5")
    brain.process("/buscar qué ganancia tiene el pid")

    brain.provider_router.chat("¿y eso para qué sirve?")

    sent = brain.provider_router.providers["ollama"].received[-1]
    assert any("kp = 2.5" in m["content"] for m in sent)


def test_un_resultado_largo_se_recorta():
    brain = brain_with_search("palabra " * 1000)

    brain.process("/buscar algo")

    stored = brain.provider_router.history[-1]["content"]
    assert len(stored) <= ACTION_RESULT_CHARS + 30 and stored.endswith("… [resultado recortado]")


def test_charla_y_comandos_de_sesion_no_se_duplican():
    brain = make_brain()

    assert brain.process("hola") is None
    brain.process("/tiempos")

    assert brain.provider_router.history == []


def test_un_resultado_local_no_sale_hacia_un_proveedor_externo():
    from config.settings_manager import SettingsManager

    brain = brain_with_search("SECRETO_DEL_PROYECTO")
    brain.process("/buscar algo")
    SettingsManager.set_overrides({"default_provider": "gemini"})
    brain.provider_router.settings = SettingsManager()

    from core.provenance import request_sources

    with request_sources(Fragment(USUARIO, "¿y eso?")):
        brain.provider_router.chat("¿y eso?")

    sent = "\n".join(m["content"] for msgs in brain.provider_router.providers["gemini"].received for m in msgs)
    assert "¿y eso?" in sent and "SECRETO_DEL_PROYECTO" not in sent
