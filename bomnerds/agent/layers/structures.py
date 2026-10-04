"""Literary structures: chiasmus, parallelism, lists, and acrostics, each with ordered parts that can hold parts."""

import sqlite3
from collections import defaultdict

from ...passages import chapter_span
from ..layer import Layer, Problems, chapter_name, kinds, passage_of, scope_span

INSTRUCTIONS = """
Find every literary structure that starts in this chapter. Kinds:

- chiasm: ideas laid out and then repeated in reverse order: A, B, C, C', B', A'.
- parallelism: lines in matching form that say the same thing again in other words, or say its opposite.
- list: a run of items of one kind, such as names, commandments, or blessings.
- acrostic: lines or stanzas whose first letters follow the alphabet, as in Psalm 119.

Rules:

- Tag a structure only where the pattern is plain in the words. Many chapters have none, and then the answer is [].
- A structure starts in this chapter and may run on into later chapters of the same book. Read them with show.
- A structure has two or more parts, in reading order. Each part sits inside the structure, and parts side by side never share words.
- A part can hold two or more parts of its own under "parts", each inside it.
- Label chiasm parts with letters on the way in and the same letter with ' on the way back: A, B, C, C', B', A'. Label the parts of every other kind 1, 2, 3. A part inside another adds a number to its parent's label: "2.1", "2.2". Labels are unique within a structure.
- In a chiasm, each part on the way back names its partner with "pairs_with". A part pairs with one other part at most. Only chiasm parts pair.

Answer with one object per structure:

{ "kind": "chiasm", "passage": { "verse": "Isaiah 6:10" }, "parts": [
  { "label": "A", "passage": { "verse": "Isaiah 6:10", "quote": "Make the heart of this people fat" } },
  { "label": "B", "passage": { "verse": "Isaiah 6:10", "quote": "make their ears heavy" } },
  { "label": "C", "passage": { "verse": "Isaiah 6:10", "quote": "shut their eyes" } },
  { "label": "C'", "passage": { "verse": "Isaiah 6:10", "quote": "see with their eyes" }, "pairs_with": "C" },
  { "label": "B'", "passage": { "verse": "Isaiah 6:10", "quote": "hear with their ears" }, "pairs_with": "B" },
  { "label": "A'", "passage": { "verse": "Isaiah 6:10", "quote": "understand with their heart" }, "pairs_with": "A" }
] }
"""

# A tag is one structure: (kind, first, last, parts). A part is (first, last, label, pairs_with, parts), parts in reading order.
# pairs_with is the label of the earlier part of a pair, held by the later one.


class Structures(Layer):
    name = "structures"
    step = 7
    sees = ()
    instructions = INSTRUCTIONS

    def parse(self, db, scope, answer):
        problems = Problems(db)
        allowed = kinds(db, "structure_kind")
        start, end = scope_span(db, scope)
        tags, seen = [], {}
        for number, item in enumerate(problems.items(answer), 1):
            where = f"item {number}"
            problems.at(where)
            if not problems.fields(item, ("kind", "passage", "parts")):
                continue
            kind = problems.kind(item["kind"], allowed)
            span = problems.passage(item["passage"])
            if span and not start <= span[0] <= end:
                problems.add(f"a structure must start in {chapter_name(db, scope)}")
                span = None
            if kind is None or span is None:
                continue
            parts = read_parts(problems, item["parts"], span, where)
            if parts is None or not pairs_hold(problems.at(where), kind, parts):
                continue
            if (kind, *span) in seen:
                problems.add(f"item {seen[(kind, *span)]} is a {kind} over the same passage. Make them one structure")
                continue
            seen[(kind, *span)] = number
            tags.append((kind, *span, paired(parts)))
        problems.raise_any()
        return tags

    def render(self, db, tag):
        kind, first, last, parts = tag
        return {"kind": kind, "passage": passage_of(db, first, last), "parts": [render_part(db, p) for p in parts]}

    def store(self, db, scope, tags):
        for kind, first, last, parts in tags:
            structure = db.execute("insert into structure (kind_id, first_word_id, last_word_id) values (?, ?, ?)", (kind, first, last)).lastrowid
            ids = {}
            for position, ((a, b, label, pairs_with, _), parent) in enumerate(walk(parts), 1):
                ids[label] = db.execute(
                    "insert into structure_part (structure_id, parent_id, position, label, pairs_with_id, first_word_id, last_word_id) values (?, ?, ?, ?, ?, ?, ?)",
                    (structure, ids.get(parent), position, label, ids.get(pairs_with), a, b),
                ).lastrowid

    def unstore(self, db, scope, tags):
        for kind, first, last, _ in tags:
            match = (kind, first, last)
            db.execute("delete from structure_part where structure_id in (select id from structure where kind_id = ? and first_word_id = ? and last_word_id = ?)", match)
            db.execute("delete from structure where kind_id = ? and first_word_id = ? and last_word_id = ?", match)

    def shown(self, db, edition, book_id, chapter):
        first, last = chapter_span(db, edition, book_id, chapter)
        return [self.render(db, tag) for tag in stored(db, first, last)]


