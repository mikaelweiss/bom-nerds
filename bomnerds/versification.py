"""Reads STEPBible's TVTMS: which Hebrew or Greek verses hold each KJV verse where the two number verses differently."""

import re
import sqlite3
from collections import defaultdict

from .refs import OLD_TESTAMENT, USFM, codes
from .rows import row_id
from .sources import fetch
from .text import KJV, SBLGNT, WLC
from .words import reading_order

# (book id, chapter, verse). A verse of None is the chapter's heading, which TVTMS calls its title.
Verse = tuple[int, int, int | None]

REFERENCE = re.compile(r"(\w+)\.(\d+):(Title|\d+)(?:\.\d+|[a-z])?(?:-(?:(\d+):)?(\d+)(?:\.\d+|[a-z])?)?")


def mapping(db: sqlite3.Connection) -> dict[Verse, list[Verse]]:
    """Map each KJV verse that TVTMS renumbers to the Hebrew or Greek verses that hold its text."""
    books = codes(db, USFM)
    old_testament = set(USFM[:OLD_TESTAMENT])
    english = verses(db, row_id(db, "edition", KJV))
    original = verses(db, row_id(db, "edition", WLC)) | verses(db, row_id(db, "edition", SBLGNT))
    result = defaultdict(list)
    columns = []
    lines = fetch("tvtms.txt").read_text(encoding="utf-8").split("#DataStart(Condensed)")[1].split("#DataEnd(Condensed)")[0].splitlines()
    for line in lines:
        cells = [cell.strip() for cell in line.split("\t")]
        action = cells[0]
        if action.startswith("$") or action == "BIBLES":
            if any(cell.startswith("English") for cell in cells[1:]):
                columns = cells[1:]
            continue
        if not action or not action[0].isalpha() or action.startswith("TEST") or len(cells) < 3 or cells[1].startswith("&"):
            continue
        try:
            english_cell = cells[1 + next(i for i, c in enumerate(columns) if c.startswith("English KJV"))]
        except StopIteration:
            continue
        first = REFERENCE.search(english_cell)
        if not first:
            continue
        target = "Hebrew" if first.group(1).upper() in old_testament else "Greek"
        index = next((i for i, c in enumerate(columns) if c.startswith(target) and not c.startswith(target + "2")), None)
        if index is None or 1 + index >= len(cells):
            continue
        sources = expand(english_cell, books, english)
        targets = expand(cells[1 + index], books, original)
        if not sources or not targets:
            continue
        if len(sources) == len(targets):
            for source, target_verse in zip(sources, targets):
                add(result, source, [target_verse])
        else:
            for source in sources:
                add(result, source, targets)
    return dict(result)


def add(result, source, targets):
    for target in targets:
        if target not in result[source]:
            result[source].append(target)


def verses(db, edition: int) -> dict[int, list[Verse]]:
    by_book = defaultdict(list)
    for verse in db.execute("select c.book_id, c.number, v.number from verse v join chapter c on c.id = v.chapter_id where c.edition_id = ? order by c.book_id, c.number, v.number", (edition,)):
        by_book[verse[0]].append(verse)
    return by_book


def expand(cell: str, books: dict[str, int], known: dict[int, list[Verse]]) -> list[Verse]:
    if cell.startswith("Absent"):
        return []
    found = []
    for match in REFERENCE.finditer(cell):
        code, chapter, verse, end_chapter, end_verse = match.groups()
        book = books.get(code.upper())
        if not book:
            continue
        start = (int(chapter), None if verse == "Title" else int(verse))
        end = (int(end_chapter or chapter), int(end_verse)) if end_verse else start
        found.extend(v for v in known.get(book, []) if reading_order(start) <= reading_order(v[1:]) <= reading_order(end) and v not in found)
    return found
