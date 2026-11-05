"""Vuelve a armar mi_voz.zip con todo lo grabado para "Oye Asia" (check_wake --grabar y --negativos).

    .venv\\Scripts\\python.exe test\\manual\\empaquetar_mi_voz.py [--grabaciones data\\wake] [--destino C:\\AsiaVoz\\wake]

Mete data/wake/positivos/oye_asia/*.wav en positivos/ y data/wake/negativos/<frase>/*.wav
en negativos/<frase>/, como generar_wake.py. Reemplaza el mi_voz.zip de --destino; las
grabaciones solo se leen.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from generar_wake import ROOT, pack_recordings  # noqa: E402

DESTINATION = Path("C:/AsiaVoz/wake")


def repack(recordings, destination) -> dict:
    """{"positivos": n, "negativos": n}; el zip nuevo se arma aparte y solo entonces reemplaza al anterior."""
    destination = Path(destination)
    staging = destination / ".mi_voz_nuevo"
    staging.mkdir(parents=True, exist_ok=True)
    counts = pack_recordings(recordings, staging)
    (staging / "mi_voz.zip").replace(destination / "mi_voz.zip")
    staging.rmdir()
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grabaciones", type=Path, default=ROOT / "data" / "wake", help="lo grabado con check_wake")
    parser.add_argument("--destino", type=Path, default=DESTINATION, help="carpeta de mi_voz.zip")
    args = parser.parse_args()

    if not (args.grabaciones / "positivos" / "oye_asia").is_dir():
        parser.error(f"no hay grabaciones en {args.grabaciones / 'positivos' / 'oye_asia'}")

    counts = repack(args.grabaciones, args.destino)
    size = (args.destino / "mi_voz.zip").stat().st_size / 1e6
    print(f"mi_voz.zip: {counts['positivos']} positivos y {counts['negativos']} negativos, {size:.1f} MB, en {args.destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
