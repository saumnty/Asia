import re

def clean_text(text: str) -> str:
    # Eliminar espacios en blanco al inicio y al final
    text = text.strip()
    
    # Reemplazar múltiples espacios consecutivos por un solo espacio
    text = re.sub(r'\s+', ' ', text)
    
    # Eliminar caracteres especiales no deseados
    text = re.sub(r'[^\w\s]', '', text)
    
    return text