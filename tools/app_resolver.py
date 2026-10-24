import difflib
import re
import subprocess
import unicodedata


def get_start_apps():
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json"
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )

    return result.stdout


def find_start_app(app_name: str):
    import json

    raw = get_start_apps()

    try:
        apps = json.loads(raw)
    except Exception:
        return None

    if isinstance(apps, dict):
        apps = [apps]

    query = app_name.lower().strip()

    for app in apps:
        name = app.get("Name", "")
        app_id = app.get("AppID", "")

        if query in name.lower():
            return {
                "name": name,
                "appid": app_id,
                "command": f'explorer.exe shell:AppsFolder\\{app_id}'
            }

    return None

# --- Nombres aproximados contra config/apps.json ----------------------------
#
# El IntentEngine a veces traduce o deforma el nombre ("bloc de notas" ->
# "notebook", "blocknote") y open_app no encontraba la app. Se compara contra
# las claves reales de apps.json; si no hay una coincidencia clara, se pide
# aclaración con los nombres parecidos en lugar de fallar.


# Traducciones o deformaciones que no se parecen lo bastante al nombre real.
# Solo valen si la clave de destino existe en apps.json.
KNOWN_VARIANTS = {
    "notebook": "bloc de notas",
    "blocknote": "bloc de notas",
    "block note": "bloc de notas",
    "notes": "bloc de notas",
    "notas": "bloc de notas",
    "calc": "calculadora",
    "browser": "navegador",
}

# Parecido mínimo (0..1) para abrir sin preguntar, y para sugerir.
OPEN_RATIO = 0.8
SUGGEST_RATIO = 0.5
MAX_SUGGESTIONS = 3


def normalize(name: str) -> str:
    """Minúsculas, sin acentos y con un solo espacio: "Bloc de  Notas" -> "bloc de notas"."""
    text = unicodedata.normalize("NFKD", name.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.split())


def compact(name: str) -> str:
    # + y # se conservan: "notepad++" no es "notepad".
    return re.sub(r"[^\w+#]", "", normalize(name))


def ratios(name: str, apps: dict) -> list[tuple[float, str]]:
    target = compact(name)
    return sorted(
        ((difflib.SequenceMatcher(None, target, compact(key)).ratio(), key) for key in apps),
        reverse=True,
    )


def resolve_known_app(name: str, apps: dict) -> str | None:
    """Clave de apps.json para name: exacta, variante conocida o casi igual.

    "Casi igual" es OPEN_RATIO o más y que no haya otra clave de un programa
    distinto igual de cerca ("calculadra" vale: calculadora y calculator
    abren lo mismo).
    """
    by_normal = {normalize(key): key for key in apps}
    query = normalize(name)

    if query in by_normal:
        return by_normal[query]

    variant = KNOWN_VARIANTS.get(query)

    if variant and normalize(variant) in by_normal:
        return by_normal[normalize(variant)]

    return None


def close_app(name: str, apps: dict) -> str | None:
    scored = ratios(name, apps)

    if not scored or scored[0][0] < OPEN_RATIO:
        return None

    best_ratio, best = scored[0]
    rivals = [key for ratio, key in scored[1:] if ratio >= OPEN_RATIO and apps[key] != apps[best]]

    return None if rivals else best


def suggestions(name: str, apps: dict) -> list[str]:
    """Claves parecidas, una por programa, para pedir aclaración."""
    seen, result = set(), []

    for ratio, key in ratios(name, apps):
        if ratio < SUGGEST_RATIO or len(result) == MAX_SUGGESTIONS:
            break

        if apps[key] not in seen:
            seen.add(apps[key])
            result.append(key)

    return result


def clarification(name: str, apps: dict) -> str:
    similar = suggestions(name, apps)

    if similar:
        options = " o ".join(f'"{key}"' for key in similar)
        return (
            f"No encontré la aplicación '{name}'. ¿Te refieres a {options}? "
            f'Escribe, por ejemplo: abre {similar[0]}.'
        )

    known = ", ".join(sorted(apps)[:12])
    return (
        f"No encontré la aplicación '{name}' ni nada parecido. "
        f"Apps conocidas: {known}. Puedes agregar otras en config/apps.json."
    )
