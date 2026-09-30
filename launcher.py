import sys
import os
from pathlib import Path

USER_CWD = Path.cwd()
PROJECT_ROOT = Path(__file__).resolve().parent

os.chdir(PROJECT_ROOT)

from core.session import Session
from core.brain import Brain
from providers.provider_router import ProviderRouter

Session.set_paths(
    project_root=PROJECT_ROOT,
    user_cwd=USER_CWD,
)


def interactive_mode():
    brain = Brain()
    jarvis = ProviderRouter()

    print("Asia iniciada")

    try:
        while True:
            user = input("\nTú: ")

            if user.lower() in ["salir", "exit", "quit"]:
                print("Asia apagada.")
                break

            brain_response = brain.process(user)

            if brain_response and brain_response != "No entendí esa acción todavía.":
                print("\nAsia:", brain_response)
                continue

            response = jarvis.ask(user)
            print("\nAsia:", response)

    except KeyboardInterrupt:
        print("\nAsia apagada.")


def single_prompt_mode(prompt):
    brain = Brain()
    jarvis = ProviderRouter()

    clean_prompt = prompt.lower().strip()
    
    if clean_prompt in ["revisa este proyecto", "analiza este proyecto"]:
        print(f"Proyecto objetivo detectado: {Session.get_user_cwd()}")
        return

    if clean_prompt in ["cwd", "donde estoy", "carpeta actual"]:
        print(f"Carpeta desde donde llamaste a Jarvis: {Session.get_user_cwd()}")
        return

    brain_response = brain.process(prompt)

    if brain_response and brain_response != "No entendí esa acción todavía.":
        print(brain_response)
        return

    print(jarvis.ask(prompt))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        single_prompt_mode(prompt)
    else:
        interactive_mode()