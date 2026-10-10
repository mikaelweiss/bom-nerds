"""Split the Hebrew into sentences where the matched KJV sentences break, cutting only between clauses."""

import bisect
import sqlite3
import sys
from collections import Counter, defaultdict

KJV = 1
HEBREW = 2


def main(path):
    db = sqlite3.connect(path)
    db.execute("pragma foreign_keys = on")

    words = db.execute(
        "select w.id, w.sequence, c.book_id from word w join verse v on v.id = w.verse_id "
        "join chapter c on c.id = v.chapter_id where c.edition_id = ? order by w.sequence",
        (HEBREW,),
    ).fetchall()
    seq = {w: s for w, s, _ in words}

    starts, ends = [], []
    for first, last in db.execute(
        "select a.sequence, b.sequence from sentence s join word a on a.id = s.first_word_id "
        "join word b on b.id = s.last_word_id join verse v on v.id = a.verse_id "
        "join chapter c on c.id = v.chapter_id where c.edition_id = ? order by a.sequence",
        (KJV,),
    ):
        starts.append(first)
        ends.append(last)
    kjv_seq = dict(db.execute(
        "select w.id, w.sequence from word w join verse v on v.id = w.verse_id "
        "join chapter c on c.id = v.chapter_id where c.edition_id = ?", (KJV,)
    ))

    def english_sentence(english_word):
        s = kjv_seq.get(english_word)
        if s is None:
            return None
        i = bisect.bisect_right(starts, s) - 1
        return i if i >= 0 and s <= ends[i] else None

    sentence_of = defaultdict(Counter)
    for a, b in db.execute("select word_id, other_word_id from word_match"):
        for english, other in ((a, b), (b, a)):
            if other in seq:
                i = english_sentence(english)
                if i is not None:
                    sentence_of[other][i] += 1

    clauses = sorted(
        (seq[a], seq[b])
        for a, b in db.execute("select first_word_id, last_word_id from clause where parent_id is null")
        if a in seq
    )
    merged = []
    for first, last in clauses:
        if merged and first <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], last)
        else:
            merged.append([first, last])
    # Cut right after each clause ends, so the conjunction that opens the next clause starts the next region.
    sequences = [s for _, s, _ in words]
    cuts = {sequences[i] for i in (bisect.bisect_right(sequences, end) for _, end in merged[:-1]) if i < len(sequences)}

    regions = []
    current = []
    book = None
    for word, s, b in words:
        if current and (b != book or s in cuts):
            regions.append((book, current))
            current = []
        book = b
        current.append((word, s))
    regions.append((book, current))

    labels = []
    for b, region in regions:
        votes = Counter()
        for word, _ in region:
            votes.update(sentence_of.get(word, {}))
        labels.append(votes.most_common(1)[0][0] if votes else None)

    spans = []
    previous_book = previous_label = None
    for (b, region), label in zip(regions, labels):
        if b != previous_book:
            previous_label = None
        if label is None or (previous_label is not None and label < previous_label):
            label = previous_label
        if spans and b == previous_book and (label is None or label == previous_label):
            spans[-1][1] = region[-1][0]
        else:
            spans.append([region[0][0], region[-1][0]])
        previous_book, previous_label = b, label

    old = dict(db.execute(
        "select s.first_word_id || ':' || s.last_word_id, s.id from sentence s join word a on a.id = s.first_word_id "
        "join verse v on v.id = a.verse_id join chapter c on c.id = v.chapter_id where c.edition_id = ?",
        (HEBREW,),
    ))
    keep = set()
    span_ids = []
    for first, last in spans:
        existing = old.get(f"{first}:{last}")
        if existing is None:
            existing = db.execute(
                "insert into sentence (first_word_id, last_word_id) values (?, ?)", (first, last)
            ).lastrowid
        keep.add(existing)
        span_ids.append((seq[first], seq[last], existing))

    span_starts = [s for s, _, _ in span_ids]
    for clause, first in db.execute("select id, first_word_id from clause").fetchall():
        if first not in seq:
            continue
        i = bisect.bisect_right(span_starts, seq[first]) - 1
        db.execute("update clause set sentence_id = ? where id = ?", (span_ids[i][2], clause))

    stale = [i for i in old.values() if i not in keep]
    db.executemany("delete from sentence where id = ?", [(i,) for i in stale])
    db.commit()
    print(f"{len(spans)} Hebrew sentences ({len(old)} before)")


if __name__ == "__main__":
    main(sys.argv[1])
