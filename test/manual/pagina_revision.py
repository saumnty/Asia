"""Voz propia: página local para revisar las frases del dataset (escuchar, corregir y aceptar).

    .venv\\Scripts\\python.exe test\\manual\\pagina_revision.py --dataset C:\\AsiaVoz\\dataset\\fa

Escribe <dataset>/revisar.html: un solo archivo, sin servidor ni nada de
internet, que se abre con file:// y reproduce wavs/NNNN.wav. Lee revisar.csv
(con texto_small y texto_turbo si ya pasó transcribir_turbo; si no, solo el de
small). El avance se guarda en el navegador; "Exportar" descarga metadata.csv
(id|texto de las aceptadas) y revision.json (estado y texto de todas).
"""
import argparse
import csv
import difflib
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from transcribir_turbo import comparable  # noqa: E402

RULE = 'El texto debe decir exactamente lo que se oye, con los números escritos en letra ("dos", no "2").'
FIRST, ACCEPTED, WORST = 1, 2, 3


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def marked(words, other):
    """[[palabra, distinta]] de words frente a other, comparando sin mayúsculas, acentos ni puntuación."""
    left, right = [comparable(word) for word in words], [comparable(word) for word in other]
    same = set()

    for block in difflib.SequenceMatcher(None, left, right, autojunk=False).get_matching_blocks():
        same.update(range(block.a, block.a + block.size))

    return [[word, index not in same] for index, word in enumerate(words)]


def entry(row) -> dict:
    """Una frase para la página, con su grupo de orden y lo que hay que mirar."""
    small = row.get("texto_small", row.get("texto", "")) or ""
    turbo = row.get("texto_turbo")
    has_turbo = turbo is not None
    turbo = turbo or ""
    reasons = row.get("motivos_turbo" if has_turbo else "motivos", "") or ""
    logprob = number(row.get("avg_logprob_turbo" if has_turbo else "avg_logprob"), -10.0)
    agree = (row.get("coinciden") == "sí") if has_turbo else True
    reason_list = [reason for reason in reasons.split("; ") if reason]

    if not agree:
        reason_list.append("no coinciden")

    # Las que más vale escuchar: dudosas pero no perdidas (logprob de -0,8 para arriba).
    if logprob >= -0.8 and (not agree or logprob < -0.6):
        group = FIRST
    elif not reasons and agree:
        group = ACCEPTED
    else:
        group = WORST

    return {
        "id": row["id"], "segundos": number(row.get("segundos")), "motivos": reason_list, "grupo": group,
        "logprob": logprob, "small": marked(small.split(), turbo.split()) if has_turbo else [[w, False] for w in small.split()],
        "turbo": marked(turbo.split(), small.split()) if has_turbo else [],
        "texto": turbo if has_turbo else small,
    }


def ordered(rows) -> list:
    """Primero las dudosas que más vale escuchar, luego las aceptadas, al final las peores (de mejor a peor)."""
    entries = [entry(row) for row in rows]
    return sorted(entries, key=lambda e: (e["grupo"], -e["logprob"] if e["grupo"] == WORST else 0, e["id"]))


def page(entries, title) -> str:
    data = json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__RULE__", html.escape(RULE)).replace(
        "__KEY__", json.dumps(f"revision-{title}")).replace("__DATA__", data)


