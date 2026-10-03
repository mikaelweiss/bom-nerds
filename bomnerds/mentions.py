"""Mentions of names that a script can settle: Bible names by Strong's number and TIPNR's verse lists, and the names of Jehovah."""

import re
import sqlite3
from collections import defaultdict

from . import tipnr
from .entities import JESUS, JESUS_CHRIST, build_ids, is_name, usable
from .refs import OLD_TESTAMENT, USFM, codes
from .strongs import base, translation_units
from .text import bible, slug
from .versification import mapping

# Latter-day Saint doctrine: the LORD, JAH, and GOD of the Old Testament render the name Jehovah, who is Jesus Christ.
JEHOVAH_STRONGS = {"H3068", "H3050", "H3069"}


def clear(db: sqlite3.Connection):
    db.execute("delete from mention where kind_id = 'names'")


def run(db: sqlite3.Connection):
    books = codes(db, USFM)
    old_testament = set(books[c] for c in USFM[:OLD_TESTAMENT])
    renumbered = mapping(db)
    candidates = defaultdict(set)
    for entity_id, record in build_ids(usable(tipnr.records())):
        if record.unique == JESUS:
            entity_id = JESUS_CHRIST[0]
        for form in record.forms:
            if not is_name(form.kjv):
                continue
            for code, chapter, verse in form.refs:
                if code in books:
                    candidates[(books[code], chapter, verse, base(form.strongs))].add(entity_id)

    kjv = {}
    texts = {}
    for id, b, c, v, p, text in db.execute("select id, book_id, chapter, verse, position, text from word where edition_id = 'kjv'"):
        kjv[(b, c, v, p)] = id
        texts[id] = text
    found = set()
    ambiguous = 0
    for book in bible():
        book_id = slug(book.name)
        for (chapter, verse), words in book.verses.items():
            refs = [(book_id, chapter, verse), *renumbered.get((book_id, chapter, verse), [])]
            units = translation_units([(kjv[(book_id, chapter, verse, n)], w.strongs) for n, w in enumerate(words, 1)])
            for number, spans in units.items():
                if number in JEHOVAH_STRONGS and book_id in old_testament:
                    entities = {JESUS_CHRIST[0]}
                else:
                    entities = set().union(*(candidates.get((*ref, number), set()) for ref in refs))
                if len(entities) > 1:
                    ambiguous += len(spans)
                if len(entities) != 1:
                    continue
                entity = next(iter(entities))
                for span in spans:
                    names = name_words(span, texts)
                    if names:
                        found.add((entity, *names))

    for id, in db.execute("select id from word where lower(text) = 'jehovah' and edition_id not in ('wlc', 'sblgnt')"):
        found.add((JESUS_CHRIST[0], id, id))
    db.executemany("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values (?, 'names', ?, ?)", sorted(found))
    print(f"mentions: {len(found)} name mentions, {ambiguous} words left where several entities carry the name")


def name_words(span: list[int], texts: dict[int, str]) -> tuple[int, int] | None:
    """Trim a tagged phrase such as "the prophet Elijah" to its capitalized words."""
    capitalized = [id for id in span if re.match(r"[A-Z]", texts[id])]
    return (capitalized[0], capitalized[-1]) if capitalized else None
