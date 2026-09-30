import re


def clean_text(text: str) -> str:
    if text is None:
        return ""

    # Elimina espacios en blanco adicionales
    text = re.sub(r'\s+', ' ', text)

    # Elimina signos de puntuación al inicio y final
    text = re.sub(r'^[^\w\s]', '', text)
    text = re.sub(r'[^\w\s]$', '', text)

    # Elimina saltos de línea adicionales
    text = re.sub(r'\n+', '\n', text)

    return text.strip()