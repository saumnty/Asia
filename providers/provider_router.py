import re

from providers.ollama_provider import RESPONSE_RESERVE_TOKENS, OllamaProvider, estimate_tokens, model_options
from core.actions.models import command_text
from memory.memory_manager import MemoryManager
from memory.project_memory import ProjectMemory, age_notice
from config.settings_manager import SettingsManager
from providers.gemini_provider import GeminiProvider
from core.confidential import (
    Decision,
    OutgoingRequest,
    check,
    describe_chars,
    is_external,
    is_local_mode,
    is_open_mode,
    outgoing_messages,
)
from core.audit import log_external_send
from core.chat_memory import asks_about_conversation, conversation_note, memory_note, relevant_memory
from core.model_selection import StickyModel, model_for, thinks
from core.interruptible import call as interruptible_call
from core.timing import timed
from core.secrets_filter import describe as describe_secrets, redact_messages, safe_error
from core.provenance import (
    DESCONOCIDO,
    MEMORIA,
    NEVER_EXPORT,
    PROYECTO,
    Fragment,
    current_fragments,
    exportable_labels,
    labels_of,
    most_restrictive,
)


SYSTEM_PROMPT = (
    "Eres Asia, un asistente local. "
    "Responde en español, de forma clara y útil."
)

# Solo en el chat (las acciones llevan sus propias instrucciones). Es texto
# fijo: el principio del prompt no cambia entre mensajes y Ollama lo
# reutiliza de su caché; el detalle pedido solo cambia el tope de tokens.
CHAT_RULES = (
    "Responde en 2 a 5 frases, salvo que el usuario pida más detalle (a fondo, con detalle, "
    "ejemplos, paso a paso): entonces extiéndete lo necesario.\n"
    "No inventes datos concretos: cifras, fechas, nombres propios ni citas. Si no estás seguro de "
    'uno, dilo ("no estoy seguro") en lugar de rellenar. Explicar un tema a fondo o poner un '
    "ejemplo ilustrativo no es inventar: hazlo cuando te lo pidan.\n"
    "Solo si te preguntan por un resultado, un campeón, unas elecciones o una noticia concreta que puede "
    "ser posterior a tu entrenamiento, di que no lo sabes en vez de adivinarlo. Explicar un concepto "
    "nunca depende de eso."
)

BRIEF_REMINDER = "\n\n(Responde en 2 a 5 frases.)"

# En modo voz la respuesta se escucha: más corta, y sin listas. Con "2 a 5
# frases" el 7B contestaba "sobre el blog de notas" con una lista de 5
# puntos de varias frases cada uno (284 tokens, 85 s de audio): contaba cada
# punto como una frase. CHAT_RULES no cambia (el prompt de sistema sigue en caché).
VOICE_REMINDER = "\n\n(Responde en 1 a 3 frases, en un solo párrafo, sin listas: se va a leer en voz alta.)"

# Los mismos que answer_limits.chat en config/defaults.json, por si falta la clave.
DEFAULT_CHAT_LIMITS = {"tokens": 350, "detail_tokens": 1500, "voice_tokens": 150}

DETAIL_REQUEST = re.compile(
    r"\b(a fondo|en detalle|con detalle|detallad[oa]s?|detalladamente|dame (unos |algunos )?ejemplos"
    r"|con ejemplos|ejemplos de|paso a paso|explica(me)? (todo|bien|completo)|completo|extens[oa]"
    r"|mas largo|mas detalle|profundidad|exhaustiv[oa])\b"
)


def wants_detail(text: str) -> bool:
    """El usuario pide una respuesta larga ("explica a fondo", "dame ejemplos")."""
    return bool(DETAIL_REQUEST.search(command_text(text)))


# "¿Quieres que te lo explique a fondo?" en la respuesta anterior: un "sí" pide el detalle.
DETAIL_OFFER = re.compile(
    r"\b(a fondo|en detalle|con (mas )?detalle|mas detalle|profundizar|ampliar|ejemplos|paso a paso"
    r"|quieres que te (lo )?explique|explicarte)\b"
)


