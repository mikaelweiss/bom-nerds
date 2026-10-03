"""Hebrew and Greek layer from Clear Bible's Macula: words, headwords, grammar codes, Hebrew word senses, and syntax."""

import csv
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from .refs import OLD_TESTAMENT, USFM, bible_books
from .sources import checkout, fetch

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

EDITIONS = [
    # edition, TSV, syntax checkout, lowfat file pattern, Strong's prefix
    ("wlc", "macula-hebrew.tsv", "macula-hebrew", "*-lowfat.xml", "H"),
    ("sblgnt", "macula-greek-SBLGNT.tsv", "macula-greek", "[0-9]*.xml", "G"),
]

LANGUAGES = {"H": "hbo", "A": "arc", "G": "grc"}

PARTS_OF_SPEECH = {
    "noun": "noun", "verb": "verb", "preposition": "preposition", "prep": "preposition", "particle": "particle", "ptcl": "particle",
    "conjunction": "conjunction", "conj": "conjunction", "suffix": "pronoun", "pronoun": "pronoun", "pron": "pronoun",
    "adjective": "adjective", "adj": "adjective", "adverb": "adverb", "adv": "adverb", "det": "article", "art": "article",
    "num": "numeral", "ij": "interjection", "intj": "interjection",
}

ROLES = {
    "s": "subject", "v": "verb", "vc": "verb", "aux": "verb", "o": "object", "o2": "object",
    "io": "indirect_object", "p": "complement", "adv": "adverbial", "pp": "adverbial",
}


def clear(db: sqlite3.Connection):
    words = "select id from word where edition_id in ('wlc', 'sblgnt')"
    db.execute(f"delete from sentence where first_word_id in ({words})")
    db.execute(f"delete from word_meaning where word_id in ({words})")
    db.execute(f"delete from word_headword where word_id in ({words})")
    db.execute("delete from meaning where headword_id in (select id from headword where language in ('hbo', 'arc', 'grc'))")
    db.execute("delete from headword where language in ('hbo', 'arc', 'grc')")
    db.execute(f"delete from word where id in ({words})")
    db.execute("delete from edition_book where edition_id in ('wlc', 'sblgnt')")


def run(db: sqlite3.Connection):
    books = dict(zip(USFM, bible_books(db)))
    for edition, tsv, repo, pattern, prefix in EDITIONS:
        codes = USFM[:OLD_TESTAMENT] if edition == "wlc" else USFM[OLD_TESTAMENT:]
        db.executemany("insert into edition_book (edition_id, book_id, position) values (?, ?, ?)", [(edition, books[c], n) for n, c in enumerate(codes, 1)])
        rows = list(csv.DictReader(open(fetch(tsv), encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE))
        ids = insert_words(db, edition, rows, books)
        insert_headwords(db, rows, ids, prefix)
        insert_syntax(db, checkout(repo), pattern, ids)
        print(f"{edition}: {len(rows)} words")


def insert_words(db, edition, rows, books) -> dict[str, int]:
    verses = defaultdict(list)
    for row in rows:
        book, chapter_verse = row["ref"].split("!")[0].split()
        chapter, verse = map(int, chapter_verse.split(":"))
        verses[(books[book], chapter, verse)].append(row)
    values = []
    for (book, chapter, verse), words in verses.items():
        for position, row in enumerate(words, 1):
            after = row["after"]
            if position == len(words):
                after = after.rstrip()
            elif not after.endswith(" ") and edition == "sblgnt":
                # Macula Greek drops the space after punctuation.
                after += " "
            values.append((edition, book, chapter, verse, position, row["text"], after))
    db.executemany("insert into word (edition_id, book_id, chapter, verse, position, text, after) values (?, ?, ?, ?, ?, ?, ?)", values)
    stored = [row[0] for row in db.execute("select id from word where edition_id = ? order by id", (edition,))]
    order = [row for words in verses.values() for row in words]
    return {row["xml:id"]: word_id for row, word_id in zip(order, stored)}


def strongs(row, prefix) -> str | None:
    number = row.get("strongnumberx") or row.get("strong") or ""
    digits = number.rstrip("abcdefghijklmnopqrstuvwxyz")
    return f"{prefix}{digits.zfill(4)}{number[len(digits):]}" if digits.isdigit() else None


def insert_headwords(db, rows, ids, prefix):
    glosses = defaultdict(Counter)
    for row in rows:
        if row["lemma"]:
            glosses[headword_key(row, prefix)][row["english"]] += 1
    for key, counts in glosses.items():
        db.execute("insert into headword (language, text, strongs, gloss) values (?, ?, ?, ?)", (*key, most_common(counts)))
    headwords = {(language, text, number): id for id, language, text, number in db.execute("select id, language, text, strongs from headword")}

    senses = defaultdict(Counter)
    tagged = []
    for row in rows:
        if not row["lemma"]:
            continue
        headword = headwords[headword_key(row, prefix)]
        part_of_speech = "proper_noun" if row.get("type") == "proper" else PARTS_OF_SPEECH.get(row["class"]) or PARTS_OF_SPEECH.get(row.get("pos"))
        if part_of_speech:
            tagged.append((ids[row["xml:id"]], headword, part_of_speech, row["morph"] or None))
        if row.get("sensenumber"):
            senses[(headword, int(row["sensenumber"]))][row["english"]] += 1
    db.executemany("insert into word_headword (word_id, headword_id, part_of_speech, grammar) values (?, ?, ?, ?)", tagged)

    for (headword, number), counts in senses.items():
        db.execute("insert into meaning (headword_id, number, gloss) values (?, ?, ?)", (headword, number, most_common(counts)))
    meanings = {(headword, number): id for id, headword, number in db.execute("select id, headword_id, number from meaning")}
    db.executemany(
        "insert into word_meaning (word_id, meaning_id) values (?, ?)",
        [(ids[row["xml:id"]], meanings[(headwords[headword_key(row, prefix)], int(row["sensenumber"]))]) for row in rows if row["lemma"] and row.get("sensenumber")],
    )


def headword_key(row, prefix):
    return LANGUAGES[row.get("lang") or prefix], row["lemma"], strongs(row, prefix)


def most_common(counts: Counter) -> str:
    return next((text for text, _ in counts.most_common() if text), "")


def insert_syntax(db, folder, pattern, ids):
    for path in sorted(folder.glob(pattern)):
        for sentence in ET.parse(path).iter("sentence"):
            insert_sentence(db, sentence, ids)


def insert_sentence(db, sentence, ids):
    parents = {child: parent for parent in sentence.iter() for child in parent}

    def span(element):
        words = [ids[w.get(XML_ID)] for w in element.iter("w")]
        return min(words), max(words)

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
        role = ROLES.get(element.get("role"))
        clause = clauses.get(clause_of(element))
        if role and clause and any(True for _ in element.iter("w")):
            db.execute("insert into clause_part (clause_id, role_id, first_word_id, last_word_id) values (?, ?, ?, ?)", (clause, role, *span(element)))


def is_clause(element) -> bool:
    return element.tag == "wg" and element.get("class") == "cl" and any(True for _ in element.iter("w"))