def stored(db: sqlite3.Connection, first: int, last: int) -> list[tuple]:
    """Every structure holding words between the two, as tags."""
    structures = list(db.execute("select id, kind_id, first_word_id, last_word_id from structure where first_word_id <= ? and last_word_id >= ? order by first_word_id, last_word_id desc, id", (last, first)))
    labels, children = {}, defaultdict(list)
    rows = db.execute(
        f"select id, structure_id, parent_id, position, label, pairs_with_id, first_word_id, last_word_id from structure_part where structure_id in ({','.join('?' * len(structures))}) order by position",
        [s[0] for s in structures],
    )
    for id, structure, parent, _, label, pairs_with, a, b in rows:
        labels[id] = label
        children[("part", parent) if parent else ("structure", structure)].append((id, a, b, label, pairs_with))

    def build(key):
        return tuple((a, b, label, labels.get(pairs_with), build(("part", id))) for id, a, b, label, pairs_with in children[key])

    return [(kind, a, b, build(("structure", id))) for id, kind, a, b in structures]


def read_parts(problems: Problems, items, outer: tuple[int, int], where: str, path: str = "") -> tuple | None:
    """Parts as (first, last, label, named partner, parts) in reading order, or None after adding every problem found."""
    if not isinstance(items, list) or len(items) < 2 or not all(isinstance(item, dict) for item in items):
        problems.at(where).add('"parts" must be a list of two or more part objects')
        return None
    found, clean = [], True
    for number, item in enumerate(items, 1):
        label = f"{where.split(',')[0]}, part {path}{number}"
        problems.at(label)
        if not problems.fields(item, ("label", "passage"), ("pairs_with", "parts")):
            clean = False
            continue
        name, partner = item["label"], item.get("pairs_with")
        if not isinstance(name, str) or not name.strip():
            problems.add('"label" must be text, such as "A" or "1"')
            name = None
        if partner is not None and (not isinstance(partner, str) or not partner.strip()):
            problems.add('"pairs_with" must be the label of another part')
            partner = None
        span = problems.passage(item["passage"])
        if span and not outer[0] <= span[0] <= span[1] <= outer[1]:
            problems.add(f"the part must sit inside its {'parent part' if path else 'structure'}")
            span = None
        inner = read_parts(problems, item["parts"], span, label, f"{path}{number}.") if "parts" in item and span else ()
        if name is None or span is None or inner is None:
            clean = False
            continue
        found.append((*span, name, partner, inner))
    found.sort(key=lambda part: (part[0], -part[1]))
    problems.at(where)
    for before, after in zip(found, found[1:]):
        if after[0] <= before[1]:
            problems.add(f"the parts {before[2]} and {after[2]} share words. Parts side by side never overlap")
            clean = False
    return tuple(found) if clean else None


def pairs_hold(problems: Problems, kind: str, parts: tuple) -> bool:
    """Whether labels are unique and every pairs_with names another part of the structure, each part pairing once."""
    labels = [part[2] for part, _ in walk(parts)]
    clean = True
    for label in sorted({l for l in labels if labels.count(l) > 1}):
        problems.add(f"the label {label!r} is used {labels.count(label)} times. Labels are unique within a structure")
        clean = False
    pairs = set()
    for part, ancestors in lineage(parts):
        label, partner = part[2], part[3]
        if partner is None:
            continue
        if kind != "chiasm":
            problems.add(f"part {label} has pairs_with, but only chiasm parts pair")
        elif partner == label:
            problems.add(f"part {label} pairs with itself. Name its partner")
        elif partner not in labels:
            problems.add(f"part {label} pairs with {partner!r}, which is not a label in this structure")
        elif partner in ancestors or partner in descendants(part):
            problems.add(f"part {label} pairs with {partner}, but one holds the other. Pair parts that stand apart")
        else:
            pairs.add(frozenset((label, partner)))
            continue
        clean = False
    for label in dict.fromkeys(labels):
        partners = sorted(next(iter(pair - {label})) for pair in pairs if label in pair)
        if len(partners) > 1:
            problems.add(f"part {label} pairs with {' and '.join(partners)}. A part pairs with one other part at most")
            clean = False
    if kind == "chiasm" and not pairs:
        problems.add('a chiasm pairs each part on the way back with its partner, with "pairs_with"')
        clean = False
    return clean


def paired(parts: tuple) -> tuple:
    """The parts with each pair named once, by its later part."""
    order = [part[2] for part, _ in walk(parts)]
    partners = {}
    for part, _ in walk(parts):
        if part[3] is not None:
            earlier, later = sorted((part[2], part[3]), key=order.index)
            partners[later] = earlier

    def rebuild(level):
        return tuple((a, b, label, partners.get(label), rebuild(inner)) for a, b, label, _, inner in level)

    return rebuild(parts)


def walk(parts: tuple, parent: str | None = None):
    """Each part with its parent's label, in reading order: a part comes before the parts inside it."""
    for part in parts:
        yield part, parent
        yield from walk(part[4], part[2])


def lineage(parts: tuple, ancestors: tuple[str, ...] = ()):
    for part in parts:
        yield part, ancestors
        yield from lineage(part[4], ancestors + (part[2],))


def descendants(part: tuple) -> set[str]:
    return {inner[2] for inner, _ in walk(part[4])}


def render_part(db: sqlite3.Connection, part: tuple) -> dict:
    first, last, label, pairs_with, inner = part
    rendered = {"label": label, "passage": passage_of(db, first, last)}
    if pairs_with is not None:
        rendered["pairs_with"] = pairs_with
    if inner:
        rendered["parts"] = [render_part(db, p) for p in inner]
    return rendered


LAYERS = [Structures()]
