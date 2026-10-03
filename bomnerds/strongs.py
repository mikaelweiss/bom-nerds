"""Matches each Hebrew and Greek word to the KJV words that translate it, by the Strong's numbers eBible puts on KJV words."""

import re
import sqlite3
from collections import defaultdict

from .text import bible, slug
from .versification import mapping

ORIGINAL = "select id from word where edition_id in ('wlc', 'sblgnt')"


def clear(db: sqlite3.Connection):
    db.execute(f"delete from word_match where other_word_id in ({ORIGINAL})")


def run(db: sqlite3.Connection):
    renumbered = mapping(db)
    kjv_ids = {(b, c, v, p): id for id, b, c, v, p in db.execute("select id, book_id, chapter, verse, position from word where edition_id = 'kjv'")}
    original = defaultdict(list)
    for id, book, chapter, verse, number in db.execute(
        "select w.id, w.book_id, w.chapter, w.verse, h.strongs from word w join word_headword wh on wh.word_id = w.id join headword h on h.id = wh.headword_id "
        "where w.edition_id in ('wlc', 'sblgnt') order by w.id"
    ):
        if number:
            original[(book, chapter, verse)].append((base(number), id))

    pairs = set()
    unmatched = 0
    for book in bible():
        book_id = slug(book.name)
        for (chapter, verse), words in book.verses.items():
            targets = [w for v in renumbered.get((book_id, chapter, verse), [(book_id, chapter, verse)]) for w in original.get(v, [])]
            units = translation_units([(kjv_ids[(book_id, chapter, verse, n)], w.strongs) for n, w in enumerate(words, 1)])
            for number, english in units.items():
                found = [id for n, id in targets if n == number]
                if len(found) == len(english):
                    matched = zip(english, ([id] for id in found))
                elif len(found) == 1:
                    matched = ((unit, found) for unit in english)
                else:
                    unmatched += len(english)
                    continue
                for unit, ids in matched:
                    pairs.update((min(a, b), max(a, b)) for a in unit for b in ids)
    db.executemany("insert into word_match (word_id, other_word_id) values (?, ?)", sorted(pairs))
    print(f"strongs: {len(pairs)} word matches, {unmatched} tagged KJV words left unmatched where counts disagree")


def base(number: str) -> str:
    return re.match(r"[HG]\d+", number).group()


def translation_units(words: list[tuple[int, tuple[str, ...]]]) -> dict[str, list[list[int]]]:
    """Group consecutive KJV words that carry the same Strong's numbers, since eBible tags a phrase like "It is written" as one translation."""
    units = defaultdict(list)
    previous = None
    for id, numbers in words:
        if not numbers:
            previous = None
            continue
        if numbers == previous:
            for number in numbers:
                units[base(number)][-1].append(id)
        else:
            for number in numbers:
                units[base(number)].append([id])
        previous = numbers
    return units
