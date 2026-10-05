"""Hebrew and Greek layer from Clear Bible's Macula: words, headwords, grammar, Hebrew word senses, and syntax."""

import csv
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from . import morphology
from .refs import OLD_TESTAMENT, USFM, bible_books
from .rows import row_id
from .sources import checkout, fetch
from .text import SBLGNT, WLC, WORDS, insert_text, marks, number_words
from .words import Word, reading_order

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

EDITIONS = [
    # edition, TSV, syntax checkout, lowfat file pattern, Strong's prefix
    (WLC, "macula-hebrew.tsv", "macula-hebrew", "*-lowfat.xml", "H"),
    (SBLGNT, "macula-greek-SBLGNT.tsv", "macula-greek", "[0-9]*.xml", "G"),
]

LANGUAGES = {"H": "hbo", "A": "arc", "G": "grc"}

# Robinson gives a transliterated Hebrew or Aramaic word no part of speech, so Macula's class supplies it.
CLASSES = {"noun": "Noun", "adv": "Adverb", "verb": "Verb", "ptcl": "Particle"}

ROLES = {
    "s": "Subject", "v": "Verb", "vc": "Verb", "aux": "Verb", "o": "Object", "o2": "Object",
    "io": "Indirect object", "p": "Complement", "adv": "Adverbial", "pp": "Adverbial",
}

HEBREW_COLUMNS = ("word_type", "stem", "verb_form", "person", "gender", "grammatical_number", "state")
GREEK_COLUMNS = (
    "word_type", "tense", "second_form", "voice", "mood", "person", "grammatical_case", "gender", "grammatical_number",
    "possessor_number", "degree", "indeclinable", "crasis", "attic_form", "transliterated_from",
)
# The value list each feature names a row of. Features missing here are stored as they are.
LISTS = {
    "word_type": "word_type", "stem": "stem", "verb_form": "verb_form", "gender": "gender", "grammatical_number": "grammatical_number",
    "state": "state", "tense": "tense", "voice": "voice", "mood": "mood", "grammatical_case": "grammatical_case",
    "possessor_number": "grammatical_number", "degree": "degree",
}


def clear(db: sqlite3.Connection):
    editions = [row_id(db, "edition", name) for name, *_ in EDITIONS]
    languages = [row_id(db, "language", code, "iso_code") for code in LANGUAGES.values()]
    words = f"select w.id from {WORDS} where c.edition_id in ({marks(editions)})"
    db.execute(f"delete from sentence where first_word_id in ({words})", editions)
    db.execute(f"delete from hebrew_word where word_id in ({words})", editions)
    db.execute(f"delete from greek_word where word_id in ({words})", editions)
    db.execute(f"delete from word where id in ({words})", editions)
    db.execute(f"delete from verse where chapter_id in (select id from chapter where edition_id in ({marks(editions)}))", editions)
    db.execute(f"delete from chapter where edition_id in ({marks(editions)})", editions)
    db.execute(f"delete from meaning where headword_id in (select id from headword where language_id in ({marks(languages)}))", languages)
    db.execute(f"delete from headword where language_id in ({marks(languages)})", languages)
    db.execute(f"delete from edition_book where edition_id in ({marks(editions)})", editions)


