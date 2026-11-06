# Voz propia: plan del fine-tuning de Piper

Plan para entrenar una voz de Piper con las frases revisadas del dataset propio (mujer, español de México; ~25–40 min de notas de voz, solo uso privado), en Colab gratuito con una T4. Solo investigación: todavía no hay cuaderno. Investigado el 2026-11-05.

## 1. Cómo se entrena hoy

- **Repositorio vigente:** [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl), el sucesor de `rhasspy/piper` (archivado). Paquete `piper-tts` 1.8.0 en PyPI (septiembre de 2026), el mismo que ya usa Asia en el `.venv`; el entrenamiento va en el extra `[train]`. Licencia GPL-3.0, que vale para uso personal.
- **Instalación** ([TRAINING.md](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/TRAINING.md)):
  1. Paquetes del sistema `build-essential`, `cmake` y `ninja-build`.
  2. Clonar el repositorio y crear un entorno virtual.
  3. `pip install -e '.[train]'`, luego `./build_monotonic_align.sh` y `python3 setup.py build_ext --inplace`.
- **Datos (formato LJSpeech):** un `metadata.csv` sin cabecera, `archivo.wav|texto`, y los audios en `--data.audio_dir`. Es lo que arma `test/manual/dataset_final.py`, con el nombre del archivo en la primera columna (`0001.wav|texto`). El texto pasa por espeak-ng: `--data.espeak_voice es-419` para el español de América Latina.
- **Comando** (PyTorch Lightning):
  ```
  python3 -m piper.train fit \
    --data.voice_name "es_MX-propia" \
    --data.csv_path metadata.csv \
    --data.audio_dir wavs/ \
    --model.sample_rate 22050 \
    --data.espeak_voice "es-419" \
    --data.cache_dir cache/ \
    --data.config_path es_MX-propia-medium.onnx.json \
    --data.batch_size 16 \
    --ckpt_path base.ckpt
  ```
