"""Passage links a script can find: OpenBible's Bible cross-references, and passages outside the Bible that closely follow it, with their word matches."""

import io
import math
import re
import sqlite3
import zipfile
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from .refs import OLD_TESTAMENT, OSIS, codes, bible_books
from .rows import row_id
from .sources import fetch
from .text import BOOK_OF_MORMON, DOCTRINE_AND_COVENANTS, KJV, PEARL_OF_GREAT_PRICE, WORDS, marks

GRAM = 5
# A five-word phrase found in more verses than this, like "and it came to pass that", says nothing about which verse is followed.
COMMON_GRAM = 20
CLOSE = 0.6
# A run of followed verses may skip this many verses on either side, where one text adds or leaves out a verse.
GAP = 2
# A verse that follows the Bible on its own can share only stock words, as "the Lord spake unto them saying" does with Deuteronomy 2:17.
# It counts when the words it shares are rare enough, scored as the sum of each word's log rarity across Bible verses, or run long and unbroken.
LONE_RARITY = 26
LONE_RUN = 12

# Passages that follow the Bible usually quote it. These books retell the Bible instead.
PARALLEL_BOOKS = {"Moses", "Abraham", "Joseph Smith\u2014Matthew"}
FOLLOWING = (BOOK_OF_MORMON, DOCTRINE_AND_COVENANTS, PEARL_OF_GREAT_PRICE)
QUOTES, PARALLEL, CROSS_REFERENCE = "Quotes", "Parallel", "Cross-reference"

# (book id, chapter, verse). A verse of None is the chapter's heading.
Verse = tuple[int, int, int | None]


def clear(db: sqlite3.Connection):
    kinds = [row_id(db, "link_kind", name) for name in (CROSS_REFERENCE, QUOTES, PARALLEL)]
    db.execute(f"delete from passage_link where link_kind_id in ({marks(kinds)})", kinds)
    editions = [row_id(db, "edition", name) for name in FOLLOWING]
    db.execute(f"delete from word_match where other_word_id in (select w.id from {WORDS} where c.edition_id in ({marks(editions)}))", editions)


def run(db: sqlite3.Connection):
    spans, ids = verse_spans(db)
    cross_references(db, spans, ids)
    followed_passages(db, spans, ids)


def verse_spans(db) -> tuple[dict[tuple[int, Verse], tuple[int, int]], dict[int, int]]:
    """Each verse's first and last word by sequence, and the id of each of those words. Passages here are pairs of sequences."""
    spans, ids = {}, {}
    for e, b, c, v, first, last, first_id, last_id in db.execute(
        "select s.edition_id, s.book_id, s.chapter, s.verse, s.first, s.last, f.id, l.id from ("
        f"select c.edition_id, c.book_id, c.number as chapter, v.number as verse, min(w.sequence) as first, max(w.sequence) as last from {WORDS} group by v.id"
        ") s join word f on f.sequence = s.first join word l on l.sequence = s.last"
    ):
        spans[(e, (b, c, v))] = (first, last)
        ids[first], ids[last] = first_id, last_id
    return spans, ids


def cross_references(db, spans, ids):
    books = codes(db, OSIS)
    kjv = row_id(db, "edition", KJV)
    found = set()
    with zipfile.ZipFile(fetch("cross-references.zip")) as archive:
        lines = io.TextIOWrapper(archive.open("cross_references.txt"), encoding="utf-8").read().splitlines()[1:]
    for line in lines:
        source, target, votes = line.split("\t")[:3]
        if int(votes) <= 0:
            continue
        a, b = passage(source, books, spans, kjv), passage(target, books, spans, kjv)
        if a and b and a != b:
            found.add((*min(a, b), *max(a, b)))
    db.executemany(
        "insert into passage_link (link_kind_id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id) values (?, ?, ?, ?, ?)",
        [(row_id(db, "link_kind", CROSS_REFERENCE), *(ids[s] for s in link)) for link in sorted(found)],
    )
    print(f"links: {len(found)} cross-references")