def run(db: sqlite3.Connection):
    books = dict(zip(USFM, bible_books(db)))
    bible = row_id(db, "work", "Bible")
    for name, tsv, repo, pattern, prefix in EDITIONS:
        edition = row_id(db, "edition", name)
        codes = USFM[:OLD_TESTAMENT] if prefix == "H" else USFM[OLD_TESTAMENT:]
        db.executemany(
            "insert into edition_book (edition_id, book_id, work_id, position) values (?, ?, ?, ?)", [(edition, books[c], bible, n) for n, c in enumerate(codes, 1)]
        )
        rows = list(csv.DictReader(open(fetch(tsv), encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE))
        ids, sequences = insert_words(db, edition, rows, books)
        insert_headwords(db, rows, ids, prefix)
        insert_grammar(db, rows, ids, prefix)
        insert_syntax(db, checkout(repo), pattern, ids, sequences)
        print(f"{name}: {len(rows)} words")
    number_words(db)


def insert_words(db, edition, rows, books) -> tuple[dict[str, int], dict[int, int]]:
    """Insert the words, and return each Macula word's id and each word id's sequence."""
    greek = edition == row_id(db, "edition", SBLGNT)
    verses = defaultdict(lambda: defaultdict(list))
    for row in rows:
        book, chapter_verse = row["ref"].split("!")[0].split()
        chapter, verse = map(int, chapter_verse.split(":"))
        verses[books[book]][(chapter, verse)].append(row)
    order = []
    for book, chapters in verses.items():
        words = {}
        for key, found in chapters.items():
            words[key] = []
            for position, row in enumerate(found, 1):
                after = row["after"]
                if position == len(found):
                    after = after.rstrip()
                elif not after.endswith(" ") and greek:
                    # Macula Greek drops the space after punctuation.
                    after += " "
                words[key].append(Word(row["text"], after=after))
        insert_text(db, edition, book, words)
        order += [row for key in sorted(chapters, key=reading_order) for row in chapters[key]]
    stored = list(db.execute(f"select w.id, w.sequence from {WORDS} where c.edition_id = ? order by w.sequence", (edition,)))
    return {row["xml:id"]: id for row, (id, _) in zip(order, stored)}, dict(stored)


def strongs(row, prefix) -> str | None:
    number = row.get("strongnumberx") or row.get("strong") or ""
    digits = number.rstrip("abcdefghijklmnopqrstuvwxyz")
    return f"{prefix}{digits.zfill(4)}{number[len(digits):]}" if digits.isdigit() else None


def insert_headwords(db, rows, ids, prefix):
    languages = {code: row_id(db, "language", iso_code, "iso_code") for code, iso_code in LANGUAGES.items()}
    glosses = defaultdict(Counter)
    for row in rows:
        if row["lemma"]:
            glosses[headword_key(row, prefix, languages)][row["english"]] += 1
    for key, counts in glosses.items():
        db.execute("insert into headword (language_id, text, strongs, gloss) values (?, ?, ?, ?)", (*key, most_common(counts)))
    headwords = {(language, text, number): id for id, language, text, number in db.execute("select id, language_id, text, strongs from headword")}

    senses = defaultdict(Counter)
    for row in rows:
        if row["lemma"] and row.get("sensenumber"):
            senses[(headwords[headword_key(row, prefix, languages)], int(row["sensenumber"]))][row["english"]] += 1
    for (headword, number), counts in senses.items():
        db.execute("insert into meaning (headword_id, number, gloss) values (?, ?, ?)", (headword, number, most_common(counts)))
    meanings = {(headword, number): id for id, headword, number in db.execute("select id, headword_id, number from meaning")}

    updates = []
    for row in rows:
        if not row["lemma"]:
            continue
        headword = headwords[headword_key(row, prefix, languages)]
        meaning = meanings[(headword, int(row["sensenumber"]))] if row.get("sensenumber") else None
        updates.append((headword, meaning, ids[row["xml:id"]]))
    db.executemany("update word set headword_id = ?, meaning_id = ? where id = ?", updates)


def headword_key(row, prefix, languages):
    return languages[row.get("lang") or prefix], row["lemma"], strongs(row, prefix)


def most_common(counts: Counter) -> str:
    return next((text for text, _ in counts.most_common() if text), "")


def insert_grammar(db, rows, ids, prefix):
    """Each word's grammar code, feature by feature, and its part of speech."""
    found = {}

    def value(table, name):
        if (table, name) not in found:
            found[(table, name)] = row_id(db, table, name)
        return found[(table, name)]

    table, columns = ("hebrew_word", HEBREW_COLUMNS) if prefix == "H" else ("greek_word", GREEK_COLUMNS)
    grammar, parts_of_speech = [], []
    for row in rows:
        features = morphology.hebrew(row["morph"], row["lang"] == "A") if prefix == "H" else morphology.greek(row["morph"])
        part_of_speech = features.pop("part_of_speech", None) or CLASSES[row["class"]]
        # Robinson codes a Greek name that declines as a plain noun. Macula marks it proper.
        if part_of_speech == "Noun" and row.get("type") == "proper":
            part_of_speech = "Proper noun"
        if "transliterated_from" in features:
            features["transliterated_from"] = row_id(db, "language", features["transliterated_from"], "iso_code")
        cells = [value(LISTS[c], features[c]) if c in LISTS and c in features else features.get(c) for c in columns]
        grammar.append((ids[row["xml:id"]], *cells))
        parts_of_speech.append((value("part_of_speech", part_of_speech), ids[row["xml:id"]]))
    names = [f"{c}_id" if c in LISTS or c == "transliterated_from" else c for c in columns]
    db.executemany(f"insert into {table} (word_id, {', '.join(names)}) values (?, {marks(names)})", grammar)
    db.executemany("update word set part_of_speech_id = ? where id = ?", parts_of_speech)


def insert_syntax(db, folder, pattern, ids, sequences):
    roles = {code: row_id(db, "clause_role", name) for code, name in ROLES.items()}
    for path in sorted(folder.glob(pattern)):
        for sentence in ET.parse(path).iter("sentence"):
            insert_sentence(db, sentence, ids, sequences, roles)


def insert_sentence(db, sentence, ids, sequences, roles):
    parents = {child: parent for parent in sentence.iter() for child in parent}

    def span(element):
        words = [ids[w.get(XML_ID)] for w in element.iter("w")]
        return min(words, key=sequences.get), max(words, key=sequences.get)

    def clause_of(element):
        ancestor = parents.get(element)
        while ancestor is not None and not is_clause(ancestor):
            ancestor = parents.get(ancestor)
        return ancestor

    sentence_id = db.execute("insert into sentence (first_word_id, last_word_id) values (?, ?)", span(sentence)).lastrowid
    clauses = {}
    for element in sentence.iter():
        if is_clause(element):
            parent = clauses.get(clause_of(element))
            clauses[element] = db.execute(
                "insert into clause (sentence_id, parent_id, first_word_id, last_word_id) values (?, ?, ?, ?)", (sentence_id, parent, *span(element))
            ).lastrowid
    for element in sentence.iter():
        role = roles.get(element.get("role"))
        clause = clauses.get(clause_of(element))
        if role and clause and any(True for _ in element.iter("w")):
            db.execute("insert into clause_part (clause_id, clause_role_id, first_word_id, last_word_id) values (?, ?, ?, ?)", (clause, role, *span(element)))


def is_clause(element) -> bool:
    return element.tag == "wg" and element.get("class") == "cl" and any(True for _ in element.iter("w"))
