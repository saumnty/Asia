"""Bitácora de envíos a proveedores externos (fase G, paso 5).

logs/external_audit.jsonl, una línea JSON por envío: fecha, proveedor,
modelo, tipos de contenido, caracteres, hash SHA-256 de lo enviado, cómo se
autorizó, secretos redactados y si el proveedor respondió. Nunca el texto:
con el hash se puede comprobar si un texto concreto salió, sin guardarlo.
"""
import hashlib
import json
from datetime import datetime

from core import paths

DEFAULT_SHOWN = 10


def prompt_hash(messages) -> str:
    text = "\n".join(f"{m.get('role')}:{m.get('content') or ''}" for m in messages)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def log_external_send(provider, model, labels, messages, authorization, secrets=0, ok=True):
    entry = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "proveedor": provider,
        "modelo": model,
        "tipos": sorted(labels),
        "caracteres": sum(len(m.get("content") or "") for m in messages),
        "sha256": prompt_hash(messages),
        "autorizacion": authorization,
        "secretos_redactados": secrets,
        "respuesta": "ok" if ok else "error",
    }
    path = paths.EXTERNAL_AUDIT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def recent_entries(limit=DEFAULT_SHOWN) -> list[dict]:
    path = paths.EXTERNAL_AUDIT_FILE

    if not path.exists():
        return []

    entries = []

    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return entries[-limit:]


def summary(limit=DEFAULT_SHOWN) -> str:
    entries = recent_entries(limit)

    if not entries:
        return "No he enviado nada afuera: la bitácora (logs/external_audit.jsonl) está vacía."

    lines = [f"Últimos {len(entries)} envíos externos (logs/external_audit.jsonl, sin el texto):"]

    for e in entries:
        secrets = f" · {e['secretos_redactados']} secretos redactados" if e.get("secretos_redactados") else ""
        failed = " · el proveedor falló" if e.get("respuesta") == "error" else ""
        lines.append(
            f"- {e['fecha'].replace('T', ' ')} · {e['proveedor']} · {', '.join(e['tipos'])} · "
            f"{e['caracteres']} caracteres · {e['autorizacion']} · sha256 {e['sha256'][:12]}…{secrets}{failed}"
        )

    return "\n".join(lines)
