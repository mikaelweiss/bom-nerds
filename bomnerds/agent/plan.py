"""The plan: every session of the tagging run, cut once from counts in the database before the first session starts.

A pass is a group of layers one session does together for a run of units: chapters, books, or headwords. Each pass weighs every unit
by what its layers must answer, and cuts its units into batches of about the same weight. Each batch is one session. Each pass ends
with review sessions, one for every REVIEW_SPAN writer sessions, which read every REVIEW_SPAN-th unit in full besides the flags.

The plan file is tab-separated: session, pass, model, layers, from, to, covers, after. A session covers the units of its pass from
`from` to `to`. `after` names the sessions that must be done first: a session id, or a pass name with :* for all its sessions.
"""

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..passages import book_name, reference
from ..sources import ROOT
from .jobs import JOBS, Job
from .layer import Rejected, chapter_scopes, split_chapter

PLAN = ROOT / "plan.tsv"
SESSIONS = JOBS / "sessions"
COLUMNS = ("session", "pass", "model", "layers", "from", "to", "covers", "after")
REVIEW_SPAN = 20
# A batch ends early at a book's last unit when it is this close to its target.
SNAP = 0.2


@dataclass(frozen=True)
class Pass:
    name: str
    layers: tuple[str, ...]
    model: str
    target: int
    after: tuple[str, ...]
    # "chapter", "entities", "headword", "edition chapter", or "book".
    unit: str = "chapter"
    # Each session waits for the one before it: every session for entities, and within one book for passes holding speakers.
    chained: str = ""


# Targets give a typical session a prompt of about 50,000 tokens, smaller where the answer is long, such as grammar and summaries.
PASSES = (
    Pass("entities", ("entities",), "opus", 40000, (), unit="entities", chained="all"),
    Pass("people", ("names", "speakers"), "sonnet", 25000, ("review-entities:*",), chained="book"),
    Pass("facts", ("relationships", "journeys", "dates"), "sonnet", 25000, ("review-people:*",)),
    Pass("links", ("links", "structures"), "opus", 25000, ("review-people:*",)),
    Pass("pronouns", ("pronouns", "about"), "sonnet", 25000, ("review-facts:*", "review-links:*")),
    Pass("headwords", ("headwords",), "sonnet", 1000, ("review-pronouns:*",)),
    Pass("meanings", ("meanings",), "opus", 1500, ("review-headwords:*",), unit="headword"),
    Pass("word-meanings", ("word-meanings",), "sonnet", 4000, ("review-meanings:*",), unit="edition chapter"),
    Pass("grammar", ("grammar",), "sonnet", 5000, ("review-pronouns:*",)),
    Pass("summaries", ("summaries",), "opus", 5000, ("review-word-meanings:*", "review-grammar:*")),
    Pass("summary-books", ("summaries",), "opus", 2000, ("review-summaries:*",), unit="book"),
)
BY_NAME = {p.name: p for p in PASSES}


@dataclass(frozen=True)
class Session:
    id: str
    pass_name: str
    model: str
    layers: tuple[str, ...]
    first: str
    last: str
    covers: str
    after: tuple[str, ...]

    @property
    def review(self) -> bool:
        return self.id.startswith("review-")

    @property
    def folder(self) -> Path:
        return SESSIONS / self.id

    def done(self) -> bool:
        return (self.folder / "done").exists()


# Units

# Values computed once per connection, since listing a pass's units reads the whole text.
# Each entry holds its connection, so its id is never reused while cached.
CACHE: dict[tuple[int, str], tuple[sqlite3.Connection, object]] = {}


def cached(db: sqlite3.Connection, key: str, compute: Callable):
    if (id(db), key) not in CACHE:
        CACHE[(id(db), key)] = (db, compute())
    return CACHE[(id(db), key)][1]


def units(db: sqlite3.Connection, p: Pass) -> list[str]:
    """Every unit of a pass, in the order its sessions cover them."""
    return cached(db, f"units/{p.name}", lambda: find_units(db, p))