def accepts_detail(text: str, history: list) -> bool:
    """text es un "sí" a una oferta de explicar más de la última respuesta."""
    from core.recent_facts import is_affirmative

    last = next((m["content"] for m in reversed(history) if m["role"] == "assistant"), "")
    return is_affirmative(text) and bool(DETAIL_OFFER.search(command_text(last)))


# Mensajes (usuario + asistente) que se conservan del chat con el usuario.
MAX_HISTORY_MESSAGES = 20

# Lo que queda en el historial del resultado de una acción (Brain.process).
ACTION_RESULT_CHARS = 1500

# Proveedor al que va una autorización de una sola vez ("envía esto a Gemini").
AUTHORIZED_PROVIDER = "gemini"


class ProviderError(Exception):
    pass


class ExternalBlocked(ProviderError):
    """Un envío externo que la política del modo confidencial no permite."""

    def __init__(self, provider, decision):
        self.provider = provider
        self.decision = decision
        super().__init__(f"No envié esto a {provider}: {decision.reason}.")


class ProviderRouter:
    # Los providers se crean al primer uso: así un provider mal configurado
    # (p. ej. Gemini sin API key) no impide arrancar Asia con otro.
    provider_factories = {
        "ollama": OllamaProvider,
        "gemini": GeminiProvider
    }

    def __init__(self):
        self.settings = SettingsManager()
        self.memory = MemoryManager()
        self.project_memory = ProjectMemory()
        self.providers = {}
        self.history = []
        # Etiqueta de procedencia de cada mensaje de history (core/provenance.py).
        self.history_labels = []
        self.last_fragments = None
        # Último prompt y autorización de una sola vez (no se guardan en disco).
        self.last_request = None
        self.pending_authorization = None
        # --allow-external: confirm(resumen) -> True, False o "all" (el launcher lo pone).
        self.confirm = None
        self.allow_all_this_run = False
        # Modelo del chat: se mantiene mientras siga la conversación.
        self.sticky_model = StickyModel()

    def get_provider(self, name: str):
        if name not in self.providers:
            factory = self.provider_factories.get(name)

            if not factory:
                raise ProviderError(f"Proveedor no disponible: {name}")

            self.providers[name] = factory()

        return self.providers[name]

    def build_project_context(self):
        project_name = self.settings.get("active_project")

        if not project_name:
            return ""

        summary = self.project_memory.load_project_summary(project_name)

        if not summary:
            return ""

        # Con su fecha, para que el modelo no lo tome por el estado actual.
        dated = getattr(self.project_memory, "summary_date", None)
        notice = age_notice(dated(project_name)) if dated else ""
        return f"({notice})\n{summary}" if notice else summary

    def ask(self, prompt: str, review=False, domain="code", max_tokens=None) -> str:
        """Llamada de un solo turno, sin historial de chat ni contexto personal.

        La usan las acciones internas (resúmenes, revisiones, generación de
        código), que ya incluyen en el prompt todo el contexto que necesitan.
        review=True para las revisiones de código: usan temperatura baja y
        penalización de repetición (ver ollama_provider.review_options).
        domain elige el modelo en models_by_domain: las acciones internas son
        de código.
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        # Lo que leyeron las acciones (archivos, RAG, proyecto) está anotado
        # en la petición en curso; sin registro, todo cuenta como local.
        fragments = current_fragments() or [Fragment(DESCONOCIDO, prompt)]
        self.last_fragments = fragments
        request = OutgoingRequest(messages, fragments, max_tokens=max_tokens)
        options = {
            "review": review,
            "model": model_for(self.settings, domain),
            "think": thinks(self.settings, domain),
        }
        self.last_request = (request, options)

        try:
            return self._complete(request, **options)
        except ProviderError as e:
            return str(e)

    def chat(self, prompt: str, on_chunk=None, history_prompt=None) -> str:
        """Conversación con el usuario: incluye proyecto, historial y la memoria que venga al caso.

        history_prompt es lo que se guarda en el historial en lugar de prompt
        (p. ej. el mensaje sin el contenido de los archivos adjuntos).

        La memoria personal no va en el prompt de sistema (core/chat_memory.py):
        solo las entradas relevantes, delante del mensaje y en tercera
        persona. Así el prompt de sistema no cambia entre mensajes y Ollama
        lo reutiliza de su caché.

        Procedencia: el resumen del proyecto, la memoria incluida, cada
        mensaje del historial que cabe con la etiqueta que heredó su turno y
        lo que trae este mensaje (usuario, adjuntos...). Hacia un proveedor
        externo solo va lo exportable de ese contexto de fondo.
        """
        typed = history_prompt or prompt
        note = memory_note(relevant_memory(typed, self.memory.load()))
        project_context = self.build_project_context()
        system_prompt = f"""{SYSTEM_PROMPT}

