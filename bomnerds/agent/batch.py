"""Runs one session of the plan: writes its prompt for each layer, stores its answers, and marks it done.

A session's prompts and answers live in jobs/sessions/<session>/: <layer>.md is the prompt, <layer>.txt the answer.
A review writes review.txt, which fixes stored answers and adds entities, and its error counts go to rates.json.
"""

import sqlite3
from pathlib import Path

from ..passages import Rejected, reference
from . import plan as plans
from .jobs import CLI, Job, check
from .jobs import reset as reset_job
from .jobs import submit as submit_job
from .layer import Layer, Problems, kinds, split_chapter, verse_number
from .plan import Session


def layer_of(session: Session, name: str) -> Layer:
    from .layers import LAYERS

    if name not in session.layers:
        raise Rejected(f"{session.id} answers {', '.join(session.layers)}, not {name!r}")
    return LAYERS[name]


def ready(db: sqlite3.Connection, session: Session, sessions: list[Session]):
    blocking = plans.waiting_on(session, sessions)
    if blocking:
        raise Rejected(f"{session.id} waits for {', '.join(blocking[:5])}" + (f" and {len(blocking) - 5} more" if len(blocking) > 5 else ""))


def answer_path(session: Session, name: str) -> Path:
    return session.folder / f"{name}.txt"


def relative(path: Path) -> str:
    from ..sources import ROOT

    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def write_prompt(db: sqlite3.Connection, session_id: str) -> str:
    """Write the prompt for every layer of a session still to answer, or for a review, and say where it is."""
    session, sessions = plans.find(session_id)
    ready(db, session, sessions)
    session.folder.mkdir(parents=True, exist_ok=True)
    path = session.folder / "prompt.md"
    if session.review:
        from .review import prompt as review_prompt

        path.write_text(review_prompt(db, session, relative(session.folder / "review.txt")), encoding="utf-8")
    else:
        from .prompt import prompt

        work = []
        for name in session.layers:
            layer = layer_of(session, name)
            scopes = [scope for scope in plans.session_scopes(db, session, name) if Job(layer, scope).settled() is None]
            if scopes:
                work.append((layer, scopes, relative(answer_path(session, name))))
        if not work:
            return f"Every section of {session.id} is stored. Finish with: {CLI} done {session.id}"
        path.write_text(prompt(db, session, work), encoding="utf-8")
    lines = path.read_text(encoding="utf-8").count("\n")
    return f"Wrote {relative(path)}, {lines:,} lines. Read all of it, then follow it."


def sections(text: str) -> list[tuple[str, list[str]]]:
    """An answer file as (heading, lines) for each section."""
    found: list[tuple[str, list[str]]] = []
    stray = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("# "):
            found.append((stripped[2:].strip(), []))
        elif stripped and found:
            found[-1][1].append(stripped)
        elif stripped:
            stray.append(stripped)
    if stray:
        raise Rejected(f"these lines come before the first heading, so they belong to no section: {stray[0]}")
    twice = sorted({heading for heading, _ in found if [h for h, _ in found].count(heading) > 1})
    if twice:
        raise Rejected(f"each heading opens one section, but these open more than one: {', '.join(twice)}")
    return found


def read_answer(path: Path) -> str:
    if not path.exists():
        raise Rejected(f"{relative(path)} does not exist. Write your answer there first")
    return path.read_text(encoding="utf-8")


def unlisted(db: sqlite3.Connection, scope: str, lines: list[str]) -> tuple[list[dict], list[str]]:
    """The unlisted lines of a chapter section as entities to add, and the section's other lines."""
    book, chapter = split_chapter(scope)
    problems = Problems(db)
    found, rest = [], []
    types = kinds(db, "entity_type")
    for number, text in enumerate(lines, 1):
        if not text.lower().startswith("unlisted"):
            rest.append(text)
            continue
        problems.at(f"unlisted line {number}")
        parts = [part.strip() for part in text.split("|")]
        if len(parts) != 5 or not all(parts[1:]):
            problems.add('write "unlisted | verse | words | type | description", such as "unlisted | 4:35 | Zoram | person | Servant of Laban who joins Nephi."')
            continue
        _, key, words, type_id, description = parts
        verse = verse_number(problems, key, chapter)
        if verse is None:
            continue
        passage = {"verse": reference(db, book, chapter, verse), "quote": words}
        if problems.passage(passage, within=scope) is None:
            continue
        if type_id not in types:
            problems.add(f"type {type_id!r} is not one of: {', '.join(types)}")
            continue
        found.append({"passage": passage, "type": type_id, "description": description})
    problems.raise_any()
    return found, rest


