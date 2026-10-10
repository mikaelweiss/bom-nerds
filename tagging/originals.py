"""Carry the King James Version's mentions onto the Hebrew and Greek editions.

    python3 tagging/originals.py [PASSAGE ...]

PASSAGE is a Bible book and chapter or chapter range, as in "Genesis 1" or
"Malachi 3-4". With none, every chapter is carried. The Hebrew and Greek
mentions of the chosen chapters are rebuilt from the King James mentions
through word_match, so rerun this after retagging a chapter.
"""

import argparse
import re
import sqlite3
from bisect import bisect_left
from collections import Counter, defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "scripture.db"
KJV, HEBREW, GREEK = 1, 2, 3
REFERS_TO = 1
PRONOUN_FORMS = ("Pronoun", "Suffix", "Article")
NOUNS = ("Noun", "Proper noun")


class Text:
    def __init__(self, db: sqlite3.Connection):
        self.sequence = {}
        self.verse = {}
        self.chapter = {}
        self.edition = {}
        self.at = {}
        self.part = {}
        for wid, sequence, verse, chapter, edition, part in db.execute(
            "select w.id, w.sequence, w.verse_id, v.chapter_id, c.edition_id, p.name from word w join verse v on v.id = w.verse_id"
            " join chapter c on c.id = v.chapter_id left join part_of_speech p on p.id = w.part_of_speech_id where c.edition_id in (?, ?, ?)",
            (KJV, HEBREW, GREEK),
        ):
            self.part[wid] = part
            self.sequence[wid] = sequence
            self.verse[wid] = verse
            self.chapter[wid] = chapter
            self.edition[wid] = edition
            self.at[sequence] = wid
        self.verse_words = defaultdict(list)
        for wid in sorted(self.sequence, key=self.sequence.get):
            self.verse_words[self.verse[wid]].append(wid)
        self.book = dict(db.execute("select v.id, c.book_id from verse v join chapter c on c.id = v.chapter_id where c.edition_id = ?", (KJV,)))

    def span(self, first: int, last: int) -> list[int]:
        return [self.at[s] for s in range(self.sequence[first], self.sequence[last] + 1)]

    def verse_start(self, verse: int) -> int:
        return self.sequence[self.verse_words[verse][0]]


def alignment(db: sqlite3.Connection, text: Text) -> dict[int, set[int]]:
    """Each King James word's Hebrew or Greek words, without stray matches.

    word_match often pairs an English pronoun with the verb, noun, or
    preposition that carries it, while the pronoun itself is a separate
    suffix or a verb ending, so a pronoun keeps only its matches to pronoun
    forms.

    A King James verse almost always matches one original verse. Where it
    matches several, an original verse counts only when it lies between the
    verses its neighbours mostly match and takes more than one word, so
    stray matches into distant verses are dropped.
    """
    raw = defaultdict(set)
    for kjv, other in db.execute("select word_id, other_word_id from word_match"):
        if text.edition.get(kjv) != KJV or text.edition.get(other) not in (HEBREW, GREEK):
            continue
        if text.part[kjv] == "Pronoun" and text.part[other] not in PRONOUN_FORMS:
            continue
        raw[kjv].add(other)

    counts = defaultdict(Counter)
    for kjv, others in raw.items():
        for other in others:
            counts[text.verse[kjv]][text.verse[other]] += 1
    order = sorted(counts, key=text.verse_start)
    anchor = {v: text.verse_start(max(c, key=lambda t: (c[t], -text.verse_start(t)))) for v, c in counts.items()}

    allowed = {}
    for i, verse in enumerate(order):
        book = text.book[verse]
        low = anchor[order[i - 1]] if i > 0 and text.book[order[i - 1]] == book else float("-inf")
        high = anchor[order[i + 1]] if i + 1 < len(order) and text.book[order[i + 1]] == book else float("inf")
        targets = counts[verse]
        allowed[verse] = {
            t for t, n in targets.items() if low <= text.verse_start(t) <= high and (n > 1 or len(targets) == 1)
        }

    links = {}
    for kjv, others in raw.items():
        kept = {o for o in others if text.verse[o] in allowed[text.verse[kjv]]}
        if kept:
            links[kjv] = kept
    return links


