from providers.ollama_provider import OllamaProvider
from memory.memory_manager import MemoryManager
from memory.project_memory import ProjectMemory
from config.settings_manager import SettingsManager
from providers.gemini_provider import GeminiProvider
from core.confidential import (
    Decision,
    OutgoingRequest,
    check,
    describe_chars,
    is_external,
    is_local_mode,
    outgoing_messages,
)
from core.audit import log_external_send
from core.model_selection import StickyModel, model_for, thinks
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

# Mensajes (usuario + asistente) que se conservan del chat con el usuario.
MAX_HISTORY_MESSAGES = 20

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

    def build_memory_context(self):
        data = self.memory.load()

        if not data:
            return "No hay memoria guardada."

        return "\n".join(
            f"- {key}: {value}"
            for key, value in data.items()
        )

    def build_project_context(self):
        project_name = self.settings.get("active_project")

        if not project_name:
            return ""

        summary = self.project_memory.load_project_summary(project_name)

        if not summary:
            return ""

        return summary

    def ask(self, prompt: str, review=False, domain="code") -> str:
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
        request = OutgoingRequest(messages, fragments)
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
        """Conversación con el usuario: incluye memoria, proyecto e historial.

        history_prompt es lo que se guarda en el historial en lugar de prompt
        (p. ej. el mensaje sin el contenido de los archivos adjuntos).

        Procedencia: la memoria y el resumen del proyecto del prompt de
        sistema, cada mensaje del historial con la etiqueta que heredó su
        turno y lo que trae este mensaje (usuario, adjuntos...). Hacia un
        proveedor externo solo va lo exportable de ese contexto de fondo.
        """
        memory_context = self.build_memory_context()
        project_context = self.build_project_context()
        system_prompt = f"""{SYSTEM_PROMPT}

Contexto personal:
{memory_context}

Contexto del proyecto:
{project_context}
"""

        user_message = {"role": "user", "content": prompt}

        messages = [
            {"role": "system", "content": system_prompt},
            *self.history,
            user_message
        ]

        ambient = []

        if self.memory.load():
            ambient.append(Fragment(MEMORIA, memory_context))

        if project_context:
            ambient.append(Fragment(PROYECTO, project_context))

        turn = current_fragments() or [Fragment(DESCONOCIDO, prompt)]
        past = [Fragment(label, m["content"]) for m, label in zip(self.history, self.history_labels)]
        self.last_fragments = ambient + past + turn

        request = self.external_chat_request(messages, turn, memory_context, project_context, user_message)
        model = self.sticky_model.choose(prompt, self.settings)
        options = {"model": model, "think": thinks(self.settings, self.sticky_model.domain)}
        self.last_request = (request, options)

        try:
            answer = self._complete(request, on_chunk=on_chunk, **options)
        except ProviderError as e:
            if on_chunk:
                on_chunk(str(e))

            return str(e)

        if history_prompt is not None:
            user_message = {"role": "user", "content": history_prompt}

        # El turno (pregunta y respuesta) hereda la etiqueta más restrictiva
        # de lo que lo originó: una respuesta sobre un adjunto queda local.
        label = most_restrictive(labels_of(turn) | labels_of(ambient))

        self.history.append(user_message)
        self.history.append({"role": "assistant", "content": answer})
        self.history_labels += [label, label]
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        self.history_labels = self.history_labels[-MAX_HISTORY_MESSAGES:]

        return answer

    def external_chat_request(self, messages, turn, memory_context, project_context, user_message):
        """El chat completo y su versión para fuera, sin el contexto de fondo local."""
        exportable = exportable_labels(self.settings)
        memory_ok = MEMORIA in exportable and self.memory.load()
        omitted = []

        if self.memory.load() and not memory_ok:
            omitted.append("memoria")

        if project_context:
            omitted.append("resumen del proyecto")

        system = SYSTEM_PROMPT + (f"\n\nContexto personal:\n{memory_context}\n" if memory_ok else "")
        history = [m for m, label in zip(self.history, self.history_labels) if label in exportable]
        exported = {label for label in self.history_labels if label in exportable}

        if memory_ok:
            exported.add(MEMORIA)

        if len(history) < len(self.history):
            omitted.append(f"{len(self.history) - len(history)} mensajes del historial")

        external = [{"role": "system", "content": system}, *history, user_message]
        return OutgoingRequest(messages, turn, external, omitted, sorted(exported))

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
            return self._call(name, provider, request.messages, on_chunk=on_chunk, review=review, model=model, think=think)

        decision = check(request, self.settings, authorized)
        authorization = "una vez" if authorized else "exportable"

        if not decision.allowed and self._confirmed_by_flag(name, request, decision):
            decision = check(request, self.settings, authorized=True)
            authorization = "--allow-external"

        if not decision.allowed:
            raise ExternalBlocked(name, decision)

        messages, secrets = redact_messages(outgoing_messages(request.external_messages))
        notice = ""

        if secrets:
            if self.settings.get("external_secret_policy", "redact") == "block":
                raise ExternalBlocked(name, Decision(False, f"contiene secretos ({describe_secrets(secrets)})"))

            notice = f"[Modo confidencial] Redacté antes de enviar a {name}: {describe_secrets(secrets)}.\n\n"

            if on_chunk:
                on_chunk(notice)

        # La bitácora guarda el envío aunque el proveedor falle: el texto ya salió.
        labels = labels_of(request.turn) | set(request.exported_ambient)

        try:
            answer = self._call(name, provider, messages, on_chunk=on_chunk, review=review, model=model, think=think)
        except Exception as e:
            log_external_send(name, model, labels, messages, authorization, len(secrets), ok=False)
            # El error de un proveedor externo no debe mostrar la clave.
            raise RuntimeError(safe_error(e)) from None

        log_external_send(name, model, labels, messages, authorization, len(secrets))
        return notice + answer

    @staticmethod
    def _call(name, provider, messages, **options):
        """provider.complete, con su tiempo anotado si --timing está activo (core/timing.py)."""
        return timed(name, options.get("model"), lambda: provider.complete(messages, **options))

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
                answer = self._call("ollama", local, request.messages, on_chunk=on_chunk, review=review, model=model, think=think)
            else:
                answer = self._call("ollama", local, request.messages, review=review, model=model, think=think)
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
