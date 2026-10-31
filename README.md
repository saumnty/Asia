# Asia

Asistente local en la terminal, con Ollama. El estado del proyecto y lo que falta están en [ROADMAP.md](ROADMAP.md).

## Instalación (Windows)

Hace falta Python 3.11 y [Ollama](https://ollama.com) con los modelos de `config/defaults.json`.

```powershell
cd C:\Asia
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
Copy-Item .\.venv\Scripts\jarvis.exe C:\Tools\jarvis.exe
```

`pip install -e .` genera `.venv\Scripts\jarvis.exe`, y `C:\Tools` ya está en el PATH. El modo editable usa el código de `C:\Asia`: cambiar el código no requiere reinstalar.

Las pruebas necesitan además `requirements-dev.txt`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

## Voz (opcional)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
```

El modelo de Whisper va en `data/models/` y las voces de Piper en `data/voices/`; no están en el repositorio. Si falta el modelo, Asia dice cómo descargarlo. Se activa con `/voz` o `jarvis --voz`.

## Si recreas el .venv

`jarvis.exe` guarda la ruta del Python del `.venv`. Después de recrear el `.venv` o de moverlo de carpeta, repite la instalación y vuelve a copiar el ejecutable:

```powershell
.\.venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
Copy-Item .\.venv\Scripts\jarvis.exe C:\Tools\jarvis.exe -Force
```

## Volver a jarvis.bat

`jarvis.bat` se mantiene por un tiempo como respaldo. `.exe` va antes que `.bat` en Windows, así que basta con quitar el ejecutable:

```powershell
Remove-Item C:\Tools\jarvis.exe
```

`jarvis` vuelve a ser `C:\Tools\jarvis.bat`, que llama a `C:\Asia\jarvis.bat`. Con él vuelve el "¿Desea terminar el trabajo por lotes (S/N)?" al pulsar Ctrl+C.
