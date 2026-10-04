"""A pass's review: one session that settles what writers flagged, what the scripts found, and the names with no entity,
then reads a fixed sample of the pass's units in full. Its fixes edit stored answers, so nothing runs again.

A review's answer has a section per stored answer it changes, headed "<layer>: <heading>", whose lines start with "- " to remove a
stored line and "+ " to add one. A "new entities" section adds entities, and an "error rates" section counts what the sample got wrong.
"""

import json
import sqlite3

from ..passages import Rejected, english_edition, parse_reference, reference, verse_text
from . import checks
from . import plan as plans
from .jobs import CLI, Job, Jobs, line, repeats
from .layer import Layer, Problems, kinds, split_chapter
from .plan import Session
from .prompt import POINTING, entity_list

NEW_ENTITIES = "new entities"
ERROR_RATES = "error rates"

INTRO = """You are reviewing the {pass_name} pass for {covers}. One writer answered each section, and the rules they followed are below.
Work through this prompt in order:

1. Flagged lines: the writer was unsure. Keep each one, fix it, or remove it.
2. Script findings: each is something to look at, not a proven error. Fix what is wrong.
3. Unlisted names: the writer found no entity for these. Pick the entity if it is on the list after all. Otherwise add it under "new entities". Then tag its words.
4. Sample sections: read each in full against its text, and fix every error you find. Count what you check and what was wrong.

Fix only what is wrong. Leave what is right as it is."""

FIXING = """## Fixing

Write your fixes to {path}. Each section is headed by the stored answer it changes, exactly as this prompt heads it, such as "# names: 1 Nephi 3".
A line starting with "- " removes a stored line: copy it exactly from the stored lines shown. A line starting with "+ " adds one, written the way the rules below say.

# names: 1 Nephi 3
- {{"entity": "lehi", "passage": {{"verse": "1 Nephi 3:4", "quote": "Laban"}}}}
+ {{"entity": "laban", "passage": {{"verse": "1 Nephi 3:4", "quote": "Laban"}}}}

To add an entity, write one JSON object per line under "# new entities", with "verse": a verse that names it. An entity named only in the Bible is recorded in that book.

# new entities
{{"id": "zoram-servant-of-laban", "type": "person", "name": "Zoram", "other_names": [], "description": "Servant of Laban who joins Nephi.", "verse": "1 Nephi 4:35"}}

Last, count the sample sections: for each layer, how many lines you checked and how many were wrong.

# error rates
names 3/212
speakers 0/14

Then run, from the repository root:

{cli} submit {session}

It stores every fix that passes and lists the problems in the rest. Fix those and run it again: fixes already stored are left out of the next run, so remove them from the file first. When every fix is stored, finish with:

{cli} done {session}"""


def stored_lines(db: sqlite3.Connection, layer: Layer, scope: str) -> str:
    settled = Job(layer, scope).settled()
    return "\n".join(line(item) for item in settled or []) or "Nothing stored."


def verse_line(db: sqlite3.Connection, layer: Layer, scope: str, flagged: str) -> str:
    """A flagged line with the text of the verse it points at, when the line names one."""
    if layer.scope != "chapter" or not flagged.split():
        return flagged
    book, chapter = split_chapter(scope)
    numbers = flagged.split()[0].split(":")
    if len(numbers) != 2 or numbers[0] != str(chapter) or not numbers[1].isdigit():
        return flagged
    verse = int(numbers[1])
    return f"{flagged}\n    {reference(db, book, chapter, verse)}: {verse_text(db, english_edition(db, book), book, chapter, verse).strip()}"