def build(dataset) -> Path:
    dataset = Path(dataset)

    with open(dataset / "revisar.csv", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))

    target = dataset / "revisar.html"
    target.write_text(page(ordered(rows), dataset.name), encoding="utf-8")
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True, help="la carpeta de preparar_voz (wavs/, revisar.csv)")
    args = parser.parse_args()
    target = build(args.dataset)
    print(f"Página: {target}")
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revisión de voz: __TITLE__</title>
<style>
:root { --bg: #f7f7f5; --card: #fff; --text: #1d1d1b; --muted: #6b6b66; --line: #ddd; --diff: #ffe08a;
        --ok: #2e7d32; --bad: #c62828; --skip: #8d6e00; --focus: #1565c0; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161615; --card: #22221f; --text: #ecebe6; --muted: #a3a29b; --line: #3a3a36; --diff: #6b5400;
          --ok: #81c784; --bad: #ef9a9a; --skip: #e6c35c; --focus: #64b5f6; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.45 system-ui, sans-serif; }
header { position: sticky; top: 0; z-index: 1; background: var(--bg); border-bottom: 1px solid var(--line);
         padding: 10px 16px; display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; }
header h1 { font-size: 17px; margin: 0; }
.rule { flex-basis: 100%; margin: 0; color: var(--muted); }
.counts { font-variant-numeric: tabular-nums; }
main { max-width: 980px; margin: 0 auto; padding: 12px 16px 80px; }
.row { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; margin: 8px 0; }
.row.current { outline: 2px solid var(--focus); }
.row.aceptada { border-left: 6px solid var(--ok); }
.row.descartada { border-left: 6px solid var(--bad); opacity: .7; }
.row.saltada { border-left: 6px solid var(--skip); }
.meta { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; color: var(--muted); font-size: 13px; }
.meta b { color: var(--text); }
.tag { border: 1px solid var(--line); border-radius: 10px; padding: 0 7px; }
audio { width: 100%; height: 32px; margin: 6px 0; }
.texts { display: grid; grid-template-columns: 70px 1fr; gap: 2px 8px; font-size: 14px; }
.texts span.label { color: var(--muted); }
mark { background: var(--diff); color: inherit; border-radius: 2px; }
textarea { width: 100%; min-height: 48px; margin-top: 6px; font: inherit; color: var(--text); background: var(--bg);
           border: 1px solid var(--line); border-radius: 6px; padding: 6px; }
.actions { display: flex; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
button, select { font: inherit; color: var(--text); background: var(--card); border: 1px solid var(--line);
                 border-radius: 6px; padding: 4px 10px; cursor: pointer; }
.help { color: var(--muted); font-size: 13px; }
</style>
</head>
<body>
<header>
  <h1>Revisión de voz: __TITLE__</h1>
  <span class="counts" id="counts"></span>
  <label>Estado <select id="state-filter">
    <option value="">todas</option><option value="pendiente">pendientes</option><option value="aceptada">aceptadas</option>
    <option value="descartada">descartadas</option><option value="saltada">saltadas</option></select></label>
  <label>Motivo <select id="reason-filter"><option value="">todos</option></select></label>
  <button id="export">Exportar</button>
  <label class="help">Importar revision.json <input type="file" id="import" accept=".json"></label>
  <p class="rule"><b>Regla:</b> __RULE__</p>
  <p class="rule help">Teclas: espacio reproduce, Enter acepta, D descarta, S salta, flechas para moverse.
    Dentro del cuadro de texto: Ctrl+Enter acepta y Esc sale.</p>
</header>
<main id="list"></main>
<script>
const ROWS = __DATA__;
const KEY = __KEY__;
let saved = {};
try { saved = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { saved = {}; }
const state = {};
for (const row of ROWS) {
  const old = saved[row.id] || {};
  state[row.id] = { estado: old.estado || "pendiente", texto: typeof old.texto === "string" ? old.texto : row.texto };
}
let current = 0;

function store() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* sin almacenamiento: el avance vive en la página */ }
}

function words(list) {
  const span = document.createElement("span");
  for (const [word, changed] of list) {
    const part = document.createElement(changed ? "mark" : "span");
    part.textContent = word;
    span.append(part, " ");
  }
  return span;
}

function visible() {
  const wantState = document.getElementById("state-filter").value;
  const wantReason = document.getElementById("reason-filter").value;
  return ROWS.filter(row => (!wantState || state[row.id].estado === wantState) &&
                            (!wantReason || row.motivos.includes(wantReason)));
}

function render() {
  const list = document.getElementById("list");
  list.textContent = "";
  const rows = visible();
  current = Math.min(current, Math.max(rows.length - 1, 0));
  rows.forEach((row, index) => {
    const box = document.createElement("section");
    box.className = `row ${state[row.id].estado}` + (index === current ? " current" : "");
    box.dataset.id = row.id;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `<b>${row.id}</b><span>${row.segundos.toFixed(1)} s</span><span>${state[row.id].estado}</span>`;
    for (const reason of row.motivos) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = reason;
      meta.append(tag);
    }
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "none";
    audio.src = `wavs/${row.id}.wav`;
    const texts = document.createElement("div");
    texts.className = "texts";
    const label = text => Object.assign(document.createElement("span"), { className: "label", textContent: text });
    texts.append(label("small"), words(row.small));
    if (row.turbo.length) texts.append(label("turbo"), words(row.turbo));
    const edit = document.createElement("textarea");
    edit.value = state[row.id].texto;
    edit.addEventListener("input", () => { state[row.id].texto = edit.value; store(); });
    edit.addEventListener("focus", () => { current = index; mark(); });
    const actions = document.createElement("div");
    actions.className = "actions";
    for (const [name, estado] of [["Aceptar", "aceptada"], ["Descartar", "descartada"], ["Saltar", "saltada"]]) {
      const button = document.createElement("button");
      button.textContent = name;
      button.addEventListener("click", () => { current = index; decide(estado); });
      actions.append(button);
    }
    box.append(meta, audio, texts, edit, actions);
    box.addEventListener("click", () => { current = index; mark(); });
    list.append(box);
  });
  counts();
}

