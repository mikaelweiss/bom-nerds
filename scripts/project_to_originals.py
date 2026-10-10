"""Copy KJV speeches, journeys, relationship evidence, and dates onto the Hebrew and Greek through word_match."""

import sqlite3
import sys
from collections import Counter, defaultdict

KJV = 1
ORIGINALS = (2, 3)


class Projector:
    def __init__(self, db):
        self.kjv_by_seq = {}
        self.original_by_seq = {}
        self.verse = {}
        self.seq = {}
        self.edition = {}
        for word, seq, verse, ed in db.execute(
            "select w.id, w.sequence, w.verse_id, c.edition_id from word w join verse v on v.id = w.verse_id "
            "join chapter c on c.id = v.chapter_id where c.edition_id in (1, 2, 3)"
        ):
            self.seq[word] = seq
            self.edition[word] = ed
            self.verse[word] = verse
            if ed == KJV:
                self.kjv_by_seq[seq] = word
            else:
                self.original_by_seq[seq] = word

        self.matches = defaultdict(list)
        self.back_matches = defaultdict(list)
        for a, b in db.execute("select word_id, other_word_id from word_match"):
            for english, other in ((a, b), (b, a)):
                if self.edition.get(english) == KJV and self.edition.get(other) in ORIGINALS:
                    self.matches[english].append(other)
                    self.back_matches[other].append(english)

        self.allowed = self._allowed_verses(self.matches)
        self.back_allowed = self._allowed_verses(self.back_matches)

    def _allowed_verses(self, matches):
        per_verse = defaultdict(Counter)
        for word, others in matches.items():
            for other in others:
                per_verse[self.verse[word]][self.verse[other]] += 1
        allowed = {}
        for verse, counts in per_verse.items():
            total = sum(counts.values())
            allowed[verse] = {v for v, n in counts.items() if n >= max(1, 0.2 * total)}
        return allowed

    def _span(self, first, last, by_seq, matches, allowed):
        found = []
        for seq in range(self.seq[first], self.seq[last] + 1):
            word = by_seq.get(seq)
            if word is None:
                continue
            verses = allowed.get(self.verse[word], ())
            found.extend(o for o in matches.get(word, ()) if self.verse[o] in verses)
        if not found:
            return None
        return min(found, key=self.seq.get), max(found, key=self.seq.get)

    def project(self, first, last):
        """The original-language span matching a KJV span, or None when nothing in it is matched."""
        return self._span(first, last, self.kjv_by_seq, self.matches, self.allowed)

    def project_back(self, first, last):
        """The KJV span matching a Hebrew or Greek span, or None when nothing in it is matched."""
        return self._span(first, last, self.original_by_seq, self.back_matches, self.back_allowed)


def kjv_rows(db, query):
    return db.execute(
        query + " join word a on a.id = x.first_word_id join verse v on v.id = a.verse_id "
        "join chapter c on c.id = v.chapter_id where c.edition_id = 1"
    ).fetchall()


def main(path):
    db = sqlite3.connect(path)
    db.execute("pragma foreign_keys = on")
    projector = Projector(db)
    report = Counter()

    for speech, through, mode, first, last in kjv_rows(
        db, "select x.id, x.through_id, x.speech_mode_id, x.first_word_id, x.last_word_id from speech x"
    ):
        span = projector.project(first, last)
        if span is None:
            report["speech unmatched"] += 1
            continue
        if db.execute("select 1 from speech where first_word_id = ? and last_word_id = ?", span).fetchone():
            report["speech already there"] += 1
            continue
        new = db.execute(
            "insert into speech (through_id, speech_mode_id, first_word_id, last_word_id) values (?, ?, ?, ?)",
            (through, mode, *span),
        ).lastrowid
        db.execute("insert into speech_speaker select ?, entity_id from speech_speaker where speech_id = ?", (new, speech))
        db.execute("insert into speech_listener select ?, entity_id from speech_listener where speech_id = ?", (new, speech))
        report["speech added"] += 1

    for traveler, origin, destination, days, first, last in kjv_rows(
        db, "select x.traveler_id, x.from_id, x.to_id, x.days, x.first_word_id, x.last_word_id from journey x"
    ):
        span = projector.project(first, last)
        if span is None:
            report["journey unmatched"] += 1
            continue
        if db.execute(
            "select 1 from journey where traveler_id = ? and to_id = ? and first_word_id = ? and last_word_id = ?",
            (traveler, destination, *span),
        ).fetchone():
            report["journey already there"] += 1
            continue
        db.execute(
            "insert into journey (traveler_id, from_id, to_id, days, first_word_id, last_word_id) values (?, ?, ?, ?, ?, ?)",
            (traveler, origin, destination, days, *span),
        )
        report["journey added"] += 1

    for relationship, first, last in kjv_rows(
        db, "select x.relationship_id, x.first_word_id, x.last_word_id from relationship_evidence x"
    ):
        span = projector.project(first, last)
        if span is None:
            report["relationship evidence unmatched"] += 1
            continue
        changed = db.execute(
            "insert or ignore into relationship_evidence (relationship_id, first_word_id, last_word_id) values (?, ?, ?)",
            (relationship, *span),
        ).rowcount
        report["relationship evidence added" if changed else "relationship evidence already there"] += 1

    for row in kjv_rows(
        db,
        "select x.counting_system_id, x.from_year, x.from_month, x.from_day, x.to_year, x.to_month, x.to_day, "
        "x.first_word_id, x.last_word_id, x.evidence_first_word_id, x.evidence_last_word_id from date x",
    ):
        *when, first, last, evidence_first, evidence_last = row
        span = projector.project(first, last)
        evidence = projector.project(evidence_first, evidence_last) if evidence_first else (None, None)
        if span is None or evidence is None:
            report["date unmatched"] += 1
            continue
        if db.execute(
            "select 1 from date where first_word_id = ? and last_word_id = ? and from_year = ? and to_year = ?",
            (*span, when[1], when[4]),
        ).fetchone():
            report["date already there"] += 1
            continue
        db.execute(
            "insert into date (counting_system_id, from_year, from_month, from_day, to_year, to_month, to_day, "
            "first_word_id, last_word_id, evidence_first_word_id, evidence_last_word_id) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*when, *span, *evidence),
        )
        report["date added"] += 1

    db.commit()
    for key, n in sorted(report.items()):
        print(f"{key}: {n}")


if __name__ == "__main__":
    main(sys.argv[1])
