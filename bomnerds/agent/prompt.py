"""The text a session reads to answer one layer for every scope of its batch."""

import json
import sqlite3

from ..passages import chapter_span, english_edition, reference
from .jobs import CLI, Job, Jobs, already, line
from .layer import JSON_LINES, Layer
from .show import compact, show

POINTING = """## Pointing at text

Point at words by verse and quote. Copy the quote exactly from the verse. The CLI finds the words, so never count them.
Write verse references the way people do: `1 Nephi 3:7`, `D&C 76:22`. A passage takes one of these shapes:

{ "verse": "1 Nephi 3:7", "quote": "Nephi" }                  words inside one verse
{ "verse": "1 Nephi 3:7", "quote": "I", "in": "I will go" }   words that appear more than once in the verse: `in` is longer words that appear once and hold the quote once
{ "verse": "1 Nephi 3:7" }                                    a whole verse
{ "from": "Alma 32:21", "to": "Alma 32:43" }                  whole verses
{ "from": "Mosiah 2:9", "to": "Mosiah 5:15", "starts": "My brethren", "ends": "Amen" }   starting and ending partway through verses
{ "chapter": "Alma 32" }                                      a whole chapter

"starts" and "ends" take "starts_in" and "ends_in" the way "quote" takes "in", when their words appear more than once in the verse."""

UNSURE = "End a line with ? when you are unsure of it. It is stored, and the pass's review checks it."

UNLISTED = """When a name, speaker, listener, or other entity this answer needs is not on the list, write a line for it in its chapter's section, and leave it out of every other line:

unlisted | 4:35 | Zoram | person | Servant of Laban who joins Nephi.

That is the chapter and verse, the words that name it, its type, and one line saying who or what it is. The pass's review adds it and tags it."""


def prompt(db: sqlite3.Connection, session, work: list[tuple[Layer, list[str], str]]) -> str:
    """One prompt for every layer of a session: work holds each layer with its scopes still to answer and its answer file, in order."""
    layers = [layer for layer, _, _ in work]
    points = any(layer.points for layer in layers)
    names = ", ".join(layer.name for layer in layers)
    sections = [
        f"# Session {session.id}: {names}, {session.covers}",
        "You are tagging scripture for bom-nerds, a free study dataset. Everything you need is in this prompt.",
        steps(db, session, work),
    ]
    for layer, scopes, path in work:
        sections.append(f"## {layer.name}\n\n" + layer.instructions.strip() + "\n\n### Answer format\n\n" + layer.format)
    if points and any(layer.format == JSON_LINES for layer in layers if layer.points):
        sections.append(POINTING)
    sections.append("## Unsure answers" + (" and missing entities" if points else "") + "\n\n" + UNSURE + ("\n\n" + UNLISTED if points else ""))
    for layer, scopes, _ in work:
        preamble = layer.preamble(db, scopes)
        if preamble:
            sections.append(preamble)
    if points:
        every = [scope for layer, scopes, _ in work if layer.points for scope in scopes]
        first = next(layer for layer in layers if layer.points)
        sections.append("## Entities\n\nPick entities from this list. It holds every entity named or tagged in these chapters.\n\n" + entity_list(db, first, every))
    sections += parts(db, work)
    return "\n\n".join(sections) + "\n"


def steps(db: sqlite3.Connection, session, work: list[tuple[Layer, list[str], str]]) -> str:
    lines = ["## What to do", "", "Answer each layer in its own file, in this order. Submit a layer before you start the next, because each can read what the one before stored.", ""]
    for n, (layer, scopes, path) in enumerate(work, 1):
        lines.append(f"{n}. {layer.name}: write {path}, then run `{CLI} submit {session.id} {layer.name}`.")
    first_layer, scopes, _ = work[0]
    lines += [
        "",
        f"An answer file has one section for each heading below, opened by the heading line exactly as written here, such as \"# {first_layer.label(db, scopes[0])}\". "
        "Keep the heading of a section with nothing to answer, and leave it empty.",
        "",
        "Submit stores every section that passes and lists the problems in the rest. Fix those sections in the same file and submit again. Sections already stored are skipped.",
    ]
    ordered = [layer.name for layer, _, _ in work if layer.ordered]
    if ordered:
        lines.append(f"{' and '.join(ordered).capitalize()} store sections in order, and stop at the first one with a problem, because each section reads the one before it.")
    lines += ["", f"When every layer is stored, run `{CLI} done {session.id}`."]
    return "\n".join(lines)


