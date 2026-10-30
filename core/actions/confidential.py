"""Comandos del modo confidencial (fase G), por texto fijo y sin el IntentEngine.

- "envía esto a Gemini": muestra qué tipos de contenido y cuántos
  caracteres saldrían del último mensaje y pide "confirmar envío". La
  autorización vale una vez y no se guarda.
- "modo local": no sale nada de esta máquina (ni la memoria ni lo
  tecleado) hasta "modo normal" o hasta salir de Asia.
- "modo abierto": sale todo lo que entra al prompt sin pedir autorización
  (ver core/confidential.py), hasta "modo normal" o hasta salir de Asia.
- "qué has enviado afuera": resumen de logs/external_audit.jsonl.
"""
from core.actions.models import command_text, set_session
from core.audit import summary as audit_summary
from core.confidential import LOCAL_MODE, NORMAL_MODE, OPEN_MODE, is_open_mode

AUTHORIZE_PHRASES = {
    "envia esto a gemini", "enviar esto a gemini", "manda esto a gemini",
    "mandar esto a gemini", "envialo a gemini",
}
CONFIRM_PHRASES = {"confirmar envio", "confirmo envio", "confirmo el envio", "confirmar el envio"}
CANCEL_PHRASES = {"cancelar envio", "cancela el envio", "cancelar el envio"}
LOCAL_PHRASES = {"modo local", "activa el modo local", "pasa a modo local"}
NORMAL_PHRASES = {
    "modo normal", "sal del modo local", "salir del modo local", "desactiva el modo local",
    "sal del modo abierto", "salir del modo abierto", "desactiva el modo abierto",
}
OPEN_PHRASES = {"modo abierto", "/modo abierto", "activa el modo abierto", "pasa a modo abierto"}

OPEN_MODE_WARNING = (
    "Modo abierto (solo en esta sesión): lo que entra al prompt sale al proveedor externo "
    "sin pedirte autorización: lo que escribes, archivos, adjuntos, RAG, resumen del "
    "proyecto, memoria e historial, con sus rutas completas. Siguen el filtro de secretos "
    "y la bitácora; lo emocional nunca sale. El costo y la latencia suben: los prompts "
    'externos son más largos. "modo normal" lo quita.'
)
AUDIT_PHRASES = {
    "que has enviado afuera", "que enviaste afuera", "que has enviado fuera",
    "que has mandado afuera", "muestra la bitacora de envios", "bitacora de envios",
}


def confidential_command(text: str):
    """Nombre del comando o None."""
    command = command_text(text)

    for name, phrases in (
        ("authorize", AUTHORIZE_PHRASES),
        ("confirm", CONFIRM_PHRASES),
        ("cancel", CANCEL_PHRASES),
        ("local", LOCAL_PHRASES),
        ("normal", NORMAL_PHRASES),
        ("open", OPEN_PHRASES),
        ("audit", AUDIT_PHRASES),
    ):
        if command in phrases:
            return name

    return None


class ConfidentialActions:
    def handle_confidential_command(self, name):
        router = self.provider_router

        if name == "authorize":
            return router.prepare_authorization()

        if name == "confirm":
            return router.send_authorized()

        if name == "cancel":
            return router.cancel_authorization()

        if name == "audit":
            return audit_summary()

        if name == "local":
            set_session(confidential_mode=LOCAL_MODE)
            router.pending_authorization = None
            return (
                "Modo local: no sale nada de esta máquina, ni la memoria ni lo que "
                'escribas, hasta que escribas "modo normal" o salgas de Asia.'
            )

        if name == "open":
            # El aviso sale una vez: al activarlo, no en cada mensaje.
            if is_open_mode(self.settings):
                return 'Ya estás en modo abierto. "modo normal" lo quita.'

            set_session(confidential_mode=OPEN_MODE)
            return OPEN_MODE_WARNING

        # Explícito (no None): con open_mode_default true, "modo normal" también lo quita.
        set_session(confidential_mode=NORMAL_MODE)
        return (
            "Modo normal: lo que escribes puede ir a un proveedor externo si lo usas; "
            "archivos, adjuntos, RAG, proyecto y memoria siguen sin salir sin tu autorización."
        )
