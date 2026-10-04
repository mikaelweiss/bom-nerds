"""Relationships: facts connecting two entities, each citing the passages in this chapter that state it."""

import sqlite3
from functools import cache

from ... import family
from ...checks import FAMILY
from ...passages import Rejected, chapter_span
from ..layer import Layer, Problems, kinds, passage_of, scope_span, split_chapter

INSTRUCTIONS = f"""
Tag every relationship between two entities that this chapter states: who is whose child, spouse, or brother, who leads or belongs to whom, where something took place, which place lies north of another, who wrote or kept a record.

- The kinds are listed under Context, with how each reads from subject to object.
- Evidence is the passages in this chapter that state the relationship. Cite the words that say it, not the whole verse, and cite at least one.
- Tag a relationship once, with all its evidence in this chapter. A relationship found in several chapters is one relationship, so tag it here with this chapter's evidence.
- A two-way kind is tagged once, with the entities in either order. A one-way kind never runs both ways.
- Never join an entity to itself.
- {", ".join(FAMILY)} join two people. When the text calls a people the son of a man, use a kind that fits, such as named_after.
- A relationship under Already tagged has the evidence listed there. Leave it out, or tag it again with only the evidence it still lacks.

Answer with one object per relationship:

{{ "subject": "nephi-son-of-lehi", "kind": "child_of", "object": "lehi-father-of-nephi",
  "evidence": [{{ "verse": "1 Nephi 1:4", "quote": "my father, Lehi" }}] }}
"""


class Relationships(Layer):
    name = "relationships"
    step = 7
    instructions = INSTRUCTIONS

    def context(self, db, jobs, scope):
        rows = db.execute("select id, name, reverse_name, two_way from relationship_kind order by rowid")
        listed = "\n".join(
            f"{id}: subject, {name}, object " + ("(two-way, stored once)" if two_way else f"(reads back as {reverse})") for id, name, reverse, two_way in rows
        )
        return super().context(db, jobs, scope) + "\n\n## Relationship kinds\n\n" + listed

    def given(self, db, scope):
        return evidenced(db, *scope_span(db, scope))

    def parse(self, db, scope, answer):
        problems = Problems(db)
        allowed = kinds(db, "relationship_kind")
        two_way = two_way_kinds(db)
        tags, seen = [], {}
        for number, item in enumerate(problems.items(answer), 1):
            where = f"item {number}"
            problems.at(where)
            if not problems.fields(item, ("subject", "kind", "object", "evidence")):
                continue
            before = len(problems.messages)
            kind = problems.kind(item["kind"], allowed)
            types = ("person",) if kind in FAMILY else None
            subject = problems.entity(item["subject"], types)
            object = problems.entity(item["object"], types)
            evidence = cite(problems, scope, item["evidence"], where)
            if subject and subject == object:
                problems.add(f"{subject} cannot be {kind} itself. Join two different entities")
            if len(problems.messages) > before:
                continue
            written = (subject, object)
            if kind in two_way:
                subject, object = sorted(written)
            pair = (kind, frozenset(written))
            if pair in seen:
                earlier, there = seen[pair]
                if there == written or kind in two_way:
                    problems.add(f"this is the same subject, kind, and object as item {earlier}. Put all the evidence in one item")
                else:
                    problems.add(f"{kind} runs both ways with item {earlier}, which says {there[0]} {kind} {there[1]}. A one-way kind cannot. Keep the one the text states")
                continue
            seen[pair] = (number, written)
            if kind not in two_way and db.execute("select 1 from relationship where kind_id = ? and subject_id = ? and object_id = ?", (kind, object, subject)).fetchone():
                problems.add(f"{object} {kind} {subject} is already stored, so this would run {kind} both ways. If the text says it, an operator must correct the stored one. Otherwise leave this out")
                continue
            tags.append((subject, kind, object, evidence))
        problems.raise_any()
        return tags

    def render(self, db, tag):
        subject, kind, object, evidence = tag
        return {"subject": subject, "kind": kind, "object": object, "evidence": [passage_of(db, first, last) for first, last in evidence]}

    def store(self, db, scope, tags):
        two_way = two_way_kinds(db)
        for subject, kind, object, evidence in tags:
            row = stored(db, subject, kind, object)
            if row is None:
                id = db.execute("insert into relationship (subject_id, kind_id, object_id) values (?, ?, ?)", (subject, kind, object)).lastrowid
            else:
                id, existing = row
                if existing != subject and kind not in two_way:
                    raise Rejected(f"{subject} {kind} {object} contradicts the stored {existing} {kind} {subject}. A one-way kind cannot run both ways")
            db.executemany("insert or ignore into relationship_evidence (relationship_id, first_word_id, last_word_id) values (?, ?, ?)", [(id, first, last) for first, last in evidence])

    def unstore(self, db, scope, tags):
        two_way = two_way_kinds(db)
        for subject, kind, object, evidence in tags:
            row = stored(db, subject, kind, object)
            if row is None or (row[1] != subject and kind not in two_way):
                continue
            id = row[0]
            db.executemany("delete from relationship_evidence where relationship_id = ? and first_word_id = ? and last_word_id = ?", [(id, first, last) for first, last in evidence])
            if (row[1], kind, object if row[1] == subject else subject) not in script_facts():
                db.execute("delete from relationship where id = ? and not exists (select 1 from relationship_evidence where relationship_id = ?)", (id, id))

    def shown(self, db, edition, book_id, chapter):
        return [self.render(db, tag) for tag in evidenced(db, *chapter_span(db, edition, book_id, chapter))]


@cache
def script_facts() -> set[tuple[str, str, str]]:
    """Family relationships the script layer owns, kept on unstore even when no evidence is left."""
    return family.facts()


def cite(problems: Problems, scope: str, value, where: str) -> tuple[tuple[int, int], ...] | None:
    """The evidence as sorted word spans, all inside the chapter."""
    if not isinstance(value, list) or not value:
        problems.add("evidence must be a list with at least one passage in this chapter")
        return None
    spans = []
    for number, passage in enumerate(value, 1):
        problems.at(f"{where}, evidence {number}")
        spans.append(problems.passage(passage, within=scope))
    problems.at(where)
    if None in spans:
        return None
    if len(set(spans)) < len(spans):
        problems.add("evidence cites the same passage twice")
        return None
    return tuple(sorted(spans))


def evidenced(db: sqlite3.Connection, first: int, last: int) -> list[tuple]:
    """Every relationship with evidence between these words, as tags holding only that evidence, in reading order."""
    found: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
    for subject, kind, object, start, end in db.execute(
        "select r.subject_id, r.kind_id, r.object_id, e.first_word_id, e.last_word_id from relationship r join relationship_evidence e on e.relationship_id = r.id "
        "where e.first_word_id >= ? and e.last_word_id <= ? order by r.id, e.first_word_id, e.last_word_id",
        (first, last),
    ):
        found.setdefault((subject, kind, object), []).append((start, end))
    return sorted(((subject, kind, object, tuple(spans)) for (subject, kind, object), spans in found.items()), key=lambda tag: tag[3][0])


def stored(db: sqlite3.Connection, subject: str, kind: str, object: str) -> tuple[int, str] | None:
    """The row for this pair and kind in either direction, as (id, subject)."""
    low, high = sorted((subject, object))
    return db.execute("select id, subject_id from relationship where kind_id = ? and min(subject_id, object_id) = ? and max(subject_id, object_id) = ?", (kind, low, high)).fetchone()


def two_way_kinds(db: sqlite3.Connection) -> set[str]:
    return {id for (id,) in db.execute("select id from relationship_kind where two_way = 1")}


LAYERS = [Relationships()]
