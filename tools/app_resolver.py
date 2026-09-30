import subprocess


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