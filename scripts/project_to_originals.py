"""Copy KJV speeches, journeys, relationship evidence, and dates onto the Hebrew and Greek through word_match.

    python scripts/project_to_originals.py scripture.db
    python scripts/project_to_originals.py scripture.db --sync [--dry-run]

--sync brings existing copies in line with their KJV sources and adds missing copies, so it is safe to repeat.
A copy is the row at the projected word range: the speech there, or the journey or date there that pairs best
with its source. --dry-run prints the changes without writing them.
"""

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
    db.execute("pragma busy_timeout = 60000")
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


def by_edition(projector, rows, first):
    kjv, originals = [], defaultdict(list)
    for row in rows:
        edition = projector.edition.get(row[first])
        if edition == KJV:
            kjv.append(row)
        elif edition in ORIGINALS:
            originals[row[first], row[first + 1]].append(row)
    return kjv, originals


def pair(sources, copies, score):
    """Pair each source with at most one copy, best score first."""
    options = sorted(
        ((s, i, j) for i, a in enumerate(sources) for j, b in enumerate(copies) if (s := score(a, b)) is not None),
        key=lambda o: (-o[0], o[1], o[2]),
    )
    pairs, used_sources, used_copies = [], set(), set()
    for _, i, j in options:
        if i not in used_sources and j not in used_copies:
            used_sources.add(i)
            used_copies.add(j)
            pairs.append((sources[i], copies[j]))
    unpaired = [s for i, s in enumerate(sources) if i not in used_sources]
    return pairs, unpaired, len(copies) - len(used_copies)


def sync_speeches(db, projector, report):
    speeches = db.execute("select id, through_id, speech_mode_id, first_word_id, last_word_id from speech").fetchall()
    members = {table: defaultdict(set) for table in ("speech_speaker", "speech_listener")}
    for table, of in members.items():
        for speech, entity in db.execute(f"select speech_id, entity_id from {table}"):
            of[speech].add(entity)
    kjv, originals = by_edition(projector, speeches, 3)
    sources = defaultdict(list)
    for row in kjv:
        span = projector.project(row[3], row[4])
        if span is None:
            report["speech unmatched"] += 1
        else:
            sources[span].append(row)

    removals, updates, inserts, additions = [], [], [], []
    for span, rows in sources.items():
        if len({row[1:3] for row in rows}) > 1:
            report["speech sources disagree on messenger or mode"] += 1
        through_mode = rows[0][1:3]
        copy = originals.get(span, [None])[0]
        if copy is None:
            inserts.append(
                ("insert into speech (through_id, speech_mode_id, first_word_id, last_word_id) values (?, ?, ?, ?)",
                 (*through_mode, *span))
            )
            report["speech added"] += 1
        elif copy[1:3] != through_mode:
            updates.append(("update speech set through_id = ?, speech_mode_id = ? where id = ?", (*through_mode, copy[0])))
            report["speech messenger or mode updated"] += 1
        for table, of in members.items():
            want = set().union(*(of[row[0]] for row in rows))
            have = of[copy[0]] if copy else set()
            removals += [(f"delete from {table} where speech_id = ? and entity_id = ?", (copy[0], e)) for e in have - want]
            additions += [
                (f"insert into {table} select id, ? from speech where first_word_id = ? and last_word_id = ?", (e, *span))
                for e in want - have
            ]
            report[f"{table} removed"] += len(have - want)
            report[f"{table} added"] += len(want - have)
            if copy and want - have and not have:
                report[f"{table} given to copies that had none"] += 1
    report["speech copies without a source"] += sum(1 for span in originals if span not in sources)
    return removals + updates + inserts + additions


JOURNEY = "traveler_id, from_id, to_id, days"
DATE = (
    "counting_system_id, from_year, from_month, from_day, to_year, to_month, to_day, "
    "evidence_first_word_id, evidence_last_word_id"
)