def find_units(db: sqlite3.Connection, p: Pass) -> list[str]:
    from .layers import LAYERS

    if p.unit == "chapter":
        wanted = set().union(*(set(scope_units(db, p, LAYERS[name])) for name in p.layers))
        return [scope for scope in chapter_scopes(db) if scope in wanted]
    if p.unit == "book":
        return list(dict.fromkeys(split_chapter(scope)[0] for scope in chapter_scopes(db)))
    return LAYERS[p.layers[0]].scopes(db)


def unit_of(db: sqlite3.Connection, p: Pass, layer_name: str, scope: str) -> str | None:
    """The unit of a pass a layer's scope belongs to, or None when the pass leaves the scope to another pass."""
    if layer_name != "summaries":
        return scope
    from .layers.summaries import target
    from ..passages import locate

    kind, book, chapter, range_id = target(scope)
    if p.unit == "book":
        return book if chapter is None and range_id is None else None
    if chapter is not None:
        return f"{book}/{chapter}"
    if range_id is not None:
        first = db.execute("select first_word_id from verse_range where id = ?", (range_id,)).fetchone()[0]
        _, book, chapter, _ = locate(db, first)
        return f"{book}/{chapter}"
    return None


def scope_units(db: sqlite3.Connection, p: Pass, layer) -> dict[str, list[str]]:
    """Each unit of the pass mapped to the layer's scopes in it, in the layer's order."""
    return cached(db, f"scopes/{p.name}/{layer.name}", lambda: find_scope_units(db, p, layer))


def find_scope_units(db: sqlite3.Connection, p: Pass, layer) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for scope in layer.scopes(db):
        unit = unit_of(db, p, layer.name, scope)
        if unit is not None:
            found.setdefault(unit, []).append(scope)
    return found


def session_scopes(db: sqlite3.Connection, session: Session, layer_name: str) -> list[str]:
    """The scopes of one layer a session answers, in order."""
    from .layers import LAYERS

    p = BY_NAME[session.pass_name]
    ordered = units(db, p)
    if session.first not in ordered or session.last not in ordered:
        raise Rejected(f"{session.id} covers {session.first} to {session.last}, which are no longer units of the {p.name} pass. Cut the plan again")
    covered = set(ordered[ordered.index(session.first): ordered.index(session.last) + 1])
    by_unit = scope_units(db, p, LAYERS[layer_name])
    return [scope for unit in ordered if unit in covered for scope in by_unit.get(unit, [])]


# Weights


def chapter_counts(db: sqlite3.Connection) -> dict[str, tuple[int, int, int]]:
    """Words, capitalized words inside a sentence, and pronouns the pronoun pass answers, for every English chapter."""
    from .layers.pronouns import TAGGED

    pronouns = ",".join(f"'{word}'" for word in sorted(TAGGED))
    rows = db.execute(
        f"""
        select w.book_id, w.chapter, count(*),
            sum(substr(w.text, 1, 1) between 'A' and 'Z' and w.position > 1 and w.text not in ('I', 'O') and w.before not glob '*[.?!:;(]*'),
            sum(lower(w.text) in ({pronouns}) and h.part_of_speech = 'pronoun')
        from word w join edition e on e.id = w.edition_id
        left join word_headword h on h.word_id = w.id
        where e.language = 'en'
        group by w.edition_id, w.book_id, w.chapter
        """
    )
    return {f"{book}/{chapter}": (words, caps, pronouns) for book, chapter, words, caps, pronouns in rows}