function mark() {
  document.querySelectorAll(".row").forEach((box, index) => box.classList.toggle("current", index === current));
}

function counts() {
  const all = Object.values(state);
  const done = all.filter(s => s.estado === "aceptada" || s.estado === "descartada").length;
  const accepted = ROWS.filter(row => state[row.id].estado === "aceptada");
  const minutes = accepted.reduce((sum, row) => sum + row.segundos, 0) / 60;
  document.getElementById("counts").textContent =
    `Revisadas ${done} de ${ROWS.length} · aceptadas ${accepted.length} · ${minutes.toFixed(1)} min aceptados`;
}

function currentBox() { return document.querySelectorAll(".row")[current]; }

function move(step) {
  const total = document.querySelectorAll(".row").length;
  if (!total) return;
  current = Math.max(0, Math.min(total - 1, current + step));
  mark();
  currentBox().scrollIntoView({ block: "center" });
}

function decide(estado) {
  const box = currentBox();
  if (!box) return;
  const id = box.dataset.id;
  state[id].estado = estado;
  state[id].texto = box.querySelector("textarea").value;
  box.querySelector("audio").pause();
  store();
  const filtered = document.getElementById("state-filter").value;
  if (filtered && filtered !== estado) { render(); } else { box.className = `row ${estado} current`; counts(); move(1); }
}

function play() {
  const box = currentBox();
  if (!box) return;
  const audio = box.querySelector("audio");
  document.querySelectorAll("audio").forEach(other => { if (other !== audio) other.pause(); });
  if (audio.paused) { audio.currentTime = audio.ended ? 0 : audio.currentTime; audio.play(); } else { audio.pause(); }
}

document.addEventListener("keydown", event => {
  const typing = event.target.tagName === "TEXTAREA";
  if (typing) {
    if (event.key === "Enter" && event.ctrlKey) { event.preventDefault(); decide("aceptada"); event.target.blur(); }
    else if (event.key === "Escape") { event.target.blur(); }
    return;
  }
  if (event.target.tagName === "SELECT" || event.target.tagName === "INPUT") return;
  const key = event.key.toLowerCase();
  if (event.key === " ") { event.preventDefault(); play(); }
  else if (event.key === "Enter") { event.preventDefault(); decide("aceptada"); }
  else if (key === "d") { decide("descartada"); }
  else if (key === "s") { decide("saltada"); }
  else if (event.key === "ArrowDown" || event.key === "ArrowRight") { event.preventDefault(); move(1); }
  else if (event.key === "ArrowUp" || event.key === "ArrowLeft") { event.preventDefault(); move(-1); }
});

function download(name, text, type) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type }));
  link.download = name;
  document.body.append(link);
  link.click();
  setTimeout(() => { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
}

document.getElementById("export").addEventListener("click", () => {
  const clean = text => text.replace(/[|\r\n]+/g, " ").replace(/\s+/g, " ").trim();
  const metadata = ROWS.filter(row => state[row.id].estado === "aceptada")
    .sort((a, b) => a.id.localeCompare(b.id))
    .map(row => `${row.id}|${clean(state[row.id].texto)}`).join("\n");
  download("metadata.csv", metadata ? metadata + "\n" : "", "text/csv;charset=utf-8");
  // Dos descargas seguidas: algunos navegadores piden permiso para la segunda.
  setTimeout(() => download("revision.json", JSON.stringify(state, null, 1), "application/json"), 400);
});

document.getElementById("import").addEventListener("change", event => {
  const file = event.target.files[0];
  if (!file) return;
  file.text().then(text => {
    const loaded = JSON.parse(text);
    for (const id of Object.keys(loaded)) {
      if (state[id] && typeof loaded[id] === "object") {
        state[id] = { estado: loaded[id].estado || "pendiente", texto: String(loaded[id].texto ?? state[id].texto) };
      }
    }
    store();
    render();
  }).catch(() => alert("No pude leer ese revision.json."));
});

const reasons = [...new Set(ROWS.flatMap(row => row.motivos))].sort();
const reasonFilter = document.getElementById("reason-filter");
for (const reason of reasons) reasonFilter.append(new Option(reason, reason));
document.getElementById("state-filter").addEventListener("change", () => { current = 0; render(); });
reasonFilter.addEventListener("change", () => { current = 0; render(); });
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