def prompt(db: sqlite3.Connection, session: Session, path: str) -> str:
    from .layers import LAYERS
    from .show import show

    layers = [LAYERS[name] for name in session.layers]
    seen = tuple(dict.fromkeys(layers[0].seen() + session.layers))
    units = plans.covered_units(db, session)
    sample = set(plans.sampled(db, session))
    sections = [f"# Review {session.id}: {session.pass_name}, {session.covers}", INTRO.format(pass_name=session.pass_name, covers=session.covers)]
    sections.append(FIXING.format(path=path, cli=CLI, session=session.id))
    for layer in layers:
        sections.append(f"## The {layer.name} rules\n\n" + layer.instructions.strip())
        preamble = layer.preamble(db, plans.session_scopes(db, session, layer.name)[:1])
        if preamble:
            sections.append(preamble)
    if any(layer.points for layer in layers):
        sections.append(POINTING)

    attention: dict[tuple[str, str], list[str]] = {}
    flagged, unlisted = [], []
    for layer in layers:
        for scope in plans.session_scopes(db, session, layer.name):
            job = Job(layer, scope)
            for item in job.read("flagged") or []:
                flagged.append(f"# {layer.name}: {layer.label(db, scope)}\n{verse_line(db, layer, scope, item)}")
                attention.setdefault((layer.name, scope), [])
            for item in job.read("unlisted") or []:
                unlisted.append(f"# {layer.name}: {layer.label(db, scope)}\n{item['passage']['verse']}: \"{item['passage']['quote']}\", {item['type']}. {item['description']}")
                attention.setdefault((layer.name, scope), [])
    found = checks.findings(db, session.pass_name, units)
    for finding in found:
        attention.setdefault((finding.layer, finding.scope), [])
    sections.append("## Flagged lines\n\n" + ("\n\n".join(flagged) or "None."))
    sections.append("## Script findings\n\n" + ("\n\n".join(f"# {checks.heading(db, f)}\n{f.text}" for f in found) or "None."))
    sections.append("## Unlisted names\n\n" + ("\n\n".join(unlisted) or "None."))

    if any(layer.points for layer in layers):
        scopes = [scope for (name, scope) in attention if LAYERS[name].points] + [u for u in units if u in sample]
        chapter_layer = next(layer for layer in layers if layer.points)
        sections.append("## Entities\n\nEvery entity named or tagged in the sections below.\n\n" + entity_list(db, chapter_layer, [s for s in dict.fromkeys(scopes) if s in set(plans.session_scopes(db, session, chapter_layer.name))]))

    shown = set()
    parts = []
    for name, scope in attention:
        layer = LAYERS[name]
        if scope not in set(plans.session_scopes(db, session, name)):
            continue
        parts.append(f"# {name}: {layer.label(db, scope)}\n\nStored lines:\n\n{stored_lines(db, layer, scope)}")
        for book, chapter in layer.text_chapters(db, scope) if layer.scope == "chapter" else []:
            if (book, chapter) not in shown:
                shown.add((book, chapter))
                parts.append(show(db, book, chapter, layers=seen, level=2))
    sections.append("## Sections to settle\n\nThe stored lines and text of every section named above.\n\n" + ("\n\n".join(parts) or "None."))

    parts = []
    for unit in units:
        if unit not in sample:
            continue
        for layer in layers:
            for scope in plans.session_scopes(db, session, layer.name):
                if plans.unit_of(db, plans.BY_NAME[session.pass_name], layer.name, scope) != unit:
                    continue
                parts.append(f"# {layer.name}: {layer.label(db, scope)}\n\nStored lines:\n\n{stored_lines(db, layer, scope)}")
                for book, chapter in layer.text_chapters(db, scope):
                    if (book, chapter) not in shown:
                        shown.add((book, chapter))
                        parts.append(show(db, book, chapter, layers=seen, level=2))
                extra = layer.extra(db, Jobs, scope)
                if extra and not layer.points:
                    parts.append(extra)
    sections.append("## Sample sections\n\nRead each in full and fix every error.\n\n" + ("\n\n".join(parts) or "None."))
    return "\n\n".join(sections) + "\n"


def canonical(item) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def apply(db: sqlite3.Connection, session: Session, text: str) -> str:
    from .batch import sections
    from .layers import LAYERS

    given = sections(text)
    labels = {}
    for name in session.layers:
        layer = LAYERS[name]
        for scope in plans.session_scopes(db, session, name):
            labels[f"{name}: {layer.label(db, scope)}"] = (layer, scope)
    report, problems = [], []
    for heading, lines in given:
        if heading == NEW_ENTITIES:
            added, failed = add_entities(db, lines)
            if added:
                report.append(f"Added {len(added)} entities: {', '.join(added)}.")
            problems += failed
        elif heading == ERROR_RATES:
            try:
                write_rates(session, lines, session.layers)
                report.append("Recorded the error rates.")
            except Rejected as error:
                problems.append(f"# {ERROR_RATES}\n{error}")
        elif heading not in labels:
            problems.append(f"# {heading}\nno stored answer of this review is headed {heading!r}. Copy each heading exactly from the prompt")
    for name in session.layers:
        layer = LAYERS[name]
        edits = [(labels[h][1], lines) for h, lines in given if h in labels and labels[h][0] is layer]
        if not edits:
            continue
        groups = [edits] if layer.ordered else [[edit] for edit in edits]
        for group in groups:
            try:
                replace(db, layer, group)
                report.append(f"Fixed {', '.join(f'{name}: {layer.label(db, scope)}' for scope, _ in group)}.")
            except Rejected as error:
                problems.append("\n".join(f"# {name}: {layer.label(db, scope)}" for scope, _ in group) + f"\n{error}")
    if problems:
        report.append("These have problems. Fix them, remove what is already stored from the file, and submit again:\n\n" + "\n\n".join(problems))
    else:
        report.append(f"Every fix is stored. Finish with: {CLI} done {session.id}")
    return "\n\n".join(report)