class Projector:
    def __init__(self, text: Text, links: dict[int, set[int]], mentions: list[tuple]):
        self.text = text
        self.links = links
        self.names = defaultdict(list)
        for entity, kind, first, last in mentions:
            if kind == REFERS_TO:
                self.names[text.verse[first]].append((text.sequence[first], text.sequence[last], entity))
        self.matched_by = defaultdict(set)
        for kjv, others in links.items():
            for other in others:
                self.matched_by[other].add(kjv)
        self.sequences = {e: sorted(self.text.sequence[w] for w in self.matched_by if text.edition[w] == e) for e in (HEBREW, GREEK)}

    def foreign(self, a: int, b: int, inside: set[int]) -> int:
        """How many words between a and b match King James words outside the mention."""
        sequences = self.sequences[self.text.edition[a]]
        low, high = self.text.sequence[a], self.text.sequence[b]
        between = sequences[bisect_left(sequences, low + 1) : bisect_left(sequences, high)]
        return sum(1 for s in between if self.matched_by[self.text.at[s]] - inside)

    def nested(self, entity: int, first: int, last: int) -> set[int]:
        """Words of the mention that belong to a shorter mention of another entity inside it."""
        low, high = self.text.sequence[first], self.text.sequence[last]
        return {
            self.text.at[s]
            for a, b, other in self.names[self.text.verse[first]]
            if other != entity and low <= a and b <= high and (a, b) != (low, high)
            for s in range(a, b + 1)
        }

    def project(self, entity: int, kind: int, first: int, last: int) -> tuple[int, int] | str:
        """The original span of a King James mention, or why it has none.

        A single word matching text outside the mention, such as a
        postpositive δέ or a copula, does not break the span. More than one
        splits it, and the piece covering most of the mention's words wins,
        so a stray match drops out. A tie leaves no clear span.
        """
        text = self.text
        words = text.span(first, last)
        inside = set(words)
        matched = sorted({o for w in words for o in self.links.get(w, ())}, key=text.sequence.get)
        if not matched:
            return "unaligned"
        if kind == REFERS_TO:
            own = inside - self.nested(entity, first, last)
            if not any(w in self.links for w in own):
                return "nested"
            nouns = [w for w in own if text.part[w] in NOUNS]
            if nouns and not any(w in self.links for w in nouns):
                return "unmatched noun"

        clusters = [[matched[0]]]
        for a, b in zip(matched, matched[1:]):
            same_verse = text.verse[a] == text.verse[b]
            if (kind == REFERS_TO and not same_verse) or self.foreign(a, b, inside) > 1:
                clusters.append([b])
            else:
                clusters[-1].append(b)

        def covered(cluster: list[int]) -> int:
            return len({k for o in cluster for k in self.matched_by[o] & inside})

        ranked = sorted(clusters, key=covered, reverse=True)
        if len(ranked) > 1 and covered(ranked[0]) == covered(ranked[1]):
            return "scattered"
        start, end = ranked[0][0], ranked[0][-1]

        if kind != REFERS_TO:
            if first not in self.links:
                start = self.widen(start, -1)
            if last not in self.links:
                end = self.widen(end, 1)
        return start, end

    def widen(self, word: int, step: int) -> int:
        """Grow a passage's end over neighbouring words in its verse that match no King James word."""
        text = self.text
        while True:
            neighbour = text.at.get(text.sequence[word] + step)
            if neighbour is None or text.verse[neighbour] != text.verse[word] or neighbour in self.matched_by:
                return word
            word = neighbour


