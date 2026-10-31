import sys

from config.settings_manager import SettingsManager
from core.timing import ollama_metrics
from providers.ollama_models import ThinkFilter, strip_think, think_kwargs, unload_others


# Medido en prompts reales de Asia: entre 3,3 y 4,1 caracteres por token.
# Se usa el valor bajo para que la estimación peque de grande.
CHARS_PER_TOKEN = 3.3

# Espacio que se deja para la respuesta dentro de la ventana de contexto.
RESPONSE_RESERVE_TOKENS = 1024


def estimate_tokens(messages: list[dict]) -> int:
    return int(sum(len(message["content"]) for message in messages) / CHARS_PER_TOKEN)


def ollama_options(settings, messages: list[dict], **extra) -> dict:
    """Opciones de Ollama con la ventana de contexto configurada (ollama_num_ctx).

    Si el prompt más la respuesta no caben, Ollama recorta el principio del
    prompt sin avisar (p. ej. la petición del usuario en generate_code), así
    que se avisa por stderr para que el resultado no se tome como fiable.
    """
    num_ctx = settings.get("ollama_num_ctx")
    estimated = estimate_tokens(messages)

    if estimated + RESPONSE_RESERVE_TOKENS > num_ctx:
        print(
            f"[Aviso] El prompt (~{estimated} tokens estimados) y la respuesta "
            f"no caben en ollama_num_ctx={num_ctx}: Ollama descartará el "
            f"principio del prompt. Sube ollama_num_ctx en config/settings.json.",
            file=sys.stderr
        )

    return {"num_ctx": num_ctx, **extra}


def review_options(settings) -> dict:
    """Opciones para las revisiones de código, no para el chat.

    Temperatura baja para que el modelo no improvise hallazgos y penalización
    de repetición porque qwen2.5-coder:7b repetía el mismo hallazgo varias
    veces.
    """
    return {
        "temperature": settings.get("ollama_temperature"),
        "repeat_penalty": settings.get("ollama_repeat_penalty"),
    }


def cut_notice(response, max_tokens) -> str:
    """Aviso si Ollama cortó la respuesta por el tope (done_reason "length")."""
    if not max_tokens or response is None or response.get("done_reason") != "length":
        return ""

    return f"\n\n[Respuesta recortada en {max_tokens} tokens (answer_limits en config).]"


class OllamaProvider:
    def __init__(self):
        self.settings = SettingsManager()
        self._client = None

    @property
    def client(self):
        """Cliente de Ollama. Se importa al primer uso: la librería tarda ~2 s en cargar."""
        if self._client is None:
            import ollama

            self._client = ollama.Client(host=self.settings.get("ollama_host"))

        return self._client

    @client.setter
    def client(self, client):
        self._client = client

    def complete(self, messages: list[dict], on_chunk=None, review=False, model=None, think=False, max_tokens=None) -> str:
        """Envía los mensajes y devuelve la respuesta completa.

        Si se pasa on_chunk, la respuesta se transmite en streaming y cada
        fragmento se entrega a on_chunk a medida que llega. Con review=True
        se usan las opciones de revisión (review_options). model elige el
        modelo de esta llamada; sin él, ollama_model. think activa el modo
        de razonamiento en los modelos que lo tienen; el razonamiento no se
        devuelve, solo la respuesta. max_tokens limita la longitud de la
        respuesta (num_predict).
        """
        # Se lee en cada llamada para que un cambio en settings.json se
        # aplique sin reiniciar Asia.
        model = model or self.settings.get("ollama_model")
        unload_others(self.client, model, self.settings)
        extra = review_options(self.settings) if review else {}

        # Tope de la respuesta: num_predict no recarga el modelo (num_ctx sí).
        if max_tokens:
            extra["num_predict"] = max_tokens

        options = ollama_options(self.settings, messages, **extra)
        thinking = think_kwargs(self.client, model, think)

        if on_chunk is None:
            response = self.client.chat(
                model=model,
                messages=messages,
                options=options,
                **thinking
            )
            ollama_metrics(response)

            return strip_think(response["message"]["content"]) + cut_notice(response, max_tokens)

        stream = self.client.chat(
            model=model,
            messages=messages,
            stream=True,
            options=options,
            **thinking
        )

        visible = ThinkFilter()
        full_response = ""
        last = None

        for chunk in stream:
            last = chunk
            content = visible.feed(chunk["message"]["content"] or "")

            if content:
                on_chunk(content)
                full_response += content

        # El último fragmento (done) trae las métricas de la respuesta.
        ollama_metrics(last)
        rest = visible.flush()

        rest += cut_notice(last, max_tokens)

        if rest:
            on_chunk(rest)
            full_response += rest

        return full_response