def edited(db: sqlite3.Connection, layer: Layer, scope: str, lines: list[str]) -> list[dict]:
    """The stored items of a scope with a review's removals and additions applied."""
    problems = Problems(db)
    items = list(Job(layer, scope).settled() or [])
    present = [canonical(item) for item in items]
    removed, added = set(), []
    for number, text in enumerate(lines, 1):
        problems.at(f"line {number}")
        mark, _, body = text.partition(" ")
        if mark not in ("-", "+"):
            problems.add('start each line with "- " to remove a stored line or "+ " to add one')
            continue
        try:
            item = json.loads(body)
        except json.JSONDecodeError as error:
            problems.add(f"not a JSON object: {error.msg}")
            continue
        if mark == "-":
            if canonical(item) not in present:
                problems.add("this line is not stored. Copy it exactly from the stored lines")
            removed.add(canonical(item))
        else:
            added.append(item)
    problems.raise_any()
    return [item for item in items if canonical(item) not in removed] + added


def replace(db: sqlite3.Connection, layer: Layer, edits: list[tuple[str, list[str]]]):
    """Replace the stored answers of these scopes with their edited items, in one transaction, latest scope unstored first."""
    order = {scope: n for n, scope in enumerate(layer.scopes(db))}
    edits = sorted(edits, key=lambda edit: order[edit[0]])
    news = {scope: edited(db, layer, scope, lines) for scope, lines in edits}
    olds = {scope: layer.parse(db, scope, Job(layer, scope).settled() or []) for scope, _ in edits}
    results = {}
    try:
        with db:
            for scope, _ in reversed(edits):
                layer.unstore(db, scope, olds[scope])
                Jobs.pending[Job(layer, scope).id] = None
            for scope, _ in edits:
                tags = layer.parse(db, scope, news[scope])
                repeats(db, layer, tags)
                taken = set(layer.given(db, scope))
                clashes = [layer.render(db, t) for t in tags if t in taken]
                if clashes:
                    raise Rejected("these are already stored by another source, so leave them out:\n" + "\n".join(line(c) for c in clashes))
                layer.store(db, scope, tags)
                results[scope] = [layer.render(db, t) for t in tags]
                Jobs.pending[Job(layer, scope).id] = results[scope]
    except sqlite3.IntegrityError as error:
        raise Rejected(f"the fix breaks what later layers stored: {error}")
    finally:
        for scope, _ in edits:
            Jobs.pending.pop(Job(layer, scope).id, None)
    for scope, items in results.items():
        Job(layer, scope).write("settled", items)


def add_entities(db: sqlite3.Connection, lines: list[str]) -> tuple[list[str], list[str]]:
    """Add each new entity to the entities answer of the book that names it, or of all of scripture for a Bible book."""
    from .layers import LAYERS
    from .layers.entities import SCRIPTURE, Catalog, book_text, check_new, check_text, read_new, split_scope

    layer = LAYERS["entities"]
    added, problems = [], []
    for number, text in enumerate(lines, 1):
        found = Problems(db).at(f"new entity {number}")
        try:
            item = json.loads(text)
        except json.JSONDecodeError as error:
            problems.append(f"# {NEW_ENTITIES}\nline {number}: not a JSON object: {error.msg}")
            continue
        verse = item.pop("verse", None) if isinstance(item, dict) else None
        if not isinstance(verse, str):
            problems.append(f"# {NEW_ENTITIES}\nline {number}: add \"verse\": a verse that names it")
            continue
        try:
            book, chapter, _ = parse_reference(db, verse)
        except Rejected as error:
            problems.append(f"# {NEW_ENTITIES}\nline {number}: {error}")
            continue
        work = db.execute("select work_id from book where id = ?", (book,)).fetchone()[0]
        scope = SCRIPTURE if work == "bible" else next(s for s in layer.scopes(db) if split_scope(s)[0] == book and (split_scope(s)[1] is None or split_scope(s)[1] <= chapter <= split_scope(s)[2]))
        if scope == SCRIPTURE:
            item["books"] = [book]
        tag = read_new(found, item, kinds(db, "entity_type"))
        if tag:
            catalog = Catalog(db)
            check_new(found, catalog, tag, [])
            check_text(found, catalog, book_text(db, book, chapter, chapter), [(number, tag)], verse)
        if found.messages or tag is None:
            problems.append(f"# {NEW_ENTITIES}\n" + "\n".join(found.messages))
            continue
        job = Job(layer, scope)
        with db:
            layer.store(db, scope, [tag])
        job.write("settled", (job.settled() or []) + [layer.render(db, tag)])
        added.append(tag.id)
    return added, problems


def write_rates(session: Session, lines: list[str], layers: tuple[str, ...]):
    rates = {}
    for text in lines:
        name, _, counts = text.partition(" ")
        wrong, _, checked = counts.strip().partition("/")
        if name not in layers or not wrong.isdigit() or not checked.isdigit() or int(wrong) > int(checked):
            raise Rejected(f'write "<layer> <wrong>/<checked>" for each of {", ".join(layers)}, such as "names 3/212"')
        rates[name] = [int(wrong), int(checked)]
    (session.folder / "rates.json").write_text(json.dumps(rates) + "\n", encoding="utf-8")