def journey_score(source, copy):
    same = [a == b for a, b in zip(source, copy)]
    return sum(same) if same[0] + same[1] + same[2] >= 2 else None


def date_score(source, copy):
    return sum(a == b for a, b in zip(source, copy)) if (source[1], source[4]) == (copy[1], copy[4]) else None


def sync_rows(db, projector, report, table, fields, score, evidence=False):
    """Pair KJV rows with copies at the same projected range, update paired copies, and insert unpaired sources."""
    width = len(fields.split(", "))
    rows = db.execute(f"select id, {fields}, first_word_id, last_word_id from {table} where first_word_id is not null")
    kjv, originals = by_edition(projector, rows.fetchall(), width + 1)
    sources = defaultdict(list)
    for row in kjv:
        values, (first, last) = row[1 : width + 1], row[width + 1 :]
        span = projector.project(first, last)
        if evidence and values[-2] is not None:
            projected = projector.project(*values[-2:])
            values = None if projected is None else (*values[:-2], *projected)
        if span is None or values is None:
            report[f"{table} unmatched"] += 1
        elif values in sources[span]:
            report[f"{table} sources repeated"] += 1
        else:
            sources[span].append(values)

    ops = []
    setter = f"update {table} set ({fields}) = ({', '.join('?' * width)}) where id = ?"
    inserter = f"insert into {table} ({fields}, first_word_id, last_word_id) values ({', '.join('?' * (width + 2))})"
    for span, wanted in sources.items():
        copies = [(c[1 : width + 1], c[0]) for c in originals.get(span, ())]
        pairs, unpaired, spare = pair(wanted, copies, lambda source, copy: score(source, copy[0]))
        report[f"{table} copies without a source"] += spare
        for values, (current, copy) in pairs:
            if values != current:
                ops.append((setter, (*values, copy)))
                report[f"{table} updated"] += 1
                for field, a, b in zip(fields.split(", "), values, current):
                    report[f"{table} {field} changed"] += a != b
        ops += [(inserter, (*values, *span)) for values in unpaired]
        report[f"{table} added"] += len(unpaired)
    report[f"{table} copies without a source"] += sum(len(c) for span, c in originals.items() if span not in sources)
    return ops


def sync_evidence(db, projector, report):
    rows = db.execute("select relationship_id, first_word_id, last_word_id from relationship_evidence").fetchall()
    kjv, originals = by_edition(projector, rows, 1)
    have = {row for copies in originals.values() for row in copies}
    wanted = set()
    for relationship, first, last in kjv:
        span = projector.project(first, last)
        if span is None:
            report["relationship evidence unmatched"] += 1
        else:
            wanted.add((relationship, *span))
    report["relationship evidence added"] += len(wanted - have)
    report["relationship evidence copies without a source"] += len(have - wanted)
    return [("insert or ignore into relationship_evidence values (?, ?, ?)", row) for row in sorted(wanted - have)]


def sync(path, dry_run):
    db = sqlite3.connect(path)
    db.execute("pragma foreign_keys = on")
    db.execute("pragma busy_timeout = 60000")
    projector = Projector(db)
    report = Counter()
    steps = (
        lambda: sync_speeches(db, projector, report),
        lambda: sync_rows(db, projector, report, "journey", JOURNEY, journey_score),
        lambda: sync_evidence(db, projector, report),
        lambda: sync_rows(db, projector, report, "date", DATE, date_score, evidence=True),
    )
    for step in steps:
        ops = step()
        if not dry_run:
            with db:
                for sql, params in ops:
                    db.execute(sql, params)
    print("dry run, nothing written" if dry_run else "synced")
    for key, n in sorted(report.items()):
        if n:
            print(f"{key}: {n}")


if __name__ == "__main__":
    if "--sync" in sys.argv[2:]:
        sync(sys.argv[1], "--dry-run" in sys.argv[2:])
    else:
        main(sys.argv[1])
