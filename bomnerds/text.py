"""Builds the database and its text layer: every work, edition, book, chapter, verse, and word."""

import re
import sqlite3
import sys
import zipfile

from . import lds, usfm
from .sources import ROOT, fetch
from .words import Book, rebuild

DATABASE = ROOT / "scripture.db"


def bible() -> list[Book]:
    with zipfile.ZipFile(fetch("eng-kjv2006_usfm.zip")) as archive:
        names = sorted(n for n in archive.namelist() if n.endswith(".usfm"))
        return [usfm.parse(archive.read(n).decode("utf-8-sig")) for n in names]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def build():
    if DATABASE.exists():
        sys.exit(f"{DATABASE.name} already exists. Tags point at word ids, so the text is never rebuilt in place. Delete it to start over.")

    editions = [
        ("bible", "kjv", bible()),
        ("bom", "bom-2013", lds.book_of_mormon(fetch("book-of-mormon.json"))),
        ("dc", "dc-2013", lds.doctrine_and_covenants(fetch("doctrine-and-covenants.json"))),
        ("pgp", "pgp-2013", lds.pearl_of_great_price(fetch("pearl-of-great-price.json"))),
    ]

    db = sqlite3.connect(DATABASE)
    db.executescript((ROOT / "db/schema.sql").read_text())
    db.executescript((ROOT / "db/seed.sql").read_text())
    with db:
        for work, edition, books in editions:
            for position, book in enumerate(books, 1):
                book_id = slug(book.name)
                db.execute("insert into book (id, work_id, name) values (?, ?, ?)", (book_id, work, book.name))
                db.execute("insert into edition_book (edition_id, book_id, position) values (?, ?, ?)", (edition, book_id, position))
                db.executemany(
                    "insert into word (edition_id, book_id, chapter, verse, position, text, before, after, supplied) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (edition, book_id, chapter, verse, number, w.text, w.before, w.after, int(w.supplied))
                        for (chapter, verse), words in sorted(book.verses.items())
                        for number, w in enumerate(words, 1)
                    ],
                )
    verify(db, editions)
    summarize(db)


def verify(db: sqlite3.Connection, editions):
    """Every verse must read back from the database exactly as parsed."""
    stored = {}
    for edition, book, chapter, verse, text in db.execute("select edition_id, book_id, chapter, verse, before || text || after from word order by id"):
        key = (edition, book, chapter, verse)
        stored[key] = stored.get(key, "") + text
    for _, edition, books in editions:
        for book in books:
            for (chapter, verse), words in book.verses.items():
                if stored[(edition, slug(book.name), chapter, verse)] != rebuild(words):
                    sys.exit(f"{book.name} {chapter}:{verse} does not rebuild from the database")


def summarize(db: sqlite3.Connection):
    print(f"{'edition':<10} {'books':>6} {'chapters':>9} {'verses':>7} {'words':>8}")
    for row in db.execute(
        "select edition_id, count(distinct book_id), count(distinct book_id || ' ' || chapter), count(distinct book_id || ' ' || chapter || ':' || verse), count(*) from word group by edition_id order by min(id)"
    ):
        print(f"{row[0]:<10} {row[1]:>6} {row[2]:>9} {row[3]:>7} {row[4]:>8}")


if __name__ == "__main__":
    build()
