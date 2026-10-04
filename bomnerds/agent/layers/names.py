"""Mentions of names and titles: which entity each name or title in a chapter refers to."""

import sqlite3

from ...passages import chapter_span, english_edition
from ...words import WORD
from ..layer import Layer, Problems, chapter_words, passage_of, scope_span, split_chapter

INSTRUCTIONS = """
Tag every name and title in this chapter with the entity it refers to: "Nephi", "Jerusalem", "the Holy One of Israel", "the Lamanites".
Pronouns such as "he" and "thee" come in a later job, so leave them out.

- Search for each entity and pick the one this verse means. Entities already found in this book come first.
- Tag a title or descriptive name as a whole: "the Holy One of Israel", not "Israel" inside it, unless the inner name also refers to an entity on its own.
- Jehovah and LORD in the Old Testament name Jesus Christ, and the Father names God the Father. Where a verse names both, tag each name to its own entity.
- One passage names one entity.

Answer with one object per mention:

{ "entity": "nephi-son-of-lehi", "passage": { "verse": "1 Nephi 3:7", "quote": "Nephi" } }
"""


class Names(Layer):
    name = "names"
    step = 4
    instructions = INSTRUCTIONS

    def ready(self, db, jobs, scope):
        book, _ = split_chapter(scope)
        earlier = super().ready(db, jobs, scope)
        if earlier or db.execute("select work_id from book where id = ?", (book,)).fetchone()[0] == "bible":
            return earlier
        if jobs.get("entities", book).settled() is None:
            return f"the entities job for this book, entities/{book}, must settle first"
        return None

    def context(self, db, jobs, scope):
        book, chapter = split_chapter(scope)
        candidates = book_entities(db, book, chapter)
        listed = "\n".join(f"{id} ({type_id}) {name}. {description}" for id, type_id, name, description in candidates)
        return super().context(db, jobs, scope) + ("\n\n## Entities found in this book whose names appear here\n\n" + listed if listed else "")

    def fixed(self, db, scope):
        book, chapter = split_chapter(scope)
        if db.execute("select work_id from book where id = ?", (book,)).fetchone()[0] == "bible":
            return []
        taken = {w for _, first, last in self.given(db, scope) for w in range(first, last + 1)}
        tags = []
        words = chapter_words(db, scope)
        names = sole_names(db)
        for start in range(len(words)):
            for length in range(min(6, len(words) - start), 0, -1):
                span = words[start:start + length]
                entity = names.get(" ".join(text for _, text in span))
                if entity and not taken & {id for id, _ in span}:
                    tags.append((entity, span[0][0], span[-1][0]))
                    taken |= {id for id, _ in span}
                    break
        return tags

    def given(self, db, scope):
        first, last = scope_span(db, scope)
        return list(db.execute("select entity_id, first_word_id, last_word_id from mention where kind_id = 'names' and first_word_id between ? and ? order by first_word_id", (first, last)))

    def parse(self, db, scope, answer):
        problems = Problems(db)
        tags = []
        for number, item in enumerate(problems.items(answer), 1):
            problems.at(f"item {number}")
            if not problems.fields(item, ("entity", "passage")):
                continue
            entity = problems.entity(item["entity"])
            span = problems.passage(item["passage"], within=scope)
            if span and only_pronouns(db, *span):
                problems.add("pronouns come in a later job, so leave them out")
            elif entity and span:
                tags.append((entity, *span))
        named = {}
        for entity, first, last in tags:
            other = named.setdefault((first, last), entity)
            if other != entity:
                problems.at("").add(f"{self.render(db, (entity, first, last))['passage']} names both {other} and {entity}. One passage names one entity")
        problems.raise_any()
        return tags

    def render(self, db, tag):
        entity, first, last = tag
        return {"entity": entity, "passage": passage_of(db, first, last)}

    def store(self, db, scope, tags):
        db.executemany("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values (?, 'names', ?, ?)", tags)

    def unstore(self, db, scope, tags):
        db.executemany("delete from mention where entity_id = ? and kind_id = 'names' and first_word_id = ? and last_word_id = ?", tags)

    def shown(self, db, edition, book_id, chapter):
        first, last = chapter_span(db, edition, book_id, chapter)
        rows = db.execute("select entity_id, kind_id, first_word_id, last_word_id from mention where first_word_id between ? and ? order by first_word_id, last_word_id desc", (first, last))
        return [{"entity": entity, "kind": kind, "passage": passage_of(db, a, b)} for entity, kind, a, b in rows]


# Each entry holds its connection, so its id is never reused while cached.
SOLE_NAMES: dict[int, tuple[sqlite3.Connection, dict[str, str]]] = {}


def sole_names(db: sqlite3.Connection) -> dict[str, str]:
    """Each name or title only one entity carries, mapped to that entity, leaving out names that are also everyday words."""
    if id(db) not in SOLE_NAMES:
        SOLE_NAMES[id(db)] = (db, find_sole_names(db))
    return SOLE_NAMES[id(db)][1]


def find_sole_names(db: sqlite3.Connection) -> dict[str, str]:
    lowercase = {w for (w,) in db.execute("select distinct text from word where edition_id in ('kjv', 'bom-2013', 'dc-2013', 'pgp-2013') and text = lower(text)")}
    carriers = {}
    for entity, name in db.execute("select entity_id, name from entity_name union select id, name from entity"):
        carriers.setdefault(" ".join(WORD.findall(name)), set()).add(entity)
    return {
        name: next(iter(entities))
        for name, entities in carriers.items()
        if len(entities) == 1 and name and name[0].isupper() and not (" " not in name and name.lower() in lowercase)
    }


def only_pronouns(db: sqlite3.Connection, first: int, last: int) -> bool:
    parts = [p for (p,) in db.execute("select part_of_speech from word_headword where word_id between ? and ?", (first, last))]
    return bool(parts) and len(parts) == last - first + 1 and all(p == "pronoun" for p in parts)


def book_entities(db: sqlite3.Connection, book: str, chapter: int) -> list[tuple[str, str, str, str]]:
    edition = english_edition(db, book)
    first, last = chapter_span(db, edition, book, chapter)
    present = {text for (text,) in db.execute("select distinct text from word where id between ? and ?", (first, last))}
    rows = db.execute(
        "select e.id, e.type_id, e.name, e.description, group_concat(n.name, '|') from entity e join entity_book b on b.entity_id = e.id "
        "left join entity_name n on n.entity_id = e.id where b.book_id = ? group by e.id order by e.name, e.id",
        (book,),
    )
    return [(id, type_id, name, description) for id, type_id, name, description, names in rows if present & set(WORD.findall(f"{name}|{names or ''}"))]


LAYERS = [Names()]
