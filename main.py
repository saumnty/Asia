from core.brain import Brain
from providers.provider_router import ProviderRouter


def main():
    brain = Brain()
    jarvis = ProviderRouter()

    print("Asia iniciada")

    while True:
        user = input("\nTú: ")

        if user.lower() in ["salir", "exit", "quit"]:
            print("Asia apagada.")
            break

        brain_response = brain.process(user)

        if brain_response:
            print("\nAsia:", brain_response)
            continue

        response = jarvis.ask(user)
        print("\nAsia:", response)


if __name__ == "__main__":
    main()