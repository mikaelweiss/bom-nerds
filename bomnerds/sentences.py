"""Splits the English editions into sentences, which end at a period, question mark, or exclamation mark, never at a colon, semicolon, or dash."""

import sqlite3
from itertools import groupby

ENGLISH = ("kjv", "bom-2013", "dc-2013", "pgp-2013")
ABBREVIATIONS = {"Jun", "Sen", "etc"}


def clear(db: sqlite3.Connection):
    db.execute(f"delete from sentence where first_word_id in (select id from word where edition_id in ({','.join('?' * len(ENGLISH))}))", ENGLISH)


def run(db: sqlite3.Connection):
    rows = []
    words = db.execute(
        f"select id, edition_id, book_id, chapter, verse, text, after from word where edition_id in ({','.join('?' * len(ENGLISH))}) order by id", ENGLISH
    )
    for _, chapter in groupby(words, key=lambda w: w[1:4]):
        rows.extend(split(list(chapter)))
    db.executemany("insert into sentence (first_word_id, last_word_id) values (?, ?)", rows)
    print(f"sentences: {len(rows)} English sentences")


def split(chapter: list[tuple]) -> list[tuple[int, int]]:
    """A chapter's sentences. Verse 0, a title or heading, never runs into verse 1, and a line break ends a sentence."""
    sentences = []
    first = chapter[0][0]
    for word, following in zip(chapter, chapter[1:] + [None]):
        id, _, _, _, verse, text, after = word
        ends = (
            following is None
            or "\n" in after
            or (verse == 0 and following[4] != 0)
            or (any(mark in after for mark in ".?!") and text not in ABBREVIATIONS and len(text) > 1)
        )
        if ends:
            sentences.append((first, id))
            if following:
                first = following[0]
    return sentences
