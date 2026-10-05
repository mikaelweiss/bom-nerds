"""Book codes each source uses for the 66 books of the Bible, in KJV order."""

import sqlite3

from .rows import row_id
from .text import KJV

# USFM codes. STEPBible and Macula use the same codes in mixed case.
USFM = """GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JOB PSA PRO ECC SNG ISA JER LAM EZK DAN HOS JOL AMO OBA JON MIC NAM HAB ZEP HAG ZEC MAL
MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV""".split()

# OSIS codes, used by OpenBible.
OSIS = """Gen Exod Lev Num Deut Josh Judg Ruth 1Sam 2Sam 1Kgs 2Kgs 1Chr 2Chr Ezra Neh Esth Job Ps Prov Eccl Song Isa Jer Lam Ezek Dan Hos Joel Amos Obad Jonah Mic Nah Hab Zeph Hag Zech Mal
Matt Mark Luke John Acts Rom 1Cor 2Cor Gal Eph Phil Col 1Thess 2Thess 1Tim 2Tim Titus Phlm Heb Jas 1Pet 2Pet 1John 2John 3John Jude Rev""".split()

OLD_TESTAMENT = 39


def bible_books(db: sqlite3.Connection) -> list[int]:
    books = [row[0] for row in db.execute("select book_id from edition_book where edition_id = ? order by position", (row_id(db, "edition", KJV),))]
    assert len(books) == len(USFM), "the KJV must hold the 66 books"
    return books


def codes(db: sqlite3.Connection, scheme: list[str]) -> dict[str, int]:
    """Map each code in a scheme, in any case, to our book id."""
    return {code.upper(): book for code, book in zip(scheme, bible_books(db))}

