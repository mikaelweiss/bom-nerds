"""Rebuild every literary structure from the staged decisions, add named verse ranges and passage links, and project Bible structures between the KJV and the Hebrew and Greek.

    python scripts/apply_structures_and_links.py scripture.db decisions/structures-links decisions/structures-links-fixes

The fixes directory revises the first: it sets which parts pair, drops or replaces structures, adds structures, supplies projections word_match cannot make, and relabels Fulfills links.
Structures are deleted and rebuilt in a fixed order, and every link is checked against the database first, so a run can be repeated safely.
"""

import json
import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from project_to_originals import KJV, Projector  # noqa: E402

RANGE_FILES = ("verse_ranges",)
LINK_FILES = ("links_quotes_events", "links_fulfills_alludes")
BIBLE = (1, 2, 3)


def read_decisions(directory, name, report):
    path = os.path.join(directory, name + ".jsonl")
    if not os.path.exists(path):
        report[f"{name}: file missing"] += 1
        return
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            report[f"{name}: unreadable line"] += 1


class Words:
    def __init__(self, db):
        self.db = db
        self.cache = {}

    def get(self, word):
        """(sequence, edition) of a word, or None when it does not exist."""
        if word not in self.cache:
            self.cache[word] = self.db.execute(
                "select w.sequence, c.edition_id from word w join verse v on v.id = w.verse_id "
                "join chapter c on c.id = v.chapter_id where w.id = ?",
                (word,),
            ).fetchone()
        return self.cache[word]

    def span(self, first, last):
        """(first sequence, last sequence) of a passage that runs forward within one edition, or None."""
        a, b = self.get(first), self.get(last)
        if a is None or b is None or a[1] != b[1] or a[0] > b[0]:
            return None
        return a[0], b[0]


