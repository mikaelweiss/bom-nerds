import sqlite3
from itertools import groupby

from .text import WORDS, english_editions, marks

ABBREVIATIONS = {"Jun", "Sen", "etc"}


def clear(db: sqlite3.Connection):
    english = english_editions(db)
    db.execute(f"delete from sentence where first_word_id in (select w.id from {WORDS} where c.edition_id in ({marks(english)}))", english)


def run(db: sqlite3.Connection):
    english = english_editions(db)
    ids = {}
    rows = []
    words = db.execute(
        f"select w.id, w.sequence, c.id, v.number, w.text, w.after from {WORDS} where c.edition_id in ({marks(english)}) order by w.sequence", english
    )
    for _, chapter in groupby(words, key=lambda w: w[2]):
        chapter = list(chapter)
        ids.update((w[1], w[0]) for w in chapter)
        rows.extend(split([w[1:] for w in chapter]))
    db.executemany("insert into sentence (first_word_id, last_word_id) values (?, ?)", [(ids[first], ids[last]) for first, last in rows])
    print(f"sentences: {len(rows)} English sentences")


def split(chapter: list[tuple]) -> list[tuple[int, int]]:
    sentences = []
    first = chapter[0][0]
    for word, following in zip(chapter, chapter[1:] + [None]):
        sequence, _, verse, text, after = word
        ends = (
            following is None
            or "\n" in after
            or (verse is None and following[2] is not None)
            or (any(mark in after for mark in ".?!") and text not in ABBREVIATIONS and len(text) > 1)
        )
        if ends:
            sentences.append((first, sequence))
            if following:
                first = following[0]
    return sentences
