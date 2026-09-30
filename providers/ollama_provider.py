import ollama


class OllamaProvider:
    def __init__(self, model="qwen2.5-coder:7b"):
        self.model = model
        self.messages = [
            {
                "role": "system",
                "content": (
                    "Eres Jarvis, un asistente local ejecutándose mediante Ollama. "
                    "Tu modelo base es qwen2.5-coder:7b. "
                    "Responde en español, de forma clara y útil. "
                    "No digas que eres Qwen a menos que te pregunten por el modelo base."
                )
            }
        ]

    def ask(self, prompt: str) -> str:
        self.messages.append({
            "role": "user",
            "content": prompt
        })

        response = ollama.chat(
            model=self.model,
            messages=self.messages
        )

        answer = response["message"]["content"]

        self.messages.append({
            "role": "assistant",
            "content": answer
        })

        return answer
    
    def ask_stream(self, prompt: str):
        self.messages.append({
            "role": "user",
            "content": prompt
        })

        stream = ollama.chat(
            model=self.model,
            messages=self.messages,
            stream=True
        )

        full_response = ""

        for chunk in stream:
            content = chunk["message"]["content"]
            print(content, end="", flush=True)
            full_response += content

        print()

        self.messages.append({
            "role": "assistant",
            "content": full_response
        })

        return None