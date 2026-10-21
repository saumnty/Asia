import numpy as np
import pandas as pd
from scipy.io import arff

nombre_archivo = "vote_copy.arff"

try:
    # 1. Leer el archivo original
    data, meta = arff.loadarff(nombre_archivo)
    df = pd.DataFrame(data)

    # 2. Limpiar los datos
    df = df.replace({b"?": np.nan, "?": np.nan})
    df_limpio = df.dropna().copy()

    # 3. SOBRESCRIBIR el archivo .arff original con los datos limpios
    atributos = [
        (col, meta[col][1] if meta[col][0] == "nominal" else "NUMERIC")
        for col in meta.names()
    ]
    registros = [tuple(row) for row in df_limpio.to_numpy()]

    with open(nombre_archivo, "w", encoding="utf-8") as f:
        # Encabezado
        f.write(f"@relation {meta.name}\n\n")
        for nombre_attr, tipo_attr in atributos:
            if isinstance(tipo_attr, tuple):
                valores = ", ".join([f"'{v}'" for v in tipo_attr])
                f.write(f"@attribute '{nombre_attr}' {{{valores}}}\n")
            else:
                f.write(f"@attribute '{nombre_attr}' {tipo_attr}\n")

        # Datos limpios
        f.write("\n@data\n")
        for fila in registros:
            valores_fila = [
                f"'{val.decode('utf-8')}'" if isinstance(val, bytes) else str(val)
                for val in fila
            ]
            f.write(",".join(valores_fila) + "\n")

    print(
        f"¡Archivo sobrescrito con éxito! Se guardaron {len(df_limpio)} registros sin valores faltantes."
    )

except Exception as e:
    print(f"Error al procesar el archivo: {e}")