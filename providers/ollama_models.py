"""Un solo modelo de Ollama en memoria a la vez (ollama_one_model_at_a_time).

Con 4 GB de VRAM y poca RAM libre, dos modelos cargados hacen que Ollama
reparta capas en la CPU o use swap. Antes de cada llamada se descargan los
demás modelos cargados (keep_alive=0). Cambiar de modelo cuesta una recarga
(segundos con un 7B): por eso el chat mantiene su modelo mientras puede
(ver core/model_selection.py).
"""


def full_name(model: str) -> str:
    """"nomic-embed-text" y "nomic-embed-text:latest" son el mismo modelo."""
    return model if ":" in model else f"{model}:latest"


def unload_others(client, model: str, settings) -> list[str]:
    """Descarga de Ollama los modelos cargados distintos de model.

    Devuelve los que descargó. Si Ollama no responde, no hace nada: la
    llamada siguiente mostrará el error.
    """
    if not settings.get("ollama_one_model_at_a_time", True):
        return []

    try:
        loaded = [m.model for m in client.ps().models]
    except Exception:
        return []

    unloaded = []

    for name in loaded:
        if full_name(name) == full_name(model):
            continue

        try:
            # Una llamada sin prompt y con keep_alive=0 descarga el modelo.
            client.generate(model=name, keep_alive=0)
            unloaded.append(name)
        except Exception:
            pass

    return unloaded