{CHAT_RULES}

Contexto del proyecto:
{project_context}
"""

        model = self.sticky_model.choose(prompt, self.settings)
        options = {"model": model, "think": thinks(self.settings, self.sticky_model.domain)}
        max_tokens = self.chat_max_tokens(typed, options["think"])

        # Con la regla solo en el prompt de sistema, el 7B la ignoraba (350
        # tokens ante "qué es un grafo bipartito"): se recuerda al final del
        # mensaje. No se guarda en el historial.
        reminder = ""

        if max_tokens and not self.detail_requested(typed):
            reminder = VOICE_REMINDER if self.voice_mode() else BRIEF_REMINDER

        plain_message = {"role": "user", "content": prompt + reminder}
        user_message = plain_message

        if note:
            user_message = {"role": "user", "content": f"{note}\n\nMensaje del usuario:\n{prompt}{reminder}"}

        system = {"role": "system", "content": system_prompt}
        kept, options["model"] = self.fit_history(system, user_message, max_tokens, model)
        history = self.history[len(self.history) - kept:]
        history_labels = self.history_labels[len(self.history_labels) - kept:]

        # "¿De qué tema empezamos?": el historial llegaba entero y qwen3 contestaba
        # con el último tema. Se le recuerdan los mensajes del usuario en orden.
        # Solo hacia el modelo local: el historial que sale fuera va filtrado.
        local_message = user_message
        recap = conversation_note(history) if asks_about_conversation(typed) else ""

        if recap:
            local_message = {"role": "user", "content": f"{recap}\n\n{user_message['content']}"}

        messages = [system, *history, local_message]

        ambient = []

        if note:
            ambient.append(Fragment(MEMORIA, note))

        if project_context:
            ambient.append(Fragment(PROYECTO, project_context))

        turn = current_fragments() or [Fragment(DESCONOCIDO, prompt)]
        past = [Fragment(label, m["content"]) for m, label in zip(history, history_labels)]
        self.last_fragments = ambient + past + turn

        request = self.external_chat_request(
            messages, turn, note, project_context, user_message, plain_message, history, history_labels
        )
        request.max_tokens = max_tokens
        self.last_request = (request, options)

        try:
            answer = self._complete(request, on_chunk=on_chunk, **options)
        except ProviderError as e:
            if on_chunk:
                on_chunk(str(e))

            return str(e)

        user_message = {"role": "user", "content": prompt if history_prompt is None else history_prompt}

        # El turno (pregunta y respuesta) hereda la etiqueta más restrictiva
        # de lo que lo originó: una respuesta sobre un adjunto queda local.
        label = most_restrictive(labels_of(turn) | labels_of(ambient))

        self.history.append(user_message)
        self.history.append({"role": "assistant", "content": answer})
        self.history_labels += [label, label]
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        self.history_labels = self.history_labels[-MAX_HISTORY_MESSAGES:]

        return answer

    def remember_action(self, text, answer, fragments):
        """Guarda una acción y su resultado (recortado) en el historial de la charla.

        El turno lleva la etiqueta más restrictiva de lo que leyó la acción
        (un /buscar en el proyecto queda como rag): hacia fuera solo sale si es
        exportable, como cualquier otro turno.
        """
        result = " ".join(answer.split()) if len(answer) > ACTION_RESULT_CHARS else answer.strip()

        if len(result) > ACTION_RESULT_CHARS:
            result = f"{result[:ACTION_RESULT_CHARS]}… [resultado recortado]"

        label = most_restrictive(labels_of(fragments or [Fragment(DESCONOCIDO, text)]))
        self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": result}]
        self.history_labels += [label, label]
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        self.history_labels = self.history_labels[-MAX_HISTORY_MESSAGES:]

    def fit_history(self, system, user_message, max_tokens, model):
        """(cuántos mensajes del historial caben, modelo) dentro del num_ctx del modelo.

        Se descartan los turnos más antiguos. Si ni sin historial cabe (un
        modelo de 4096 con un mensaje largo), esa respuesta va con
        ollama_model, si tiene una ventana más grande.
        """
        fixed = estimate_tokens([system, user_message]) + (max_tokens or RESPONSE_RESERVE_TOKENS)
        num_ctx = model_options(self.settings, model)["num_ctx"]
        default = self.settings.get("ollama_model")

        if not num_ctx:
            return len(self.history), model

        if fixed > num_ctx and model != default and (model_options(self.settings, default)["num_ctx"] or 0) > num_ctx:
            model, num_ctx = default, model_options(self.settings, default)["num_ctx"]

        kept = 0

        # De a turnos (pregunta y respuesta), del más reciente al más antiguo.
        while kept + 2 <= len(self.history) and fixed + estimate_tokens(self.history[len(self.history) - kept - 2:]) <= num_ctx:
            kept += 2

        return kept, model

    def chat_max_tokens(self, text, think):
        """Tope de la respuesta del chat (answer_limits.chat): más alto si se pide detalle
        y más bajo en modo voz (voice_tokens).

        Con razonamiento (math con qwen3) no hay tope: num_predict cuenta
        también los tokens del razonamiento y lo cortaría.
        """
        if think:
            return None

        limits = {**DEFAULT_CHAT_LIMITS, **((self.settings.get("answer_limits") or {}).get("chat") or {})}

        if self.detail_requested(text):
            return limits["detail_tokens"]

        return limits["voice_tokens"] if self.voice_mode() else limits["tokens"]

    def detail_requested(self, text):
        """"a fondo", "dame ejemplos"... o un "sí" a "¿quieres que te lo explique a fondo?"."""
        return wants_detail(text) or accepts_detail(text, getattr(self, "history", []))

    def voice_mode(self):
        """"/voz" o --voz: la respuesta se lee en voz alta."""
        from core.actions.voice import VOICE_SETTING

        return bool(self.settings.get(VOICE_SETTING))

    def external_chat_request(self, messages, turn, note, project_context, user_message, plain_message,
                              history, history_labels):
        """El chat completo y su versión para fuera, sin el contexto de fondo local.

        Sin permiso para la memoria, afuera va el mensaje sin la nota de memoria.
        """
        exportable = exportable_labels(self.settings)
        memory_ok = MEMORIA in exportable and bool(note)
        omitted = []

        if note and not memory_ok:
            omitted.append("memoria")

        if project_context:
            omitted.append("resumen del proyecto")

        system = f"{SYSTEM_PROMPT}\n\n{CHAT_RULES}"
        exportable_history = [m for m, label in zip(history, history_labels) if label in exportable]
        exported = {label for label in history_labels if label in exportable}

        if memory_ok:
            exported.add(MEMORIA)

        if len(exportable_history) < len(history):
            omitted.append(f"{len(history) - len(exportable_history)} mensajes del historial")

        external = [{"role": "system", "content": system}, *exportable_history, user_message if memory_ok else plain_message]

        # Modo abierto: todo el chat (memoria, proyecto, historial) menos los
        # turnos que nunca salen.
        open_history = [m for m, label in zip(history, history_labels) if label not in NEVER_EXPORT]
        open_labels = {label for label in history_labels if label not in NEVER_EXPORT}

        if note:
            open_labels.add(MEMORIA)

        if project_context:
            open_labels.add(PROYECTO)

        return OutgoingRequest(
            messages, turn, external, omitted, sorted(exported),
            open_messages=[messages[0], *open_history, user_message],
            open_labels=sorted(open_labels),
        )

    # --- Envío con la política del modo confidencial ---------------------------

    def _complete(self, request: OutgoingRequest, on_chunk=None, review=False, model=None, think=False) -> str:
        provider_name = self.settings.get("default_provider", "ollama")

        try:
            return self._send(provider_name, request, on_chunk, review, model, think)
        except ExternalBlocked as blocked:
            return self._answer_locally(blocked, request, on_chunk, review, model, think)
        except ProviderError:
            raise
        except Exception as e:
            return self._fallback(provider_name, e, request, on_chunk, review, model, think)

    def _send(self, name, request, on_chunk=None, review=False, model=None, think=False, authorized=False):
        provider = self.get_provider(name)

        if not is_external(name, self.settings):
            return self._call(name, provider, request.messages, on_chunk=on_chunk, review=review, model=model, think=think, **request.limits())

        decision = check(request, self.settings, authorized)
        open_mode = is_open_mode(self.settings)
        authorization = "modo abierto" if open_mode else "una vez" if authorized else "exportable"

        if not decision.allowed and self._confirmed_by_flag(name, request, decision):
            decision = check(request, self.settings, authorized=True)
            authorization = "--allow-external"

        if not decision.allowed:
            raise ExternalBlocked(name, decision)

        # En modo abierto sale todo, con las rutas; los secretos se filtran igual.
        if open_mode:
            outgoing = request.open_messages
        else:
            outgoing = outgoing_messages(request.external_messages)

        messages, secrets = redact_messages(outgoing)
        notice = ""

        if secrets:
            if self.settings.get("external_secret_policy", "redact") == "block":
                raise ExternalBlocked(name, Decision(False, f"contiene secretos ({describe_secrets(secrets)})"))

            notice = f"[Modo confidencial] Redacté antes de enviar a {name}: {describe_secrets(secrets)}.\n\n"

            if on_chunk:
                on_chunk(notice)

        # La bitácora guarda el envío aunque el proveedor falle: el texto ya salió.
        labels = labels_of(request.turn) | set(request.open_labels if open_mode else request.exported_ambient)

        try:
            answer = self._call(name, provider, messages, on_chunk=on_chunk, review=review, model=model, think=think, **request.limits())
        except Exception as e:
            log_external_send(name, model, labels, messages, authorization, len(secrets), ok=False)
            # El error de un proveedor externo no debe mostrar la clave.
            raise RuntimeError(safe_error(e)) from None

        log_external_send(name, model, labels, messages, authorization, len(secrets))
        return notice + answer

    @staticmethod
    def _call(name, provider, messages, **options):
        """provider.complete, con su tiempo anotado si --timing está activo (core/timing.py).

        En otro hilo, para que Ctrl+C la corte al momento (core/interruptible.py).
        """
        streaming = "on_chunk" in options
        on_chunk = options.pop("on_chunk", None)

        def complete(emit):
            return provider.complete(messages, **options, **({"on_chunk": emit} if streaming else {}))

        cancel = getattr(provider, "cancel", None)
        return timed(name, options.get("model"), lambda: interruptible_call(complete, on_chunk, cancel))

    def _confirmed_by_flag(self, name, request, decision) -> bool:
        """--allow-external: se confirma cada envío (o "todos en esta ejecución")."""
        if not self.settings.get("allow_external") or is_local_mode(self.settings):
            return False

        if labels_of(request.turn) & NEVER_EXPORT:
            return False

        if self.allow_all_this_run:
            return True

        if not self.confirm:
            return False

        answer = self.confirm(self.describe_outgoing(request, name))

        if answer == "all":
            self.allow_all_this_run = True

        return bool(answer)

    def _answer_locally(self, blocked, request, on_chunk, review, model, think):
        """Lo que no pudo salir lo contesta el modelo local, con aviso."""
        notice = f"[Modo confidencial] {blocked}"
        hint = (
            ' Para enviarlo una sola vez: "envía esto a Gemini".'
            if not (is_local_mode(self.settings) or blocked.decision.local & NEVER_EXPORT)
            else ""
        )

        if is_external("ollama", self.settings):
            raise ProviderError(
                f"{notice} No hay un modelo local disponible (ollama_host apunta fuera de "
                f"esta máquina), así que no hay respuesta.{hint}"
            )

        try:
            local = self.get_provider("ollama")

            if on_chunk:
                on_chunk(f"{notice} Respondo con el modelo local (ollama).{hint}\n\n")
                answer = self._call("ollama", local, request.messages, on_chunk=on_chunk, review=review, model=model, think=think, **request.limits())
            else:
                answer = self._call("ollama", local, request.messages, review=review, model=model, think=think, **request.limits())
        except Exception as e:
            raise ProviderError(
                f"{notice} El modelo local (ollama) tampoco respondió: {e}. "
                f"No se envió a ningún proveedor externo.{hint}"
            ) from e

        return f"{notice} Respondo con el modelo local (ollama).{hint}\n\n{answer}"

    def _fallback(self, provider_name, error, request, on_chunk, review, model, think):
        fallback_name = self.settings.get("fallback_provider", None)

        if not fallback_name or fallback_name == provider_name:
            raise ProviderError(
                f"Error usando provider {provider_name}: {safe_error(error)}"
            ) from error

        try:
            response = self._send(fallback_name, request, review=review, model=model, think=think)
        except ExternalBlocked as blocked:
            # El fallback automático nunca se lleva contenido local.
            raise ProviderError(
                f"Falló {provider_name} ({safe_error(error)}) y no usé el fallback {fallback_name}: "
                f"{blocked.decision.reason}. No salió nada de esta máquina."
            ) from error
        except Exception as fallback_error:
            raise ProviderError(
                "Falló el provider principal y también el fallback. "
                f"Error: {safe_error(fallback_error)}"
            ) from fallback_error

        response = f"[Fallback: usando {fallback_name}]\n\n{response}"

        if on_chunk:
            on_chunk(response)

        return response

    # --- Autorización de una sola vez -------------------------------------------

    def describe_outgoing(self, request, provider) -> str:
        messages = outgoing_messages(request.external_messages)
        total = sum(len(m["content"]) for m in messages)
        parts = describe_chars(request.turn) or "nada"
        omitted = f" Se quitan: {', '.join(request.omitted)}." if request.omitted else ""

        return (
            f"Saldría a {provider}: {parts} ({total} caracteres en total, con las rutas "
            f"reemplazadas por el nombre del archivo y los secretos redactados).{omitted}"
        )

    def prepare_authorization(self, provider=AUTHORIZED_PROVIDER) -> str:
        if is_local_mode(self.settings):
            return 'Estás en modo local: no envío nada afuera. Escribe "modo normal" para salir de él.'

        if not self.last_request:
            return "No hay ningún mensaje que enviar."

        request, _ = self.last_request
        never = labels_of(request.turn) & NEVER_EXPORT

        if never:
            return f"No lo envío: lleva contenido {', '.join(sorted(never))}, que nunca sale de esta máquina."

        self.pending_authorization = (self.last_request, provider)

        return (
            f"{self.describe_outgoing(request, provider)}\n"
            'Escribe "confirmar envío" para enviarlo una sola vez o "cancelar envío". '
            "La autorización no se guarda."
        )

    def send_authorized(self) -> str:
        pending, self.pending_authorization = self.pending_authorization, None

        if not pending:
            return 'No hay ningún envío por confirmar. Primero escribe "envía esto a Gemini".'

        (request, options), provider = pending

        try:
            return self._send(provider, request, authorized=True, **options)
        except ProviderError as e:
            return str(e)
        except Exception as e:
            return f"Error usando provider {provider}: {safe_error(e)}"

    def cancel_authorization(self) -> str:
        if not self.pending_authorization:
            return "No hay ningún envío por confirmar."

        self.pending_authorization = None
        return "Envío cancelado. No salió nada."