def overlaps(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


def span_key(record):
    return record["kind"], record["first_word_id"], record["last_word_id"]


def pairs_of(record):
    """The record's pairs of part keys, from "pairs" or else from each part's "pairs_with"."""
    if "pairs" in record:
        return [tuple(pair) for pair in record["pairs"]]
    keys = {part["key"] for part in record["parts"]}
    found = []
    for part in record["parts"]:
        partner = part.get("pairs_with")
        if partner in keys and partner != part["key"] and {part["key"], partner} not in found:
            found.append({part["key"], partner})
    return [tuple(sorted(pair)) for pair in found]


def reviewed_restoration(sources, report):
    review = {(d["first_word_id"], d["last_word_id"]): d for d in read_decisions(sources, "restoration_auto_review", report)}
    for record in read_decisions(sources, "restoration_structures", report):
        decision = review.get((record["first_word_id"], record["last_word_id"]))
        if record["kind"] != "Parallelism" or decision is None or decision.get("decision") == "keep":
            yield record
        elif decision.get("decision") == "drop":
            report["restoration_auto_review: dropped"] += 1
        elif decision.get("decision") == "fix" and decision.get("record"):
            report["restoration_auto_review: replaced"] += 1
            yield decision["record"]
        else:
            report["restoration_auto_review: unreadable decision, kept as is"] += 1
            yield record


def revise(records, overrides, words, report, label):
    """Apply override lines to records. A line matches the record with its span, or when no record has that span, the one unmatched record of its kind it overlaps."""
    by_key = {span_key(record): i for i, record in enumerate(records)}
    matched = {}
    loose = []
    for line in overrides:
        i = by_key.get(span_key(line))
        if i is None or i in matched:
            loose.append(line)
        else:
            matched[i] = line
    for line in loose:
        line_span = words.span(line["first_word_id"], line["last_word_id"])
        candidates = [
            i
            for i, record in enumerate(records)
            if i not in matched
            and record["kind"] == line["kind"]
            and line_span
            and overlaps(line_span, words.span(record["first_word_id"], record["last_word_id"]) or (0, -1))
        ]
        if len(candidates) == 1:
            matched[candidates[0]] = line
            report[f"{label}: matched by overlap"] += 1
        else:
            report[f"{label}: matched no record"] += 1

    revised = []
    for i, record in enumerate(records):
        line = matched.get(i)
        origins = record.get("origins", []) + [span_key(record)]
        if line is None:
            revised.append({**record, "pairs": pairs_of(record), "origins": origins})
        elif line.get("decision") == "drop" or line.get("pairs") == []:
            report[f"{label}: dropped"] += 1
        else:
            replacement = line.get("record")
            report[f"{label}: {'replaced' if replacement else 'pairs set'}"] += 1
            pairs = line["pairs"] if "pairs" in line else pairs_of(replacement)
            revised.append({**(replacement or record), "pairs": [tuple(p) for p in pairs], "origins": origins})
    return revised


def staged_structures(sources, fixes, words, report):
    def read(directory, name):
        return list(read_decisions(directory, name, report))

    groups = [
        (read(sources, "hebrew_poetry"), "pairs_hebrew_poetry"),
        (read(sources, "hebrew_prophets"), "review_hebrew_prophets"),
        (read(sources, "bible_structures") + read(sources, "nt_parallelism_sweep"), "pairs_greek"),
        (list(reviewed_restoration(sources, report)) + read(sources, "restoration_sweep2"), "pairs_restoration"),
    ]
    records = []
    for group, fix in groups:
        records += revise(group, read(fixes, fix), words, report, fix)
    records = revise(records, read(fixes, "chiasms"), words, report, "chiasms")
    for name in ("nt_sweep3", "restoration_sweep3"):
        records += [{**r, "pairs": pairs_of(r)} for r in read(fixes, name)]
    return records


def shape_problem(words, span, parts):
    """Why a structure's parts do not nest in reading order, or None when they do."""
    if span is None:
        return "bad span"
    spans = {}
    last_end = {}
    for part in parts:
        part_span = words.span(part["first_word_id"], part["last_word_id"])
        if part_span is None:
            return "bad part span"
        parent = part.get("parent")
        outer = span if parent is None else spans.get(parent)
        if outer is None:
            return "unknown parent"
        if not (outer[0] <= part_span[0] and part_span[1] <= outer[1]):
            return "part outside its parent"
        if parent in last_end and part_span[0] <= last_end[parent]:
            return "siblings overlap or out of order"
        last_end[parent] = part_span[1]
        spans[part["key"]] = part_span
    return None


def record_problem(words, kind, record):
    parts = record.get("parts") or []
    if kind is None:
        return "unknown kind"
    if not parts:
        return "no parts"
    return shape_problem(words, words.span(record["first_word_id"], record["last_word_id"]), parts)


def insert_structure(db, kind, record, report, label):
    first, last = record["first_word_id"], record["last_word_id"]
    if db.execute(
        "select 1 from structure where structure_kind_id = ? and first_word_id = ? and last_word_id = ?",
        (kind, first, last),
    ).fetchone():
        report[f"{label}: duplicate skipped"] += 1
        return False
    db.execute("savepoint structure")
    try:
        structure = db.execute(
            "insert into structure (structure_kind_id, first_word_id, last_word_id) values (?, ?, ?)", (kind, first, last)
        ).lastrowid
        ids = {}
        for position, part in enumerate(record["parts"], 1):
            ids[part["key"]] = db.execute(
                "insert into structure_part (structure_id, parent_id, position, first_word_id, last_word_id) "
                "values (?, ?, ?, ?, ?)",
                (structure, ids.get(part.get("parent")), position, part["first_word_id"], part["last_word_id"]),
            ).lastrowid
        for key, other in record["pairs"]:
            if key not in ids or other not in ids or key == other:
                report[f"{label}: pair naming a missing part skipped"] += 1
                continue
            db.execute(
                "insert or ignore into structure_part_pair (part_id, other_part_id) values (?, ?)",
                (min(ids[key], ids[other]), max(ids[key], ids[other])),
            )
    except sqlite3.DatabaseError:
        db.execute("rollback to structure")
        db.execute("release structure")
        report[f"{label}: rejected by the database"] += 1
        return False
    db.execute("release structure")
    report[f"{label}: added"] += 1
    return True


def project_structure(projector, words, record):
    """The record moved to the other Bible edition and None, or None and the reason it cannot move."""
    move = projector.project if projector.edition[record["first_word_id"]] == KJV else projector.project_back
    mapped = {}
    for key, item in [(None, record)] + [(p["key"], p) for p in record["parts"]]:
        span = move(item["first_word_id"], item["last_word_id"])
        if span is None:
            return None, "part did not map"
        mapped[key] = span
    targets = {projector.edition[w] for span in mapped.values() for w in span}
    if len(targets) != 1:
        return None, "mapped into more than one edition"
    parts = [
        {**part, "first_word_id": mapped[part["key"]][0], "last_word_id": mapped[part["key"]][1]}
        for part in record["parts"]
    ]
    top = [mapped[None]] + [(p["first_word_id"], p["last_word_id"]) for p in parts if p.get("parent") is None]
    first = min((s[0] for s in top), key=projector.seq.get)
    last = max((s[1] for s in top), key=projector.seq.get)
    problem = shape_problem(words, words.span(first, last), parts)
    if problem:
        return None, problem
    return {"kind": record["kind"], "first_word_id": first, "last_word_id": last, "parts": parts, "pairs": record["pairs"]}, None


def manual_projection(manual, words, kind, record):
    """The hand-made projection of a record, carrying the record's pairs, or None."""
    for origin in record.get("origins", []) + [span_key(record)]:
        target = manual.get(origin)
        if target and not record_problem(words, kind, target):
            return {**target, "pairs": record["pairs"]}
    return None


def apply_structures(db, sources, fixes, projector, words, report):
    kinds = dict(db.execute("select name, id from structure_kind"))
    manual = {span_key(line["source"]): line["record"] for line in read_decisions(fixes, "manual_projections", report)}
    db.execute("delete from structure")
    valid = []
    for record in staged_structures(sources, fixes, words, report):
        kind = kinds.get(record.get("kind"))
        problem = record_problem(words, kind, record)
        if problem:
            report[f"structures: rejected ({problem})"] += 1
            continue
        insert_structure(db, kind, record, report, "structures")
        valid.append((kind, record))

    for kind, record in valid:
        if projector.edition.get(record["first_word_id"]) not in BIBLE:
            continue
        projected, problem = project_structure(projector, words, record)
        label = f"projection {record['kind']}"
        if projected is None:
            projected = manual_projection(manual, words, kind, record)
            label = f"manual projection {record['kind']}"
        if projected is None:
            report[f"projection {record['kind']}: skipped ({problem})"] += 1
        else:
            insert_structure(db, kind, projected, report, label)


def apply_ranges(db, directory, words, report):
    for name in RANGE_FILES:
        for record in read_decisions(directory, name, report):
            first, last = record["first_word_id"], record["last_word_id"]
            existing = db.execute(
                "select first_word_id, last_word_id from verse_range where name = ?", (record["name"],)
            ).fetchone()
            if existing == (first, last):
                report["verse ranges: already there"] += 1
            elif existing or words.span(first, last) is None:
                report["verse ranges: rejected"] += 1
            elif db.execute(
                "select 1 from verse_range where first_word_id = ? and last_word_id = ?", (first, last)
            ).fetchone():
                report["verse ranges: span already named, skipped"] += 1
            else:
                db.execute(
                    "insert into verse_range (name, first_word_id, last_word_id) values (?, ?, ?)",
                    (record["name"], first, last),
                )
                report["verse ranges: added"] += 1


def joins(a, b):
    """Whether two links join overlapping spans of the same two passages, in either direction."""
    return (overlaps(a[0], b[0]) and overlaps(a[1], b[1])) or (overlaps(a[0], b[1]) and overlaps(a[1], b[0]))


def naming_verse(db):
    """Joseph Smith-History 1:40, which names the passages Moroni quoted without quoting them."""
    return db.execute(
        "select min(w.sequence), max(w.sequence) from word w join verse v on v.id = w.verse_id "
        "join chapter c on c.id = v.chapter_id join book b on b.id = c.book_id "
        "where b.name = 'Joseph Smith' || char(8212) || 'History' and c.number = 1 and v.number = 40"
    ).fetchone()


def link_ends(record):
    return (
        record["from_first_word_id"],
        record["from_last_word_id"],
        record["to_first_word_id"],
        record["to_last_word_id"],
    )


def relabel_fulfills(db, fixes, report):
    """Move reviewed Fulfills links to the kind the review chose, and return that choice by link ends."""
    kinds = dict(db.execute("select name, id from link_kind"))
    fulfills = kinds["Fulfills"]
    relabels = {}
    for line in read_decisions(fixes, "fulfills_review", report):
        kind = kinds.get(line.get("decision"))
        if kind is None:
            report["fulfills_review: unknown decision"] += 1
            continue
        ends = link_ends(line)
        relabels[ends] = line["decision"]
        if kind == fulfills:
            continue
        link = "from passage_link where link_kind_id = ? and from_first_word_id = ? and from_last_word_id = ? and to_first_word_id = ? and to_last_word_id = ?"
        if not db.execute("select 1 " + link, (fulfills, *ends)).fetchone():
            report[f"fulfills_review: no Fulfills link to relabel to {line['decision']}"] += 1
        elif db.execute("select 1 " + link, (kind, *ends)).fetchone():
            report[f"fulfills_review: {line['decision']} already there, relabel skipped"] += 1
        else:
            db.execute("update passage_link set link_kind_id = ? where id = (select id " + link + ")", (kind, fulfills, *ends))
            report[f"fulfills_review: relabeled to {line['decision']}"] += 1
    return relabels


def apply_links(db, directory, words, relabels, report):
    kinds = {name: (id, two_way) for id, name, two_way in db.execute("select id, name, two_way from link_kind")}
    named = {id: name for name, (id, _) in kinds.items()}
    reviewed = set()
    spans_of = {}

    def passages(row):
        return words.span(row[1], row[2]), words.span(row[3], row[4])

    staged = []
    for name in LINK_FILES:
        for record in read_decisions(directory, name, report):
            if record.get("kind") == "Fulfills" and link_ends(record) in relabels:
                record = {**record, "kind": relabels[link_ends(record)]}
                reviewed_link = True
            else:
                reviewed_link = False
            kind = kinds.get(record.get("kind"))
            row = (
                kind and kind[0],
                record["from_first_word_id"],
                record["from_last_word_id"],
                record["to_first_word_id"],
                record["to_last_word_id"],
            )
            spans = passages(row)
            if kind is None or None in spans:
                report["links: rejected"] += 1
                continue
            if kind[1] and spans[0] > spans[1]:
                row, spans = (row[0], row[3], row[4], row[1], row[2]), spans[::-1]
            spans_of[row] = spans
            staged.append(row)
            if reviewed_link:
                reviewed.add(row)

    parallel, quotes = kinds["Parallel"][0], kinds["Quotes"][0]
    verse = naming_verse(db)
    kept = []
    for row in staged:
        from_span = spans_of[row][0]
        if row[0] == quotes and verse[0] <= from_span[0] and from_span[1] <= verse[1]:
            report["links: Quotes from Joseph Smith-History 1:40 dropped"] += 1
        else:
            kept.append(row)
    staged = kept

    existing = db.execute(
        "select link_kind_id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id "
        "from passage_link where link_kind_id in (?, ?)",
        (parallel, quotes),
    ).fetchall()
    by_kind = {}
    for row in staged + existing:
        spans_of.setdefault(row, passages(row))
        by_kind.setdefault(row[0], []).append(row)

    blocker = {kinds["Same event"][0]: parallel, kinds["Alludes to"][0]: quotes}
    for row in staged:
        spans = spans_of[row]
        if row not in reviewed and row[0] in blocker and any(joins(spans, spans_of[other]) for other in by_kind.get(blocker[row[0]], ())):
            report[f"links: {named[row[0]]} dropped for a matching {named[blocker[row[0]]]}"] += 1
            continue
        try:
            added = db.execute(
                "insert or ignore into passage_link (link_kind_id, from_first_word_id, from_last_word_id, "
                "to_first_word_id, to_last_word_id) values (?, ?, ?, ?, ?)",
                row,
            ).rowcount
        except sqlite3.DatabaseError:
            report["links: rejected by the database"] += 1
            continue
        report[f"links {named[row[0]]}: {'added' if added else 'already there'}"] += 1


def main(path, sources, fixes):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("pragma foreign_keys = on")
    projector = Projector(db)
    words = Words(db)
    report = Counter()
    db.execute("begin")
    apply_structures(db, sources, fixes, projector, words, report)
    apply_ranges(db, sources, words, report)
    relabels = relabel_fulfills(db, fixes, report)
    apply_links(db, sources, words, relabels, report)
    problems = db.execute("pragma foreign_key_check").fetchall()
    if problems:
        db.execute("rollback")
        sys.exit(f"foreign key problems, nothing applied: {problems[:10]}")
    db.execute("commit")
    for key, n in sorted(report.items()):
        print(f"{key}: {n}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