def submit(db: sqlite3.Connection, session_id: str, name: str | None) -> str:
    session, sessions = plans.find(session_id)
    ready(db, session, sessions)
    if session.review:
        from .review import apply

        return apply(db, session, read_answer(session.folder / "review.txt"))
    if name is None:
        raise Rejected(f"name the layer: {' or '.join(session.layers)}")
    layer = layer_of(session, name)
    scopes = plans.session_scopes(db, session, name)
    labels = {layer.label(db, scope): scope for scope in scopes}
    given = sections(read_answer(answer_path(session, name)))
    unknown = [heading for heading, _ in given if heading not in labels]
    if unknown:
        raise Rejected(f"no section of {session.id} {name} is headed {unknown[0]!r}. Copy each heading exactly from the prompt")
    answers = dict(given)
    stored, skipped, problems, missing = [], [], [], []
    for scope in scopes:
        job = Job(layer, scope)
        label = layer.label(db, scope)
        if job.settled() is not None:
            skipped.append(label)
            continue
        if label not in answers:
            missing.append(label)
            if layer.ordered:
                break
            continue
        try:
            store_section(db, layer, scope, answers[label])
            stored.append(label)
        except Rejected as error:
            problems.append(f"# {label}\n{error}")
            if layer.ordered:
                break
    left = [layer.label(db, scope) for scope in scopes if Job(layer, scope).settled() is None]
    report = []
    if stored:
        report.append(f"Stored {len(stored)} sections: {', '.join(stored)}.")
    if skipped:
        report.append(f"Already stored, so skipped: {len(skipped)} sections.")
    if problems:
        report.append("These sections have problems. Fix them and submit again:\n\n" + "\n\n".join(problems))
    if missing:
        report.append(f"No section for: {', '.join(missing)}. Add them and submit again.")
    if not left:
        rest = [other for other in session.layers if other != name and any(Job(layer_of(session, other), s).settled() is None for s in plans.session_scopes(db, session, other))]
        then = f"Next, answer {rest[0]} and submit it." if rest else f"Every layer is stored. Finish with: {CLI} done {session.id}"
        report.append(f"Every section of {name} is stored. {then}")
    elif layer.ordered and (problems or missing):
        report.append(f"Still to store, in order: {', '.join(left)}.")
    return "\n\n".join(report)


def store_section(db: sqlite3.Connection, layer: Layer, scope: str, lines: list[str]):
    """Check one section and store it, or raise Rejected with every problem in it."""
    found = []
    if layer.entities and layer.scope == "chapter":
        found, lines = unlisted(db, scope, lines)
    reading = layer.read(db, scope, lines)
    reading.unlisted = found
    messages = layer.complete(db, scope, reading)
    if messages:
        try:
            check(db, Job(layer, scope), reading.items)
        except Rejected as error:
            messages = [str(error)] + messages
        raise Rejected("\n".join(messages))
    submit_job(db, Job(layer, scope), reading.items, reading.flagged, found)


def done(db: sqlite3.Connection, session_id: str) -> str:
    session, sessions = plans.find(session_id)
    if not session.review:
        left = [f"{name} {layer_of(session, name).label(db, scope)}" for name in session.layers for scope in plans.session_scopes(db, session, name) if Job(layer_of(session, name), scope).settled() is None]
        if left:
            raise Rejected(f"{session.id} still has sections to store: {', '.join(left[:10])}" + (f" and {len(left) - 10} more" if len(left) > 10 else ""))
    session.folder.mkdir(parents=True, exist_ok=True)
    (session.folder / "done").write_text("", encoding="utf-8")
    return f"{session.id} is done."


def reset(db: sqlite3.Connection, session_id: str) -> str:
    """Delete everything a writer session stored, latest first, so it runs again from the start."""
    session, _ = plans.find(session_id)
    if session.review:
        raise Rejected("a review's fixes replace what writers stored, so they stay. Run the review again to continue it")
    deleted = 0
    for name in reversed(session.layers):
        layer = layer_of(session, name)
        for scope in reversed(plans.session_scopes(db, session, name)):
            deleted += reset_job(db, Job(layer, scope))
    if session.folder.exists():
        for path in session.folder.iterdir():
            path.unlink()
    return f"{session.id}: reset, {deleted} tags deleted."