- **Desde un checkpoint:**
  - `--ckpt_path` reanuda el contador de épocas y el optimizador del checkpoint.
  - `--model.warmstart_ckpt` copia solo los pesos y empieza en la época 0.
  - Solo los checkpoints **medium** valen sin tocar otros ajustes.
  - Los checkpoints viejos de `rhasspy/piper-checkpoints` traen claves que el entrenamiento nuevo no reconoce, así que no se pueden reanudar. Lo que funciona es usarlos de base, empezando en la época 0 ([discusión #138](https://github.com/OHF-Voice/piper1-gpl/discussions/138)).
- **Exportar:**
  - `python3 -m piper.train.export_onnx --checkpoint <ckpt> --output-file es_MX-propia-medium.onnx`.
  - El JSON de `--data.config_path` se renombra al mismo nombre con `.onnx.json`.
  - Los dos archivos van a `data/voices/` y se eligen con `voice.tts_voice`, sin cambiar código.
- **En Colab gratuito**, según la [discusión #138](https://github.com/OHF-Voice/piper1-gpl/discussions/138):
  - `wget` corrompe las descargas de Hugging Face: el archivo empieza por "<" en vez de "PK". Hay que usar `aria2c`, o subir el checkpoint a Drive desde el navegador.
  - Con PyTorch 2.6 o posterior, cargar un checkpoint falla por `torch.load(weights_only=True)`. Hace falta `weights_only=False` en `piper/train/__main__.py`.
  - La conexión con Drive se cae hacia las 4 h. Hay que guardar los checkpoints cada pocas épocas (`checkpoint_epochs`) y reanudar desde `last.ckpt`.
  - Hay un cuaderno de la comunidad, todavía con arreglos pendientes: [Piper_Training_Notebook de KiON-GiON](https://colab.research.google.com/github/KiON-GiON/piper1-gpl/blob/fixes/notebooks/Piper_Training_Notebook.ipynb). Conviene tomarlo de referencia, no ejecutarlo tal cual.

## 2. Checkpoint de base

En [rhasspy/piper-checkpoints](https://huggingface.co/datasets/rhasspy/piper-checkpoints/tree/main/es) solo hay tres voces en español, y **ninguna es de mujer con acento mexicano**:

| Checkpoint | Acento | Voz | Calidad, frecuencia | Licencia de los datos | Peso del `.ckpt` |
|---|---|---|---|---|---|
| `es/es_MX/ald/medium` | México (espeak `es-419`) | hombre (Aldo), 1,5 h | medium, 22 050 Hz | Unlicense | 845 898 456 B |
| `es/es_ES/sharvard/medium` | España (`es`) | 2 hablantes: M y F | medium, 22 050 Hz | CC BY 3.0 (atribución) | 924 476 424 B |
| `es/es_ES/davefx/medium` | España | hombre | medium, 22 050 Hz | CC0 | 845 898 392 B |

- Hay versiones `x_low` y `high` de algunas voces, pero el entrenamiento nuevo solo admite medium sin cambiar ajustes. La voz `es_MX-claude-high` que usa Asia no publica su checkpoint.
- Los checkpoints de la comunidad en Hugging Face (por ejemplo, los de HirCoir para es_MX) **no traen licencia ni dicen de dónde salen sus datos**, y algunos imitan personajes o personas reales. No los recomiendo.
- **Recomendación: `es_MX/ald/medium`.** El ROADMAP pide que la base coincida en género y acento, y ninguna base disponible cumple las dos cosas. Doy prioridad al acento y a la fonética:
  - comparte el espeak `es-419`, con seseo, y la entonación mexicana;
  - es de un solo hablante y tiene licencia libre;
  - el tono de voz es lo que más cambia en un fine-tuning, así que el género pesa menos que el acento.
- **Plan B, si el resultado suena masculino:** el hablante F de `sharvard/medium`. Es de mujer, pero con acento de España y de un modelo de dos hablantes. Pasar a una voz de un hablante probablemente exige `--model.warmstart_ckpt`, o quedarse con dos hablantes y usar solo la F. No está probado.

## 3. 16 o 22 kHz

Los audios son notas de voz de WhatsApp en opus. Se decodifican a 48 kHz, pero la voz no tiene contenido por encima de unos 8 kHz (la banda de un audio de 16 kHz).

- **22 050 Hz (recomendado):**
  - es la frecuencia de todos los checkpoints medium en español, también la del `x_low` de ald, y la que asume el entrenamiento (`--model.sample_rate 22050`);
  - el modelo aprende que por encima de 8 kHz no hay nada, así que sonará algo más apagado que las voces de estudio, pero fiel a los audios;
  - en contra: los WAV pesan un 38 % más y el entrenamiento procesa más muestras.
- **16 000 Hz:**
  - coincide con la banda real de los audios y pesa menos;
  - en contra: no hay checkpoint en español a 16 kHz, así que habría que entrenar casi desde cero o cambiar la arquitectura, con menos calidad, y además se sale del camino probado.

`dataset_final.py` arma las dos versiones. Para el fine-tuning se usa la de 22 050 Hz, y la de 16 000 Hz queda guardada por si algún día hay una base a 16 kHz.

## 4. Pasos y tiempo (estimación)

Son estimaciones; se confirman midiendo las iteraciones por segundo en los primeros minutos de la primera sesión.

- **Datos:** con 25–40 min aceptados y frases de unos 3–4 s, salen unas 450–700 frases. Con `batch_size` 16 son unos 30–45 pasos por época.
- **Épocas:** la guía sugiere unas 2000 épocas para un fine-tuning con menos de 5 h de datos. Con tan poco audio conviene escuchar a las 300, 500 y 1000 épocas: suele bastar antes de 2000, y con más se arriesga el sobreajuste.
- **Velocidad en la T4:** sin cifras publicadas. Supongo 1–2 pasos/s para un modelo medium con `batch_size` 16, es decir, unos 20–45 s por época. Eso da:
  - 500 épocas (≈ 15 000–22 000 pasos): 3–6 h;
  - 1000 épocas (≈ 30 000–45 000 pasos): 6–12 h.
- **Sesiones:** son 2 o 3 sesiones de Colab gratuito, con los checkpoints en Drive. Con un tope de unas 4 h por sesión, se guarda cada 25–50 épocas.

## 5. Qué descargaría (no descargado)

- En Colab, no en la laptop: `es/es_MX/ald/medium/epoch=9999-step=1753600.ckpt`.
  - 845 898 456 B (846 MB).
  - sha256 `77ee30f9a382594123ec4fb3ca53b437612819a44b3e3dc490f39f5a2dfefcce`.
  - Con su `config.json` (6 861 B).
- Plan B: `es/es_ES/sharvard/medium/epoch=4899-step=215600.ckpt`.
  - 924 476 424 B (924 MB).
  - sha256 `cae76056c432f1a477705af1ebec55b73b586865e73b256d4bdc6fdaea8296c9`.
- El resto lo instala Colab: piper1-gpl con `[train]` y espeak-ng.

Subir el dataset a Colab o a Drive saca los audios de la máquina: es una decisión pendiente del usuario (ver el ROADMAP, "Voz propia").

## Fuentes

- [piper1-gpl, TRAINING.md](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/TRAINING.md)
- [piper-tts en PyPI](https://pypi.org/project/piper-tts/)
- [rhasspy/piper-checkpoints, español](https://huggingface.co/datasets/rhasspy/piper-checkpoints/tree/main/es): fichas y `config.json` de [ald](https://huggingface.co/datasets/rhasspy/piper-checkpoints/tree/main/es/es_MX/ald), [sharvard](https://huggingface.co/datasets/rhasspy/piper-checkpoints/tree/main/es/es_ES/sharvard) y [davefx](https://huggingface.co/datasets/rhasspy/piper-checkpoints/tree/main/es/es_ES/davefx)
- [Dataset de ald](https://huggingface.co/datasets/rmcpantoja/Ald_Mexican_Spanish_speech_dataset)
- [Discusión #138 de piper1-gpl: entrenar en Colab y checkpoints viejos](https://github.com/OHF-Voice/piper1-gpl/discussions/138)
- [Cuaderno de la comunidad (KiON-GiON)](https://colab.research.google.com/github/KiON-GiON/piper1-gpl/blob/fixes/notebooks/Piper_Training_Notebook.ipynb)
