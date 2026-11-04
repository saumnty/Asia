"""Una página de pregunta de Stack Exchange (.zim de sotoki) en fragmentos (fase H, capa 4).

La pregunta y cada respuesta van aparte, con su autor, votos y fecha. De las
respuestas se quedan la aceptada y, después, las más votadas (a igual voto, la
más reciente). El texto va una frase por línea y el código línea por línea,
para que las citas se puedan verificar.

Estructura comprobada en robotics.stackexchange.com_en_all_2026-10 (sotoki
3.1.1): #question y div.answer con data-score, la aceptada con la clase
accepted-answer, el cuerpo en .js-post-body, la fecha y el autor en la
tarjeta .s-user-card ("answered Oct 21 '25 at 06:37"), la fecha de la pregunta
también en time[itemprop=dateCreated].
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from core.rag.article import SENTENCE_END, clean, pack

MAX_ANSWERS = 3
# Una respuesta de más años que esto, frente a la edición del .zim, puede estar desactualizada.
STALE_YEARS = 5
PROSE = ["p", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"]
CARD_DATE = re.compile(r"(?:asked|answered)\s+(.+)$", re.IGNORECASE)
CARD_FORMATS = ("%b %d '%y at %H:%M", "%b %d, %Y at %H:%M", "%b %d at %H:%M")
# CC BY-SA según la fecha de publicación (stackoverflow.com/help/licensing).
LICENSES = ((date(2011, 4, 8), "CC BY-SA 2.5"), (date(2018, 5, 2), "CC BY-SA 3.0"))
LATEST_LICENSE = "CC BY-SA 4.0"


@dataclass
class Post:
    post_id: str
    kind: str  # "pregunta" o "respuesta"
    score: int = 0
    accepted: bool = False
    posted: date = None
    author: str = ""
    lines: list = field(default_factory=list)


@dataclass
class QAPage:
    question_id: str
    title: str
    question: Post
    answers: list


def license_for(posted) -> str:
    for until, name in LICENSES:
        if posted and posted < until:
            return name

    return LATEST_LICENSE


def is_stale(posted, edition) -> bool:
    return bool(posted and edition) and (edition - posted).days > STALE_YEARS * 365


def card_date(text: str, edition=None):
    """La fecha de "answered Oct 21 '25 at 06:37" (sin año, la de la edición)."""
    found = CARD_DATE.search(text or "")

    for pattern in CARD_FORMATS:
        try:
            parsed = datetime.strptime(found.group(1).strip(), pattern) if found else None
        except ValueError:
            continue

        if parsed and "%y" not in pattern and "%Y" not in pattern:
            parsed = parsed.replace(year=(edition or date.today()).year)

        return parsed.date() if parsed else None

    return None


def post_lines(body) -> list:
    """Una frase por línea; el código, una línea por línea."""
    lines = []

    for block in body.find_all(PROSE + ["pre"]):
        if block.find_parent(PROSE + ["pre"]) and block.find_parent(PROSE + ["pre"]) is not block:
            continue

        if block.name == "pre":
            lines += [line.rstrip() for line in block.get_text().splitlines() if line.strip()]
        else:
            lines += [sentence for sentence in SENTENCE_END.split(clean(block.get_text())) if sentence]

    return lines


def post_of(node, kind, edition=None) -> Post:
    card = next((c for c in node.select(".s-user-card") if CARD_DATE.search(c.get_text(" ", strip=True))), None)
    link = card.select_one(".s-user-card--link") if card else None
    time = card.select_one("time") if card else None
    author = clean(link.get_text()) if link else ""

    if not author:
        named = node.select_one("[itemprop=author] [itemprop=name]")
        author = clean(named.get_text()) if named else ""

    # Migradas de ROS Answers: la cuenta no existe, pero el cuerpo dice "Originally posted by X".
    if not author:
        original = node.select_one(".js-post-body a[href*='answers.ros.org/users/']")
        author = clean(original.get_text()) if original else ""

    body = node.select_one(".js-post-body")
    return Post(
        post_id=(node.get("id") or "").removeprefix("answer-"),
        kind=kind,
        score=int(node.get("data-score") or 0),
        accepted="accepted-answer" in (node.get("class") or []),
        posted=card_date(time.get_text(" ", strip=True) if time else "", edition),
        author=author or "autor desconocido",
        lines=post_lines(body) if body else [],
    )


def parse_page(html: str, edition=None) -> QAPage:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    heading = soup.select_one("#question-header h1")
    link = heading.select_one("a") if heading else None
    question_id = re.search(r"questions/(\d+)", link.get("href", "")) if link else None
    question = post_of(soup.select_one("#question"), "pregunta", edition)
    created = soup.select_one("time[itemprop=dateCreated]")

    if created and created.get("datetime"):
        question.posted = date.fromisoformat(created["datetime"][:10])

    question.post_id = question_id.group(1) if question_id else ""
    answers = [post_of(node, "respuesta", edition) for node in soup.select("#answers div.answer")]
    return QAPage(question.post_id, clean(heading.get_text()) if heading else "", question, answers)


def ordered_answers(answers: list, limit: int = MAX_ANSWERS) -> list:
    """La aceptada primero; después, las más votadas; a igual voto, la más reciente."""
    newest = date.max.toordinal()
    return sorted(
        answers, key=lambda a: (not a.accepted, -a.score, newest - (a.posted or date.min).toordinal())
    )[:limit]


def post_label(page: QAPage, post: Post) -> str:
    if post.kind == "pregunta":
        return f"{page.title} > Pregunta"

    kind = "Respuesta aceptada" if post.accepted else "Respuesta"
    return f"{page.title} > {kind}"


def post_origin(page: QAPage, post: Post, domain: str, edition=None) -> str:
    """Lo que ve quien lee: pregunta, enlace, autor, votos, fecha, licencia y si puede estar desactualizada."""
    link = f"https://{domain}/q/{page.question_id}" if post.kind == "pregunta" else f"https://{domain}/a/{post.post_id}"
    who = f"pregunta de {post.author}" if post.kind == "pregunta" else (
        f"respuesta {'aceptada ' if post.accepted else ''}de {post.author}, {post.score} votos"
    )
    when = post.posted.isoformat() if post.posted else "sin fecha"
    old = " (puede estar desactualizada)" if post.kind == "respuesta" and is_stale(post.posted, edition) else ""
    return f"«{page.title}» · {link} · {who} · {when}{old} · {license_for(post.posted)}"


def page_chunks(page: QAPage) -> list:
    """[(post, Chunk)] de la pregunta y las respuestas elegidas. Las líneas se cuentan en toda la página."""
    chunks, number = [], 0

    for post in [page.question, *ordered_answers(page.answers)]:
        numbered = list(enumerate(post.lines, number + 1))
        number += len(post.lines)
        chunks += [(post, chunk) for chunk in pack(numbered, post_label(page, post))] if numbered else []

    return chunks