def weights(db: sqlite3.Connection, p: Pass, ordered: list[str]) -> dict[str, float]:
    """What each unit costs a session of the pass."""
    if p.unit == "chapter":
        counts = chapter_counts(db)
        if p.name == "people":
            return {u: counts[u][0] + 4 * counts[u][1] for u in ordered}
        if p.name == "pronouns":
            return {u: counts[u][0] + 3 * counts[u][2] for u in ordered}
        if p.name == "headwords":
            from .layers.dictionary import unsettled

            found = unsettled(db)
            return {u: 2 + len(found.get(u, {})) for u in ordered}
        return {u: counts[u][0] for u in ordered}
    if p.unit == "entities":
        from .layers import LAYERS

        layer = LAYERS["entities"]
        counts = chapter_counts(db)
        return {u: sum(counts[f"{b}/{c}"][0] for b, c in layer.chapters(db, u)) or p.target for u in ordered}
    if p.unit == "headword":
        from .layers.dictionary import headword_of

        uses = dict(db.execute("select headword_id, count(*) from word_headword group by headword_id"))
        return {u: 10 + min(uses.get(headword_of(db, u), 0), 40) for u in ordered}
    if p.unit == "edition chapter":
        from .layers.dictionary import ORIGINAL, MACULA_SENSE, meaningless

        skipped = ",".join(str(id) for id in meaningless(db)) or "0"
        rows = db.execute(
            f"select w.edition_id, w.book_id, w.chapter, count(*) from word w join word_headword wh on wh.word_id = w.id "
            f"where wh.headword_id not in ({skipped}) and (w.edition_id not in ({','.join('?' * len(ORIGINAL))}) or not {MACULA_SENSE.format(word='w.id')}) "
            f"group by w.edition_id, w.book_id, w.chapter",
            ORIGINAL,
        )
        found = {f"{edition}/{book}/{chapter}": count for edition, book, chapter, count in rows}
        return {u: 20 + found.get(u, 0) for u in ordered}
    kinds = db.execute("select count(*) from summary_kind").fetchone()[0]
    chapters = {}
    for scope in chapter_scopes(db):
        book = split_chapter(scope)[0]
        chapters[book] = chapters.get(book, 0) + 1
    return {u: chapters.get(u, 1) * kinds for u in ordered}


def book_of(p: Pass, unit: str) -> str:
    if p.unit == "edition chapter":
        return unit.split("/")[1]
    return unit.split("/")[0]


def work_of(db: sqlite3.Connection, p: Pass, unit: str) -> str:
    if p.unit == "headword":
        return "en" if unit.startswith("en/") else "original"
    if p.unit == "entities" and unit == "scripture":
        return ""
    book = book_of(p, unit)
    return db.execute("select work_id from book where id = ?", (book,)).fetchone()[0]


def cut(db: sqlite3.Connection, p: Pass, ordered: list[str], weight: dict[str, float]) -> list[list[str]]:
    """Units cut into batches near the pass's target, ending early at a book's end when close, and never crossing from one work to the next."""
    batches: list[list[str]] = []
    groups: list[list[str]] = []
    for unit in ordered:
        if groups and work_of(db, p, groups[-1][-1]) == work_of(db, p, unit):
            groups[-1].append(unit)
        else:
            groups.append([unit])
    for group in groups:
        total = sum(weight[u] for u in group)
        target = total / max(1, round(total / p.target))
        current, size = [], 0.0
        for i, unit in enumerate(group):
            current.append(unit)
            size += weight[unit]
            book_ends = i + 1 == len(group) or book_of(p, group[i + 1]) != book_of(p, unit)
            if size >= target or (book_ends and size >= target * (1 - SNAP)):
                batches.append(current)
                current, size = [], 0.0
        if current:
            if batches and size < target / 2 and work_of(db, p, batches[-1][0]) == work_of(db, p, current[0]):
                batches[-1] += current
            else:
                batches.append(current)
    return batches


# Describing units


def describe(db: sqlite3.Connection, p: Pass, first: str, last: str) -> str:
    """The units a session covers, as people write them: "Alma 1–9"."""
    from .layers import LAYERS

    if p.unit == "chapter":
        a, b = split_chapter(first), split_chapter(last)
        if a == b:
            return reference(db, *a)
        if a[0] == b[0]:
            return f"{reference(db, *a)}–{b[1]}"
        return f"{reference(db, *a)} – {reference(db, *b)}"
    if p.unit == "entities":
        from .layers.entities import split_scope

        layer = LAYERS["entities"]
        if first == last:
            return layer.label(db, first)
        (book, low, _), (other, _, high) = split_scope(first), split_scope(last)
        if book == other and low is not None:
            return f"{reference(db, book, low)}–{high}"
        start = layer.label(db, first) if low is None else reference(db, book, low)
        end = layer.label(db, last) if high is None else f"{reference(db, other, high)}"
        return f"{start} – {end}"
    if p.unit == "book":
        return book_name(db, first) if first == last else f"{book_name(db, first)} – {book_name(db, last)}"
    return first if first == last else f"{first} – {last}"


