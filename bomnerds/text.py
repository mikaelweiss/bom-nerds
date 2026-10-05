import sqlite3
import sys
import zipfile
from collections.abc import Callable

from . import lds, usfm
from .rows import row_id
from .sources import ROOT, fetch
from .words import Book, Word, reading_order, rebuild

DATABASE = ROOT / "scripture.db"

KJV = "King James Version (1769)"
WLC = "Westminster Leningrad Codex"
SBLGNT = "SBL Greek New Testament"
BOOK_OF_MORMON = "Book of Mormon (2013)"
DOCTRINE_AND_COVENANTS = "Doctrine and Covenants (2013)"
PEARL_OF_GREAT_PRICE = "Pearl of Great Price (2013)"

WORDS = "word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id"


def bible() -> list[Book]:
    with zipfile.ZipFile(fetch("eng-kjv2006_usfm.zip")) as archive:
        names = sorted(n for n in archive.namelist() if n.endswith(".usfm"))
        return [usfm.parse(archive.read(n).decode("utf-8-sig")) for n in names]


def english_editions(db: sqlite3.Connection) -> list[int]:
    return [row[0] for row in db.execute("select id from edition where language_id = ? order by id", (row_id(db, "language", "en", "iso_code"),))]


def marks(values) -> str:
    return ",".join("?" * len(values))


def build():
    new = not DATABASE.exists()
    db = sqlite3.connect(DATABASE)
    db.execute("pragma foreign_keys = on")
    if new:
        db.executescript((ROOT / "db/schema.sql").read_text())
    db.executescript((ROOT / "db/seed.sql").read_text())
    added = []
    for name, books in editions(db):
        edition = row_id(db, "edition", name)
        if db.execute("select 1 from edition_book where edition_id = ?", (edition,)).fetchone():
            continue
        with db:
            added += add_edition(db, edition, books())
    with db:
        number_words(db)
    verify(db, added)
    summarize(db)


def editions(db: sqlite3.Connection) -> list[tuple[str, Callable[[], list[Book]]]]:
    from . import macula

    return [
        (KJV, bible),
        (BOOK_OF_MORMON, lambda: lds.book_of_mormon(fetch("book-of-mormon.json"))),
        (DOCTRINE_AND_COVENANTS, lambda: lds.doctrine_and_covenants(fetch("doctrine-and-covenants.json"))),
        (PEARL_OF_GREAT_PRICE, lambda: lds.pearl_of_great_price(fetch("pearl-of-great-price.json"))),
        (WLC, lambda: macula.books(db, WLC)),
        (SBLGNT, lambda: macula.books(db, SBLGNT)),
    ]


def add_edition(db: sqlite3.Connection, edition: int, books: list[Book]) -> list[tuple[int, int, Book]]:
    work = db.execute("select work_id from edition where id = ?", (edition,)).fetchone()[0]
    added = []
    for position, book in enumerate(books, 1):
        db.execute("insert into book (work_id, name) values (?, ?) on conflict do nothing", (work, book.name))
        book_id = db.execute("select id from book where work_id = ? and name = ?", (work, book.name)).fetchone()[0]
        db.execute("insert into edition_book (edition_id, book_id, work_id, position) values (?, ?, ?, ?)", (edition, book_id, work, position))
        insert_text(db, edition, book_id, book.verses)
        added.append((edition, book_id, book))
    return added


def insert_text(db: sqlite3.Connection, edition: int, book: int, verses: dict[tuple[int, int | None], list[Word]]):
    sequence = db.execute("select coalesce(max(sequence), 0) from word").fetchone()[0]
    chapters = {}
    for (chapter, verse), words in sorted(verses.items(), key=lambda item: reading_order(item[0])):
        if chapter not in chapters:
            chapters[chapter] = db.execute("insert into chapter (edition_id, book_id, number) values (?, ?, ?)", (edition, book, chapter)).lastrowid
        verse_id = db.execute("insert into verse (chapter_id, number) values (?, ?)", (chapters[chapter], verse)).lastrowid
        db.executemany(
            "insert into word (verse_id, position, sequence, text, before, after, supplied) values (?, ?, ?, ?, ?, ?, ?)",
            [(verse_id, position, sequence + position, w.text, w.before, w.after, int(w.supplied)) for position, w in enumerate(words, 1)],
        )
        sequence += len(words)


def number_words(db: sqlite3.Connection):
    order = (
        "select w.id, row_number() over (order by c.edition_id, eb.position, c.number, v.number nulls first, w.position) as sequence "
        f"from {WORDS} join edition_book eb on eb.edition_id = c.edition_id and eb.book_id = c.book_id"
    )
    db.execute(f"update word set sequence = -o.sequence from ({order}) o where o.id = word.id and word.sequence <> o.sequence")
    db.execute("update word set sequence = -sequence where sequence < 0")


def verify(db: sqlite3.Connection, parsed: list[tuple[int, int, Book]]):
    stored = {}
    for edition, book, chapter, verse, text in db.execute(f"select c.edition_id, c.book_id, c.number, v.number, w.before || w.text || w.after from {WORDS} order by w.sequence"):
        key = (edition, book, chapter, verse)
        stored[key] = stored.get(key, "") + text
    for edition, book_id, book in parsed:
        for (chapter, verse), words in book.verses.items():
            if stored[(edition, book_id, chapter, verse)] != rebuild(words):
                sys.exit(f"{book.name} {chapter}:{verse} does not rebuild from the database")


def summarize(db: sqlite3.Connection):
    print(f"{'edition':<30} {'books':>6} {'chapters':>9} {'verses':>7} {'words':>8}")
    for row in db.execute(
        f"select e.name, count(distinct c.book_id), count(distinct c.id), count(distinct v.id), count(*) from {WORDS} join edition e on e.id = c.edition_id "
        "group by e.id order by e.id"
    ):
        print(f"{row[0]:<30} {row[1]:>6} {row[2]:>9} {row[3]:>7} {row[4]:>8}")


if __name__ == "__main__":
    build()
