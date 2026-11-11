# Voz propia: plan del fine-tuning de Piper

Plan para entrenar una voz de Piper con las frases revisadas del dataset propio (mujer, español de México; ~25–40 min de notas de voz, solo uso privado), en Colab gratuito con una T4. Investigado el 2026-11-05; dataset y cuaderno listos el 2026-11-11 (sección 6).

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
  - La conexión con Drive se cae hacia las 4 h. Piper reescribe `last.ckpt` en cada época (TRAINING.md no documenta ningún flag de frecuencia de guardado), y hay que copiarlo a Drive y reanudar desde ahí.
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
- **Sesiones:** son 2 o 3 sesiones de Colab gratuito, con los checkpoints en Drive. Con un tope de unas 4 h por sesión, el cuaderno para a las 3 h 30 (`--trainer.max_time`) y copia `last.ckpt` a Drive cada 5 min.

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

## 6. Dataset y cuaderno (hechos el 2026-11-11)

### Las dos variantes (22 050 Hz, mono, 16 bits)

Salen de `dataset_final.py` con las 750 frases de `revisar.html` (747 aceptadas y 3 descartadas por ti). Están en `C:\AsiaVoz\dataset\fa\`, fuera del repositorio, y no se ha subido nada a internet.

| Variante | Carpeta | Frases | Minutos | Zip | Qué cambia |
|---|---|---|---|---|---|
| normal | `fa_normal50` | 747 | 52,2 | 108,9 MB | solo recorta el silencio de los extremos (0,15 s) y normaliza el pico a -3 dBFS |
| silencios atenuados | `fa_atenuado50` | 747 | 52,2 | 106,2 MB | lo mismo, y las pausas de más de 0,35 s dentro de la frase bajan 24 dB (rampas de 30 ms; la duración no cambia) |

Comandos:
```
.venv\Scripts\python.exe test\manual\dataset_final.py --dataset C:\AsiaVoz\dataset\fa --metadata C:\AsiaVoz\dataset\fa\exportado\metadata.csv --revision C:\AsiaVoz\dataset\fa\exportado\revision.json --destino C:\AsiaVoz\dataset\fa\fa_normal --frecuencias 22050
Para la otra: --silencios atenuados y --destino ...\fa_atenuado
```

- **Descartadas por el script:** ninguna (no hay textos vacíos ni wavs que falten). `metadata.csv` y `revision.json` cuadran.
- **Avisos (siguen dentro):** 32 frases con dígitos (espeak-ng los lee en letra, pero conviene revisarlos), 1 con un "%" (0611) y 1 de 0,99 s (0185). Ninguna pasa de 15 s: la más larga dura 14,1 s.
- **Validación** (las dos variantes): todos los wav son mono, 22 050 Hz y 16 bits; ninguna transcripción vacía; `metadata.csv` (`NNNN.wav|texto`) cuadra con los archivos, y el zip tiene los mismos archivos que la carpeta. Los `metadata.csv` de las dos variantes son idénticos, y sin recortes ni picos bajos. Un 25–29 % de los wavs tiene más de un 10 % de muestras en cero exacto (silencio digital de las notas de voz, algo más en la atenuada): no impide entrenar.
- **Cuál usar:** empieza con la **normal**. La atenuada es para comparar si la voz sale con ruido o con respiraciones raras en las pausas; solo tendría sentido entrenarla aparte.

### El cuaderno

`test/manual/colab/entrenar_voz_propia.ipynb`: fine-tuning de Piper desde `es_MX/ald/medium` (plan B, `BASE = "sharvard"`), con checkpoints en Drive, exportación a `.onnx` y una celda que borra los audios. Las instalaciones (`apt`, `pip`, piper1-gpl con `[train]`) solo ocurren dentro de Colab.

Estado: **no probado en Colab** (no tengo acceso). Lo que escribí sale de TRAINING.md y de la discusión #138; si una celda falla, el error mostrará qué ajustar. Dudas conocidas:
- `--model.warmstart_ckpt` con la base `ald` es lo que dice la documentación para los checkpoints viejos; con `sharvard` (dos hablantes) puede fallar por la forma de las capas.
- Uso `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` en vez de parchear `piper/train/__main__.py`.
- `--trainer.max_time` es un argumento de Lightning, no documentado por Piper.

### Pasos para Colab

1. **Antes de subir nada:** confirma con la persona de la voz que sus audios irán a tu Drive y a Colab (ver Pendientes de `docs/CONTEXTO.md`).
2. En Drive, crea `MyDrive/asia_voz/entrada/` y sube `fa_normal_22050.zip`.
3. Abre el cuaderno en Colab (Archivo → Subir cuaderno) con **T4 GPU**.
   - **Primero, la prueba de humo:** pon `SMOKE = True` y ejecuta todo. Usa 20 frases (unos 10–15 min más las instalaciones) y imprime ✅/❌ para tres puntos: (a) `max_time` se respeta (entrena con un límite de 3 min y debe parar solo), (b) se reanuda con `--ckpt_path` desde el `last.ckpt` de Drive y el contador sigue subiendo, (c) se exporta el `.onnx` y se sintetiza una frase que suena. Usa rutas propias (`checkpoints_humo`, `/content/humo`) y no toca los checkpoints ni el zip reales. Con algún ❌, no sigas.
   - Con todo ✅, pon `SMOKE = False`, reinicia el entorno y ejecuta las secciones 0 a 4 en orden (la 4 es el entrenamiento). La primera sesión baja la base (846 MB, con sha256 comprobado) a `asia_voz/base/`.
4. La sección 4 para sola a las 3 h 30 (`SESSION_MAX_TIME`) o al llegar a `MAX_EPOCHS`. Para escuchar un avance (300, 500 y 1000 épocas) ejecuta entonces la sección 5.
5. Para seguir entrenando, vuelve a ejecutar las secciones 0 a 4 en una sesión nueva: reanuda desde `asia_voz/checkpoints/last.ckpt`. `MAX_EPOCHS` es el total, no por sesión.
6. Sección 5: exporta `es_MX-propia-medium.onnx` y su `.onnx.json` a `asia_voz/salida/` y los descarga.
7. Sección 6, solo al terminar de entrenar (sin los audios no se puede repetir desde cero): borra el zip de Drive y los audios de Colab (`DELETE_AUDIO = True`), y **vacía la Papelera de Drive**, porque Drive guarda lo borrado.

**Tiempo estimado:** 3–6 h para 500 épocas, 6–12 h para 1000 (sección 4), en 2 o 3 sesiones; mide los pasos por segundo en los primeros minutos.

### Probarla en Asia

1. Copia `es_MX-propia-medium.onnx` y `es_MX-propia-medium.onnx.json` a `data/voices/` (no se versiona).
2. En `config/settings.json`, sección `voice`, pon `"tts_voice": "es_MX-propia-medium"` (lo cambias tú: el archivo está protegido). `voices_dir` ya es `data/voices`.
3. Reinicia Asia y di algo con la voz activada. Para volver, deja `es_MX-claude-high`.
4. Compara con `test/manual/check_primer_audio.py`: la voz es de calidad medium (22 050 Hz), igual que la que ya funciona, y no debería cambiar el primer audio.

## Fuentes

- [piper1-gpl, TRAINING.md](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/TRAINING.md)
- [piper-tts en PyPI](https://pypi.org/project/piper-tts/)
- [rhasspy/piper-checkpoints, español](https://huggingface.co/datasets/rhasspy/piper-checkpoints/tree/main/es): fichas y `config.json` de [ald](https://huggingface.co/datasets/rhasspy/piper-checkpoints/tree/main/es/es_MX/ald), [sharvard](https://huggingface.co/datasets/rhasspy/piper-checkpoints/tree/main/es/es_ES/sharvard) y [davefx](https://huggingface.co/datasets/rhasspy/piper-checkpoints/tree/main/es/es_ES/davefx)
- [Dataset de ald](https://huggingface.co/datasets/rmcpantoja/Ald_Mexican_Spanish_speech_dataset)
- [Discusión #138 de piper1-gpl: entrenar en Colab y checkpoints viejos](https://github.com/OHF-Voice/piper1-gpl/discussions/138)
- [Cuaderno de la comunidad (KiON-GiON)](https://colab.research.google.com/github/KiON-GiON/piper1-gpl/blob/fixes/notebooks/Piper_Training_Notebook.ipynb)
