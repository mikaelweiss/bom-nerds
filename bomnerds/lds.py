"""Reads bcbooks/scriptures-json for the Book of Mormon, Doctrine and Covenants, and Pearl of Great Price."""

import json
import re
from pathlib import Path

from .words import Book, rebuild, split


def book_of_mormon(path: Path) -> list[Book]:
    source = json.loads(path.read_text())
    page = source["title_page"]
    title_page = Book("Title Page")
    add(title_page, 1, None, page["title"], page["subtitle"])
    for number, paragraph in enumerate(page["text"], 1):
        add(title_page, 1, number, paragraph)
    add(title_page, 1, len(page["text"]), page["translated_by"])
    books = [title_page]

    for testimony in source["testimonies"]:
        book = Book(testimony["title"])
        add(book, 1, None, testimony["title"])
        add(book, 1, 1, testimony["text"], *testimony["witnesses"])
        books.append(book)

    for entry in source["books"]:
        book = Book(entry["book"])
        for chapter in entry["chapters"]:
            if chapter["chapter"] == 1:
                add(book, 1, None, entry["full_title"], entry.get("full_subtitle"), entry.get("heading"))
            add(book, chapter["chapter"], None, chapter.get("heading"))
            add_verses(book, chapter["chapter"], chapter["verses"])
        books.append(book)
    return books


def doctrine_and_covenants(path: Path) -> list[Book]:
    source = json.loads(path.read_text())
    book = Book("Doctrine and Covenants")
    for section in source["sections"]:
        add_verses(book, section["section"], section["verses"])
        add(book, section["section"], section["verses"][-1]["verse"], section.get("signature"))
    return [book]


def pearl_of_great_price(path: Path) -> list[Book]:
    source = json.loads(path.read_text())
    books = []
    for entry in source["books"]:
        book = Book(entry["book"])
        add(book, 1, None, entry["full_title"], entry.get("full_subtitle"))
        for chapter in entry["chapters"]:
            add_verses(book, chapter["chapter"], chapter["verses"])
        books.append(book)
        for facsimile in entry.get("facsimiles", []):
            books.append(facsimile_book(facsimile))
    return books


def facsimile_book(facsimile: dict) -> Book:
    book = Book(f"Facsimile {facsimile['number']}")
    add(book, 1, None, facsimile["title"])
    for explanation in facsimile["explanations"]:
        number, text = re.fullmatch(r"(\d+)\. (.*)", explanation, re.S).groups()
        add(book, 1, int(number), text)
    add(book, 1, int(number), facsimile.get("note"))
    return book


def add_verses(book: Book, chapter: int, verses: list[dict]):
    for verse in verses:
        add(book, chapter, verse["verse"], verse["text"])


def add(book: Book, chapter: int, verse: int | None, *lines: str | None):
    """Add lines to a verse, or to the chapter's heading where verse is None, each on its own line after any text it already has."""
    lines = [line for line in lines if line]
    if not lines:
        return
    existing = book.verses.get((chapter, verse))
    text = "\n".join(([rebuild(existing)] if existing else []) + lines)
    book.verses[(chapter, verse)] = split(text)
