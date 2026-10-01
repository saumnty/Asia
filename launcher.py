import sys
from pathlib import Path

# No se cambia de carpeta: los datos internos de Asia usan rutas absolutas
# (core/paths.py) y las rutas que da el usuario se resuelven contra la
# carpeta desde la que llamó a Asia.
from core.paths import PROJECT_ROOT
from core.session import Session
from core.brain import Brain

Session.set_paths(
    project_root=PROJECT_ROOT,
    user_cwd=Path.cwd(),
)

EXIT_COMMANDS = {"salir", "exit", "quit"}


def respond(brain, text, prefix=""):
    """Procesa un mensaje e imprime la respuesta.

    Si Brain no reconoce una acción (devuelve None), el mensaje se trata
    como conversación normal con el provider.
    """
    print(prefix, end="", flush=True)

    try:
        response = brain.process(text)

        if response is not None:
            print(response)
            return

        if brain.settings.get("stream_output", False):
            brain.provider_router.chat(
                text,
                on_chunk=lambda chunk: print(chunk, end="", flush=True)
            )
            print()
            return

        print(brain.provider_router.chat(text))
    except Exception as e:
        print(f"Error inesperado: {e}")


def interactive_mode():
    brain = Brain()

    print("Asia iniciada")

    try:
        while True:
            user = input("\nTú: ")

            if user.lower().strip() in EXIT_COMMANDS:
                print("Asia apagada.")
                break

            respond(brain, user, prefix="\nAsia: ")

    except (KeyboardInterrupt, EOFError):
        print("\nAsia apagada.")


def single_prompt_mode(prompt):
    clean_prompt = prompt.lower().strip()

    if clean_prompt in ["cwd", "donde estoy", "carpeta actual"]:
        print(f"Carpeta desde donde llamaste a Asia: {Session.get_user_cwd()}")
        return

    respond(Brain(), prompt)


def main():
    if len(sys.argv) > 1:
        single_prompt_mode(" ".join(sys.argv[1:]))
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