# The plan


def make(db: sqlite3.Connection) -> list[Session]:
    """Every session of the run, writer sessions of each pass followed by its reviews, in the order they should start."""
    from .layers import LAYERS

    sessions: list[Session] = []
    for p in PASSES:
        ordered = units(db, p)
        if not ordered:
            continue
        batches = cut(db, p, ordered, weights(db, p, ordered))
        width = len(str(len(batches)))
        ids = [f"{p.name}-{n:0{max(3, width)}d}" for n in range(1, len(batches) + 1)]
        for n, batch in enumerate(batches):
            after = list(p.after)
            if n and (p.chained == "all" or (p.chained == "book" and book_of(p, batch[0]) == book_of(p, batches[n - 1][-1]))):
                after.append(ids[n - 1])
            sessions.append(Session(ids[n], p.name, p.model, p.layers, batch[0], batch[-1], describe(db, p, batch[0], batch[-1]), tuple(after)))
        for n in range(0, len(batches), REVIEW_SPAN):
            part = batches[n:n + REVIEW_SPAN]
            first, last = part[0][0], part[-1][-1]
            sessions.append(Session(f"review-{p.name}-{n // REVIEW_SPAN + 1}", p.name, "opus", p.layers, first, last, describe(db, p, first, last), (f"{p.name}:*",)))
    return sessions


def write(sessions: list[Session], path: Path):
    with open(path, "w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out, delimiter="\t", lineterminator="\n")
        writer.writerow(COLUMNS)
        for s in sessions:
            writer.writerow((s.id, s.pass_name, s.model, ",".join(s.layers), s.first, s.last, s.covers, " ".join(s.after)))


def load(path: Path) -> list[Session]:
    if not path.exists():
        raise Rejected(f"{path.name} does not exist. Cut it with: python3 -m bomnerds.agent plan")
    with open(path, newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
    return [Session(r["session"], r["pass"], r["model"], tuple(r["layers"].split(",")), r["from"], r["to"], r["covers"], tuple(r["after"].split())) for r in rows]


def find(session_id: str) -> tuple[Session, list[Session]]:
    """A session, with every session of the plan."""
    sessions = load(PLAN)
    for s in sessions:
        if s.id == session_id:
            return s, sessions
    raise Rejected(f"no session {session_id!r} in {PLAN.name}")


def waiting_on(session: Session, sessions: list[Session]) -> list[str]:
    """The sessions this one waits for that are not done."""
    found = []
    for token in session.after:
        if token.endswith(":*"):
            name = token[:-2]
            review = name.startswith("review-")
            members = [s for s in sessions if s.pass_name == name.removeprefix("review-") and s.review == review]
        else:
            members = [s for s in sessions if s.id == token]
        found += [s.id for s in members if not s.done()]
    return found


def state(db: sqlite3.Connection, session: Session, sessions: list[Session]) -> str:
    if session.done():
        return "done"
    blocking = waiting_on(session, sessions)
    if blocking:
        return f"waiting for {blocking[0]}" + (f" and {len(blocking) - 1} more" if len(blocking) > 1 else "")
    if not session.review:
        from .layers import LAYERS

        stored = sum(Job(LAYERS[name], scope).settled() is not None for name in session.layers for scope in session_scopes(db, session, name))
        if stored:
            return f"started: {stored} sections stored"
    return "ready"


def sampled(db: sqlite3.Connection, session: Session) -> list[str]:
    """The units a review reads in full: every REVIEW_SPAN-th unit of the pass."""
    p = BY_NAME[session.pass_name]
    ordered = units(db, p)
    covered = ordered[ordered.index(session.first): ordered.index(session.last) + 1]
    return [u for u in covered if ordered.index(u) % REVIEW_SPAN == 0]


def covered_units(db: sqlite3.Connection, session: Session) -> list[str]:
    ordered = units(db, BY_NAME[session.pass_name])
    return ordered[ordered.index(session.first): ordered.index(session.last) + 1]