def chapters(db: sqlite3.Connection, passages: list[str]) -> set[int]:
    found = set()
    for label in passages:
        match = re.fullmatch(r"(.+?) (\d+)(?:-(\d+))?", label.strip())
        if not match:
            raise SystemExit(f"cannot read passage {label!r}: use Book C or Book C-C")
        book, low, high = match.groups()
        rows = db.execute(
            "select c.id from chapter c join book b on b.id = c.book_id where c.edition_id = ? and b.name = ? and c.number between ? and ?",
            (KJV, book, int(low), int(high or low)),
        ).fetchall()
        if not rows:
            raise SystemExit(f"no King James chapters in {label}")
        found |= {r for r, in rows}
    return found


def closure(text: Text, links: dict[int, set[int]], mentions: list[tuple], kjv: set[int]) -> tuple[set[int], set[int]]:
    """The King James and original chapters whose mentions rebuild together.

    Versification differs, as where the King James Malachi 4 is the Hebrew
    Malachi 3, so a chapter is rebuilt with every chapter that shares words
    with it, and with every chapter a mention starting in it runs into.
    """
    edges = defaultdict(set)

    def join(a, b):
        edges[a].add(b)
        edges[b].add(a)

    for k, others in links.items():
        for o in others:
            join(("kjv", text.chapter[k]), ("original", text.chapter[o]))
    for _, _, first, last in mentions:
        if text.chapter[first] != text.chapter[last]:
            for chapter in {text.chapter[w] for w in text.span(first, last)}:
                join(("kjv", text.chapter[first]), ("kjv", chapter))
    seen = {("kjv", c) for c in kjv}
    todo = list(seen)
    while todo:
        for node in edges[todo.pop()] - seen:
            seen.add(node)
            todo.append(node)
    return {c for side, c in seen if side == "kjv"}, {c for side, c in seen if side == "original"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("passage", nargs="*", help="a King James book and chapter or chapter range, such as \"Malachi 3-4\"")
    args = parser.parse_args()
    db = sqlite3.connect(DB)
    db.execute("pragma foreign_keys = on")
    text = Text(db)
    links = alignment(db, text)

    mentions = [m for m in db.execute("select entity_id, mention_kind_id, first_word_id, last_word_id from mention") if text.edition.get(m[2]) == KJV]
    projector = Projector(text, links, mentions)
    if args.passage:
        kjv, original = closure(text, links, mentions, chapters(db, args.passage))
        mentions = [m for m in mentions if text.chapter[m[2]] in kjv]
    else:
        kjv = {c for c, in db.execute("select id from chapter where edition_id = ?", (KJV,))}
        original = {c for c, in db.execute("select id from chapter where edition_id in (?, ?)", (HEBREW, GREEK))}

    rows = set()
    skipped = Counter()
    for entity, kind, first, last in mentions:
        span = projector.project(entity, kind, first, last)
        if isinstance(span, str):
            skipped[span] += 1
            continue
        rows.add((entity, kind, *span))

    with db:
        stale = [m for m, w in db.execute("select id, first_word_id from mention") if text.chapter.get(w) in original]
        db.executemany("delete from mention where id = ?", [(m,) for m in stale])
        db.executemany("insert into mention (entity_id, mention_kind_id, first_word_id, last_word_id) values (?, ?, ?, ?)", sorted(rows))
        problems = db.execute("pragma foreign_key_check").fetchall()
        if problems:
            raise SystemExit(f"foreign key problems: {problems[:5]}")

    made = Counter(text.edition[r[2]] for r in rows)
    print(f"{len(mentions)} King James mentions in {len(kjv)} chapters")
    print(f"removed {len(stale)}, added {made[HEBREW]} Hebrew and {made[GREEK]} Greek mentions")
    print(
        f"skipped {skipped['unaligned']} with no matched words, {skipped['nested']} matched only through a mention inside them,"
        f" {skipped['unmatched noun']} whose nouns have no match, and {skipped['scattered']} matched to scattered words"
    )


if __name__ == "__main__":
    main()
