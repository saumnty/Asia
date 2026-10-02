import sys

import ollama

from config.settings_manager import SettingsManager


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


class OllamaProvider:
    def __init__(self):
        self.settings = SettingsManager()
        self.client = ollama.Client(host=self.settings.get("ollama_host"))

    def complete(self, messages: list[dict], on_chunk=None) -> str:
        """Envía los mensajes y devuelve la respuesta completa.

        Si se pasa on_chunk, la respuesta se transmite en streaming y cada
        fragmento se entrega a on_chunk a medida que llega.
        """
        # Se lee en cada llamada para que un cambio en settings.json se
        # aplique sin reiniciar Asia.
        model = self.settings.get("ollama_model")
        options = ollama_options(self.settings, messages)

        if on_chunk is None:
            response = self.client.chat(
                model=model,
                messages=messages,
                options=options
            )

            return response["message"]["content"]

        stream = self.client.chat(
            model=model,
            messages=messages,
            stream=True,
            options=options
        )

        full_response = ""

        for chunk in stream:
            content = chunk["message"]["content"]
            on_chunk(content)
            full_response += content

        return full_response