def passage(reference, books, spans, kjv) -> tuple[int, int] | None:
    ends = []
    for part in reference.split("-"):
        match = re.fullmatch(r"(\w+)\.(\d+)\.(\d+)", part)
        if not match or match.group(1).upper() not in books:
            return None
        verse = (books[match.group(1).upper()], int(match.group(2)), int(match.group(3)))
        if (kjv, verse) not in spans:
            return None
        ends.append(spans[(kjv, verse)])
    return ends[0][0], ends[-1][1]


def followed_passages(db, spans, ids):
    kjv = row_id(db, "edition", KJV)
    parallel_books = {id for id, name in db.execute("select id, name from book") if name in PARALLEL_BOOKS}
    bom = row_id(db, "edition", BOOK_OF_MORMON)
    bible = verse_words(db, kjv)
    old_testament = set(bible_books(db)[:OLD_TESTAMENT])
    index = defaultdict(set)
    for verse, words in bible.items():
        for gram in grams(words):
            index[gram].add(verse)
    common = {gram for gram, verses in index.items() if len(verses) > COMMON_GRAM}
    verses_with = Counter(t for words in bible.values() for t in {t for _, t in words})
    rarity = {t: math.log(len(bible) / count) for t, count in verses_with.items()}

    links = []
    pairs = set()
    for edition in (row_id(db, "edition", name) for name in FOLLOWING):
        followed = {}
        words_of = verse_words(db, edition)
        for verse, words in words_of.items():
            hits = Counter(v for gram in set(grams(words)) - common for v in index.get(gram, ()))
            candidates = sorted(hits.items(), key=lambda hit: (-hit[1], hit[0]))[:3]
            # Verses that score the same, as the Gospels often do, go to the one that comes first, so a run follows one book.
            best = max(((similarity(words, bible[v]), v) for v, _ in sorted(candidates)), key=lambda scored: scored[0], default=(0, None))
            if best[0] >= CLOSE:
                followed[verse] = best[1]
        for run in runs(followed):
            if len(run) == 1 and not distinctive(words_of[run[0][0]], bible[run[0][1]], rarity):
                continue
            source = (spans[(edition, run[0][0])][0], spans[(edition, run[-1][0])][1])
            targets = sorted(target for _, target in run)
            target = (spans[(kjv, targets[0])][0], spans[(kjv, targets[-1])][1])
            for verse, followed_verse in run:
                pairs.update(word_pairs(words_of[verse], bible[followed_verse]))
            book = run[0][0][0]
            if book in parallel_books or (edition == bom and targets[0][0] not in old_testament):
                links.append((PARALLEL, *min(source, target), *max(source, target)))
            else:
                links.append((QUOTES, *source, *target))
    db.executemany(
        "insert into passage_link (link_kind_id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id) values (?, ?, ?, ?, ?)",
        [(row_id(db, "link_kind", kind), *(ids[s] for s in ends)) for kind, *ends in links],
    )
    db.executemany("insert or ignore into word_match (word_id, other_word_id) values (?, ?)", sorted(pairs))
    print(f"links: {len(links)} passages that follow the Bible, {len(pairs)} word matches inside them")


def verse_words(db, edition: int) -> dict[Verse, list[tuple[int, str]]]:
    """Each numbered verse's words as (word id, text), in reading order."""
    verses = defaultdict(list)
    for id, b, c, v, text in db.execute(
        f"select w.id, c.book_id, c.number, v.number, w.text from {WORDS} where c.edition_id = ? and v.number is not null order by w.sequence", (edition,)
    ):
        verses[(b, c, v)].append((id, text.lower().replace("’", "'")))
    return verses


def grams(words):
    texts = [t for _, t in words]
    return [tuple(texts[i:i + GRAM]) for i in range(len(texts) - GRAM + 1)]


def similarity(a, b) -> float:
    return SequenceMatcher(None, [t for _, t in a], [t for _, t in b], autojunk=False).ratio()


def distinctive(a, b, rarity: dict[str, float]) -> bool:
    matcher = SequenceMatcher(None, [t for _, t in a], [t for _, t in b], autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size]
    shared = [t for block in blocks for _, t in a[block.a:block.a + block.size]]
    return sum(rarity[t] for t in shared) >= LONE_RARITY or max((block.size for block in blocks), default=0) >= LONE_RUN


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