def parts(db: sqlite3.Connection, work: list[tuple[Layer, list[str], str]]) -> list[str]:
    """Each heading's section: its chapters' text once, then what each layer adds for it."""
    found: dict[str, list[tuple[Layer, str]]] = {}
    for layer, scopes, _ in work:
        for scope in scopes:
            found.setdefault(layer.label(db, scope), []).append((layer, scope))
    shown: set[tuple[str, int]] = set()
    sections = []
    for label, members in found.items():
        part = [f"# {label}"]
        seen = members[0][0].seen()
        for layer, scope in members:
            for book, chapter in layer.text_chapters(db, scope):
                if (book, chapter) in shown:
                    continue
                shown.add((book, chapter))
                part.append(show(db, book, chapter, layers=seen, level=2))
        for layer, scope in members:
            batch = tuple(s for other, scopes, _ in work if other is layer for s in scopes)
            extra = layer.extra(db, Jobs, scope, batch)
            if extra:
                part.append(extra)
            taken = layer.already_shown(db, already(db, Job(layer, scope)))
            if taken:
                part.append(f"## Already stored for {layer.name}\n\nLeave these out of your answer.\n\n" + "\n".join(compact(t) for t in taken))
        if len(part) == 1:
            part.append("The text is shown above.")
        sections.append("\n\n".join(part))
    return sections


def entity_list(db: sqlite3.Connection, layer: Layer, scopes: list[str]) -> str:
    """Every entity named or tagged in the scopes' chapters, and every entity for all of scripture other than topics."""
    from .layers.names import book_entities

    chapters = list(dict.fromkeys(c for scope in scopes for c in layer.text_chapters(db, scope)))
    ids: set[str] = set()
    for book, chapter in chapters:
        first, last = chapter_span(db, english_edition(db, book), book, chapter)
        ids |= {id for id, _, _, _ in book_entities(db, book, chapter)}
        ids |= {id for (id,) in db.execute("select entity_id from mention where first_word_id between ? and ?", (first, last))}
        ids |= {id for (id,) in db.execute("select speaker_id from speech where first_word_id <= ? and last_word_id >= ?", (last, first))}
        ids |= {id for (id,) in db.execute(
            "select l.entity_id from speech_listener l join speech s on s.id = l.speech_id where s.first_word_id <= ? and s.last_word_id >= ?", (last, first)
        )}
    ids |= {id for (id,) in db.execute("select id from entity e where type_id <> 'topic' and not exists (select 1 from entity_book b where b.entity_id = e.id)")}
    rows = db.execute(
        "select e.id, e.type_id, e.name, e.description, group_concat(n.name, '|') from json_each(?) j join entity e on e.id = j.value "
        "left join entity_name n on n.entity_id = e.id and n.name <> e.name group by e.id order by e.name, e.id",
        (json.dumps(sorted(ids)),),
    )
    lines = []
    for id, type_id, name, description, others in rows:
        also = f" Also: {', '.join(sorted(set(others.split('|'))))}." if others else ""
        lines.append(f"{id} ({type_id}) {name}. {description}{also}".rstrip())
    return "\n".join(lines) or "No entities yet."


def job_text(db: sqlite3.Connection, job: Job) -> str:
    """What a prompt shows for one job: its section, with the layer's lists every batch shares."""
    preamble = job.layer.preamble(db, [job.scope])
    return "\n\n".join(([preamble] if preamble else []) + parts(db, [(job.layer, [job.scope], "")]))
