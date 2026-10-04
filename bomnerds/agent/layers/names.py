"""Mentions of names and titles: which entity each name or title in a chapter refers to."""

import sqlite3

from ...passages import chapter_span, english_edition, reference
from ...words import WORD
from ..layer import Layer, Problems, Reading, chapter_words, passage_of, scope_span, split_chapter, unflag, where

INSTRUCTIONS = """
Tag every name and title in each chapter with the entity it refers to: "Nephi", "Jerusalem", "the Holy One of Israel", "the Lamanites".
Pronouns such as "he" and "thee" come in a later pass, so leave them out.

- Pick each entity from the list under Entities: the one this verse means.
- Tag a title or descriptive name as a whole: "the Holy One of Israel", not "Israel" inside it, unless the inner name also refers to an entity on its own.
- Jehovah and LORD in the Old Testament name Jesus Christ, and the Father names God the Father. Where a verse names both, tag each name to its own entity.
- One passage names one entity.
- Every word listed under "Capitalized words" must be inside a tag, or marked as no name with "-" in place of the entity, as "Behold" is below.
"""

FORMAT = """Write one line per mention: the chapter and verse, the quote, and the entity, joined by " | ".

3:7 | Nephi | nephi-son-of-lehi
3:16 | the Holy One of Israel | jesus-christ
3:28 | Lemuel @ Lemuel did | lemuel
3:29 | Behold | -

When the quote appears more than once in its verse, add " @ " and longer words that appear once and hold it once, as on the Lemuel line. An error that says to add "in" means this.
A "-" in place of the entity marks a capitalized word that names no one."""


class Names(Layer):
    name = "names"
    step = 4
    instructions = INSTRUCTIONS

    format = FORMAT

    def extra(self, db, jobs, scope, batch=()):
        verses = {}
        taken = covered(self.fixed(db, scope) + self.given(db, scope))
        book, chapter = split_chapter(scope)
        for word, verse, text in name_candidates(db, scope):
            if word not in taken:
                verses.setdefault(verse, []).append(text)
        listed = "\n".join(f"{chapter}:{verse} {', '.join(texts)}" for verse, texts in verses.items())
        return "## Capitalized words\n\n" + listed if listed else ""

    def read(self, db, scope, lines):
        book, chapter = split_chapter(scope)
        problems = Problems(db)
        reading = Reading()
        for number, line in enumerate(lines, 1):
            problems.at(f"line {number}")
            text, unsure = unflag(line)
            parts = [part.strip() for part in text.split("|")]
            if len(parts) != 3 or not all(parts):
                problems.add('write "verse | quote | entity", such as "3:7 | Nephi | nephi-son-of-lehi"')
                continue
            verse, quote, entity = parts
            passage = verse_passage(db, book, chapter, verse, quote, problems)
            if passage is None:
                continue
            if entity == "-":
                reading.skipped.append(passage)
                continue
            item = {"entity": entity, "passage": passage}
            reading.items.append(item)
            if unsure:
                reading.flagged.append(text)
        problems.raise_any()
        return reading

    def complete(self, db, scope, reading):
        problems = Problems(db)
        # Parse reports a passage that does not resolve, so this only collects the ones that do.
        quiet = Problems(db)
        passages = reading.skipped + [found["passage"] for found in reading.unlisted] + [item.get("passage") for item in reading.items]
        spans = [span for span in (quiet.passage(passage, within=scope) for passage in passages) if span]
        taken = covered([(None, *span) for span in spans] + self.fixed(db, scope) + self.given(db, scope))
        book, chapter = split_chapter(scope)
        missing = {}
        for word, verse, text in name_candidates(db, scope):
            if word not in taken:
                missing.setdefault(verse, []).append(text)
        if missing:
            problems.add("these capitalized words are in no tag. Tag each one, or mark it with \"-\" when it names no one: " + "; ".join(f"{chapter}:{verse} {', '.join(texts)}" for verse, texts in missing.items()))
        return problems.messages

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
            problems.at(where(number, item))
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


def covered(tags) -> set[int]:
    """Every word inside the passage of one of these (entity, first, last) tags."""
    return {word for _, first, last in tags for word in range(first, last + 1)}


def name_candidates(db: sqlite3.Connection, scope: str) -> list[tuple[int, int, str]]:
    """(word id, verse, text) of each capitalized word inside a sentence, which a names answer tags or marks as no name."""
    first, last = scope_span(db, scope)
    rows = db.execute(
        """
        select w.id, w.verse, w.text from (
            select id, verse, text, position, before, lag(after) over (partition by verse order by position) as prior
            from word where id between ? and ?
        ) w left join word_headword h on h.word_id = w.id
        where substr(w.text, 1, 1) between 'A' and 'Z' and w.position > 1 and w.text not in ('I', 'O')
            and w.prior not glob '*[.?!:;]*' and w.before not glob '*[(“‘"]*' and coalesce(h.part_of_speech, '') <> 'pronoun'
        order by w.id
        """,
        (first, last),
    )
    return list(rows)


def verse_passage(db: sqlite3.Connection, book: str, chapter: int, verse: str, quote: str, problems: Problems) -> dict | None:
    """The passage a short line points at: "3:7" and a quote, with "quote @ longer words" when the quote appears more than once."""
    numbers = verse.split(":")
    if len(numbers) != 2 or not all(n.isdigit() for n in numbers):
        problems.add(f'"{verse}" must be chapter and verse, such as {chapter}:7')
        return None
    if int(numbers[0]) != chapter:
        problems.add(f"{verse} is not in chapter {chapter}. Write each line under its own chapter's heading")
        return None
    words, _, within = quote.partition(" @ ")
    passage = {"verse": reference(db, book, chapter, int(numbers[1])), "quote": words.strip()}
    if within.strip():
        passage["in"] = within.strip()
    return passage


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
