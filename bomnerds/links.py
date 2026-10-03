"""Passage links a script can find: OpenBible's Bible cross-references, and passages outside the Bible that closely follow it, with their word matches."""

import io
import re
import sqlite3
import zipfile
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from .refs import OLD_TESTAMENT, OSIS, codes, bible_books
from .sources import fetch

GRAM = 5
# A five-word phrase found in more verses than this, like "and it came to pass that", says nothing about which verse is followed.
COMMON_GRAM = 20
CLOSE = 0.6
# A run of followed verses may skip this many verses on either side, where one text adds or leaves out a verse.
GAP = 2

# Passages that follow the Bible usually quote it. These books retell the Bible instead.
PARALLEL_BOOKS = {"moses", "abraham", "joseph-smith-matthew"}

Verse = tuple[str, int, int]


def clear(db: sqlite3.Connection):
    db.execute("delete from passage_link where kind_id in ('cross_reference', 'quotes', 'parallel')")
    other = "select id from word where edition_id in ('bom-2013', 'dc-2013', 'pgp-2013')"
    db.execute(f"delete from word_match where other_word_id in ({other})")


def run(db: sqlite3.Connection):
    spans = verse_spans(db)
    cross_references(db, spans)
    followed_passages(db, spans)


def verse_spans(db) -> dict[tuple[str, Verse], tuple[int, int]]:
    return {(e, (b, c, v)): (first, last) for e, b, c, v, first, last in db.execute(
        "select edition_id, book_id, chapter, verse, min(id), max(id) from word group by edition_id, book_id, chapter, verse"
    )}


def cross_references(db, spans):
    books = codes(db, OSIS)
    found = set()
    with zipfile.ZipFile(fetch("cross-references.zip")) as archive:
        lines = io.TextIOWrapper(archive.open("cross_references.txt"), encoding="utf-8").read().splitlines()[1:]
    for line in lines:
        source, target, votes = line.split("\t")[:3]
        if int(votes) <= 0:
            continue
        a, b = passage(source, books, spans), passage(target, books, spans)
        if a and b and a != b:
            found.add((*min(a, b), *max(a, b)))
    db.executemany(
        "insert into passage_link (kind_id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id) values ('cross_reference', ?, ?, ?, ?)",
        sorted(found),
    )
    print(f"links: {len(found)} cross-references")


def passage(reference, books, spans) -> tuple[int, int] | None:
    ends = []
    for part in reference.split("-"):
        match = re.fullmatch(r"(\w+)\.(\d+)\.(\d+)", part)
        if not match or match.group(1).upper() not in books:
            return None
        verse = (books[match.group(1).upper()], int(match.group(2)), int(match.group(3)))
        if ("kjv", verse) not in spans:
            return None
        ends.append(spans[("kjv", verse)])
    return ends[0][0], ends[-1][1]


def followed_passages(db, spans):
    bible = verse_words(db, "kjv")
    old_testament = set(bible_books(db)[:OLD_TESTAMENT])
    index = defaultdict(set)
    for verse, words in bible.items():
        for gram in grams(words):
            index[gram].add(verse)
    common = {gram for gram, verses in index.items() if len(verses) > COMMON_GRAM}

    links = []
    pairs = set()
    for edition in ("bom-2013", "dc-2013", "pgp-2013"):
        followed = {}
        for verse, words in verse_words(db, edition).items():
            hits = Counter(v for gram in set(grams(words)) - common for v in index.get(gram, ()))
            candidates = sorted(hits.items(), key=lambda hit: (-hit[1], hit[0]))[:3]
            best = max(((similarity(words, bible[v]), v) for v, _ in candidates), default=(0, None))
            if best[0] >= CLOSE:
                followed[verse] = best[1]
                pairs.update(word_pairs(words, bible[best[1]]))
        for run in runs(followed):
            source = (spans[(edition, run[0][0])][0], spans[(edition, run[-1][0])][1])
            targets = sorted(target for _, target in run)
            target = (spans[("kjv", targets[0])][0], spans[("kjv", targets[-1])][1])
            book = run[0][0][0]
            if book in PARALLEL_BOOKS or (edition == "bom-2013" and targets[0][0] not in old_testament):
                links.append(("parallel", *min(source, target), *max(source, target)))
            else:
                links.append(("quotes", *source, *target))
    db.executemany(
        "insert into passage_link (kind_id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id) values (?, ?, ?, ?, ?)", links
    )
    db.executemany("insert or ignore into word_match (word_id, other_word_id) values (?, ?)", sorted(pairs))
    print(f"links: {len(links)} passages that follow the Bible, {len(pairs)} word matches inside them")


def verse_words(db, edition) -> dict[Verse, list[tuple[int, str]]]:
    verses = defaultdict(list)
    for id, b, c, v, text in db.execute("select id, book_id, chapter, verse, text from word where edition_id = ? and verse > 0 order by id", (edition,)):
        verses[(b, c, v)].append((id, text.lower().replace("’", "'")))
    return verses


def grams(words):
    texts = [t for _, t in words]
    return [tuple(texts[i:i + GRAM]) for i in range(len(texts) - GRAM + 1)]


def similarity(a, b) -> float:
    return SequenceMatcher(None, [t for _, t in a], [t for _, t in b], autojunk=False).ratio()


def word_pairs(a, b):
    """Pair the same words, and changed words where one text swaps in as many words as it takes out."""
    matcher = SequenceMatcher(None, [t for _, t in a], [t for _, t in b], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for (x, _), (y, _) in zip(a[i1:i2], b[j1:j2]):
                yield min(x, y), max(x, y)


def runs(followed: dict[Verse, Verse]) -> list[list[tuple[Verse, Verse]]]:
    """Group followed verses into passages: nearby verses in one chapter that follow nearby verses of one Bible book."""
    grouped = []
    for verse, target in sorted(followed.items()):
        if grouped:
            last, last_target = grouped[-1][-1]
            if verse[:2] == last[:2] and verse[2] - last[2] <= GAP + 1 and comes_soon_after(target, last_target):
                grouped[-1].append((verse, target))
                continue
        grouped.append([(verse, target)])
    return grouped


def comes_soon_after(verse: Verse, previous: Verse) -> bool:
    book, chapter, number = verse
    if book != previous[0]:
        return False
    if chapter == previous[1]:
        return 0 < number - previous[2] <= GAP + 1
    return chapter == previous[1] + 1 and number <= GAP + 1
