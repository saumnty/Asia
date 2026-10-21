import numpy as np
import pandas as pd
from scipy.io import arff

nombre_archivo = "vote.arff"

try:
    # 1. Leer el archivo ARFF original y convertirlo a DataFrame
    data, meta = arff.loadarff(nombre_archivo)
    df = pd.DataFrame(data)

    # 2. Convertir los indicadores de faltantes ('?') a NaN
    df = df.replace({b"?": np.nan, "?": np.nan})

    # 3. Imputar valores faltantes usando la moda de cada columna
    for col in df.columns:
        if df[col].isnull().any():
            # Calcular la moda ignorando nulos (primer valor si hay empate)
            moda = df[col].mode().iloc[0]
            # Rellenar los faltantes con la moda encontrada
            df[col] = df[col].fillna(moda)

    # 4. SOBRESCRIBIR el archivo .arff original con los datos imputados
    atributos = [
        (col, meta[col][1] if meta[col][0] == "nominal" else "NUMERIC")
        for col in meta.names()
    ]
    registros = [tuple(row) for row in df.to_numpy()]

    with open(nombre_archivo, "w", encoding="utf-8") as f:
        # Encabezado ARFF
        f.write(f"@relation {meta.name}\n\n")
        for nombre_attr, tipo_attr in atributos:
            if isinstance(tipo_attr, tuple):
                valores = ", ".join([f"'{v}'" for v in tipo_attr])
                f.write(f"@attribute '{nombre_attr}' {{{valores}}}\n")
            else:
                f.write(f"@attribute '{nombre_attr}' {tipo_attr}\n")

        # Datos guardados (reemplazando faltantes con la moda)
        f.write("\n@data\n")
        for fila in registros:
            valores_fila = [
                f"'{val.decode('utf-8')}'" if isinstance(val, bytes) else str(val)
                for val in fila
            ]
            f.write(",".join(valores_fila) + "\n")

    print(
        f"¡Archivo sobrescrito con éxito! Se imputaron los valores faltantes con la moda en {len(df)} registros."
    )

except Exception as e:
    print(f"Error al procesar el archivo: {e}")