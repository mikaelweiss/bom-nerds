"""Give Hebrew and Greek headwords that have no meanings the STEPBible senses, and tag each word with its sense.

    python fill_original_meanings.py scripture.db SOURCE_DIR

SOURCE_DIR holds the STEPBible-Data files TAHOT_*.txt, TAGNT_*.txt, TBESH.txt, and TBESG.txt.
Headwords that already have meanings keep them.
"""

import difflib
import glob
import html
import os
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict

STEP_BOOKS = (
    "Gen Exo Lev Num Deu Jos Jdg Rut 1Sa 2Sa 1Ki 2Ki 1Ch 2Ch Ezr Neh Est Job Psa Pro Ecc Sng Isa Jer Lam Ezk Dan "
    "Hos Jol Amo Oba Jon Mic Nam Hab Zep Hag Zec Mal Mat Mrk Luk Jhn Act Rom 1Co 2Co Gal Eph Php Col 1Th 2Th 1Ti "
    "2Ti Tit Phm Heb Jas 1Pe 2Pe 1Jn 2Jn 3Jn Jud Rev"
).split()
REFERENCE = re.compile(r"^(\w+)\.(\d+)\.(\d+)(?:\((\d+)\.(\d+)\))?#")
HEBREW, GREEK = 2, 3


def plain(text):
    """Letters only, without vowels, accents, or case, for matching the same word across sources."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c).startswith("L")).lower()


def step_hebrew(source):
    verses = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(source, "TAHOT_*.txt"))):
        for line in open(path, encoding="utf-8"):
            match = REFERENCE.match(line)
            if not match:
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 5:
                continue
            book, chapter, verse, hebrew_chapter, hebrew_verse = match.groups()
            key = (book, int(hebrew_chapter or chapter), int(hebrew_verse or verse))
            segments = fields[1].split("\\")[0].split("/")
            tags = [t for t in re.split(r"[/\\]", fields[4]) if t]
            tags = [t.strip("{}") for t in tags if not t.strip("{}").startswith(("H9014", "H9015", "H9016"))]
            if len(segments) != len(tags):
                continue
            verses[key].extend(zip(segments, tags))
    return verses


def step_greek(source):
    verses = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(source, "TAGNT_*.txt"))):
        for line in open(path, encoding="utf-8"):
            match = REFERENCE.match(line)
            if not match:
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 6 or "SBL" not in fields[5]:
                continue
            book, chapter, verse, _, _ = match.groups()
            greek = fields[1].split(" (")[0]
            verses[book, int(chapter), int(verse)].append((greek, fields[3].split("=")[0]))
    return verses


def lexicon(path):
    entries = {}
    for line in open(path, encoding="utf-8"):
        fields = line.rstrip("\n").split("\t")
        key = fields[1].split(" ")[0] if len(fields) >= 8 else ""
        if not re.match(r"^[HG]\d{4}[A-Za-z]?$", key):
            continue
        entries[key] = (fields[6].strip(), clean(fields[7]), plain(fields[3]))
    return entries


def clean(definition):
    text = re.sub(r"<br\s*/?>", "\n", definition, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("__", "")
    lines = [re.sub(r"\s+", " ", line).strip(" :") for line in text.split("\n")]
    return "\n".join(line for line in lines if line) or None


def lookup(entries, tag):
    if tag in entries:
        return tag
    base = tag[:5]
    for candidate in (base, base + "G", base + "A", base + "a"):
        if candidate in entries:
            return candidate
    return None


def tag_words(db, edition, step_verses):
    book_ids = [b for (b,) in db.execute(
        "select book_id from edition_book where edition_id = 1 order by position")]
    step_book = dict(zip(book_ids, STEP_BOOKS))
    ours = defaultdict(list)
    for word, text, book, chapter, verse in db.execute(
        "select w.id, w.text, c.book_id, c.number, v.number from word w join verse v on v.id = w.verse_id "
        "join chapter c on c.id = v.chapter_id where c.edition_id = ? order by w.sequence", (edition,)
    ):
        ours[step_book[book], chapter, verse or 0].append((word, text))

    tags = {}
    for key, words in ours.items():
        theirs = step_verses.get(key)
        if not theirs:
            continue
        a = [plain(t) for _, t in words]
        b = [plain(t) for t, _ in theirs]
        matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for block in matcher.get_matching_blocks():
            for k in range(block.size):
                tags[words[block.a + k][0]] = theirs[block.b + k][1]
    return tags


def agrees(strongs, lemma, entry, entries):
    """A tag fits a headword when their Strong's numbers or lemmas match, or the tag is one of STEPBible's affix numbers."""
    if not strongs or entry.startswith("H9") or plain(lemma) == entries[entry][2]:
        return True
    return int(re.sub(r"\D", "", strongs) or 0) == int(entry[1:5])


def fill(db, edition, tags, entries):
    language_ids = [i for (i,) in db.execute(
        "select distinct h.language_id from word w join headword h on h.id = w.headword_id join verse v on v.id = w.verse_id "
        "join chapter c on c.id = v.chapter_id where c.edition_id = ?", (edition,))]
    bare = {h for (h,) in db.execute(
        f"select id from headword where language_id in ({','.join('?' * len(language_ids))}) "
        "and id not in (select headword_id from meaning)", language_ids)}

    words = defaultdict(list)
    for word, headword, strongs, lemma in db.execute(
        "select w.id, w.headword_id, h.strongs, h.text from word w join headword h on h.id = w.headword_id "
        "join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id "
        "where c.edition_id = ? and w.meaning_id is null", (edition,)
    ):
        if headword not in bare or word not in tags:
            continue
        entry = lookup(entries, tags[word])
        if entry and agrees(strongs, lemma, entry, entries):
            words[headword].append((word, entry))

    added_meanings = tagged = 0
    for headword, tagged_words in words.items():
        senses = sorted({entry for _, entry in tagged_words})
        meaning_of = {}
        for number, entry in enumerate(senses, 1):
            gloss, definition, _ = entries[entry]
            meaning_of[entry] = db.execute(
                "insert into meaning (headword_id, number, gloss, definition) values (?, ?, ?, ?)",
                (headword, number, gloss or entry, definition),
            ).lastrowid
            added_meanings += 1
        db.executemany(
            "update word set meaning_id = ? where id = ?",
            [(meaning_of[entry], word) for word, entry in tagged_words],
        )
        tagged += len(tagged_words)
    return len(words), added_meanings, tagged


def fill_single_senses(db, edition):
    """Words whose headword has exactly one meaning take that meaning."""
    return db.execute(
        "update word set meaning_id = (select min(m.id) from meaning m where m.headword_id = word.headword_id) "
        "where meaning_id is null and headword_id in (select headword_id from meaning group by headword_id having count(*) = 1) "
        "and verse_id in (select v.id from verse v join chapter c on c.id = v.chapter_id where c.edition_id = ?)",
        (edition,),
    ).rowcount


def main(path, source):
    db = sqlite3.connect(path)
    db.execute("pragma foreign_keys = on")
    for edition, step_verses, lexicon_file in (
        (HEBREW, step_hebrew(source), "TBESH.txt"),
        (GREEK, step_greek(source), "TBESG.txt"),
    ):
        entries = lexicon(os.path.join(source, lexicon_file))
        tags = tag_words(db, edition, step_verses)
        headwords, meanings, tagged = fill(db, edition, tags, entries)
        single = fill_single_senses(db, edition)
        print(f"edition {edition}: {len(tags)} words lined up with STEPBible, "
              f"{headwords} headwords given {meanings} meanings, {tagged} words tagged, "
              f"{single} more words given their headword's only meaning")
    db.commit()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
