"""A small scripture database and job folder for testing agent layers."""

import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from bomnerds.agent import jobs
from bomnerds.sources import ROOT
from bomnerds.text import slug
from bomnerds.words import split

EDITIONS = {"bible": "kjv", "bom": "bom-2013", "dc": "dc-2013", "pgp": "pgp-2013"}


def database(books: list[tuple[str, str, dict[tuple[int, int], str]]]) -> sqlite3.Connection:
    """An in-memory database holding each (work, book name, {(chapter, verse): text}) in its English edition."""
    db = sqlite3.connect(":memory:")
    db.executescript((ROOT / "db/schema.sql").read_text())
    db.executescript((ROOT / "db/seed.sql").read_text())
    positions = {}
    for work, name, verses in books:
        edition = EDITIONS[work]
        book = slug(name)
        positions[edition] = positions.get(edition, 0) + 1
        db.execute("insert into book (id, work_id, name) values (?, ?, ?)", (book, work, name))
        db.execute("insert into edition_book (edition_id, book_id, position) values (?, ?, ?)", (edition, book, positions[edition]))
        for (chapter, verse), text in sorted(verses.items()):
            db.executemany(
                "insert into word (edition_id, book_id, chapter, verse, position, text, before, after) values (?, ?, ?, ?, ?, ?, ?, ?)",
                [(edition, book, chapter, verse, n, w.text, w.before, w.after) for n, w in enumerate(split(text), 1)],
            )
    return db


def entity(db: sqlite3.Connection, id: str, type_id: str, name: str, description: str = "", other_names: tuple[str, ...] = (), books: tuple[str, ...] = ()):
    db.execute("insert into entity (id, type_id, name, description) values (?, ?, ?, ?)", (id, type_id, name, description))
    db.executemany("insert into entity_name (entity_id, name) values (?, ?)", [(id, n) for n in (name, *other_names)])
    db.executemany("insert into entity_book (entity_id, book_id) values (?, ?)", [(id, b) for b in books])


@contextmanager
def job_folder():
    """Point the job store at a temporary folder for the length of a test."""
    with tempfile.TemporaryDirectory() as folder:
        with mock.patch.object(jobs, "JOBS", Path(folder)), mock.patch.object(jobs, "MISSING", Path(folder) / "missing.jsonl"):
            yield Path(folder)
