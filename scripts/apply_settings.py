"""Rebuild the setting table, where each passage takes place, from the settings pass decisions, and project KJV settings onto the Hebrew and Greek.

    python scripts/apply_settings.py scripture.db decisions/settings
    python scripts/apply_settings.py --check scripture.db decisions/settings/<slice>.jsonl

Every .jsonl file in the directory is read except places.jsonl, the places add_restoration_places.py adds. With --check, one file or directory is only validated: each problem line is printed and nothing is written. Each line names its chapter and is one of three kinds:

    {"chapter_id": 1304, "verses": "19-39", "place_id": 10454, "first_word_id": 914103, "last_word_id": 915097}
    {"chapter_id": 501, "none": "poetry"}
    {"chapter_id": 1432, "verses": "1-39", "missing": "Hiram", "type": "City", "first_word_id": 1060193, "last_word_id": 1061262}

A setting must name a place and run forward through numbered verses of its chapter, its first word in the first verse of "verses" and its last word in the last.
Settings of one place may not overlap within a chapter. None lines are only counted. A missing line becomes a setting once a place of that name
exists, matched on its name or another name and, when several places share it, on its type. Names still missing are listed so the places can be added.
The table is emptied and rebuilt in one transaction, so a run can be repeated safely.
"""

import json
import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from project_to_originals import KJV, Projector  # noqa: E402

EDITIONS = (1, 4, 5, 6)


def read_all(source, report, rejects):
    """Each (file:line, record) of a .jsonl file or of every .jsonl file in a directory."""
    if os.path.isdir(source):
        paths = [os.path.join(source, name) for name in sorted(os.listdir(source)) if name.endswith(".jsonl") and name != "places.jsonl"]
    else:
        paths = [source]
    for path in paths:
        name = os.path.basename(path)
        for number, line in enumerate(open(path, encoding="utf-8"), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                record = None
            if isinstance(record, dict):
                yield f"{name}:{number}", record
            else:
                report[f"{name}: unreadable line"] += 1
                rejects.append((f"{name}:{number}", "unreadable line"))


class Words:
    def __init__(self, db):
        self.db = db
        self.cache = {}

    def get(self, word):
        """(sequence, chapter, verse number, verse id) of a word, or None when it does not exist."""
        if word not in self.cache:
            self.cache[word] = self.db.execute(
                "select w.sequence, v.chapter_id, v.number, v.id from word w join verse v on v.id = w.verse_id where w.id = ?",
                (word,),
            ).fetchone()
        return self.cache[word]

    def verse_ends(self, verse):
        return self.db.execute(
            "select (select id from word where verse_id = ?1 order by sequence limit 1), "
            "(select id from word where verse_id = ?1 order by sequence desc limit 1)",
            (verse,),
        ).fetchone()


def verse_numbers(label):
    """(first, last) verse numbers of a label like "19-39" or "7", or None."""
    try:
        parts = [int(p) for p in str(label).split("-")]
    except ValueError:
        return None
    if len(parts) == 1:
        parts *= 2
    if len(parts) != 2 or parts[0] > parts[1]:
        return None
    return tuple(parts)


def span_problem(words, chapters, record):
    """Why a line's chapter, verses, and words do not fit together, or None when they do."""
    chapter = record.get("chapter_id")
    if chapters.get(chapter) not in EDITIONS:
        return "unknown chapter"
    verses = verse_numbers(record.get("verses"))
    if verses is None:
        return "bad verses"
    first, last = words.get(record.get("first_word_id")), words.get(record.get("last_word_id"))
    if first is None or last is None:
        return "unknown word"
    if first[1] != chapter or last[1] != chapter:
        return "word outside the chapter"
    if first[2] is None or last[2] is None:
        return "word in the heading"
    if first[0] > last[0]:
        return "runs backward"
    if (first[2], last[2]) != verses:
        return "words do not match verses"
    return None


def named_place(places_named, name, type):
    """The id of the one place a missing line's name and type pick out, or None."""
    name = name.strip()
    found = places_named.get(name.lower()) or places_named.get(name.split(" (")[0].lower(), set())
    if len(found) > 1:
        found = {place for place in found if place[1] == type}
    return next(iter(found))[0] if len(found) == 1 else None


def stage(db, source, words, report, rejects):
    chapters = dict(db.execute(f"select id, edition_id from chapter where edition_id in {EDITIONS}"))
    places_named = {}
    places = set()
    for id, type, name in db.execute(
        "select x.id, t.name, x.name from entity x join entity_type t on t.id = x.entity_type_id "
        "left join entity_type p on p.id = t.parent_id where 'Place' in (t.name, p.name) "
        "union select x.id, t.name, n.name from entity_name n join entity x on x.id = n.entity_id "
        "join entity_type t on t.id = x.entity_type_id left join entity_type p on p.id = t.parent_id where 'Place' in (t.name, p.name)"
    ):
        places.add(id)
        places_named.setdefault(name.lower(), set()).add((id, type))

    staged = {}
    none = set()
    missing = Counter()
    missing_chapters = set()
    def reject(where, label, problem):
        report[f"{label}: rejected ({problem})"] += 1
        rejects.append((where, problem))

    for where, record in read_all(source, report, rejects):
        chapter = record.get("chapter_id")
        if "none" in record:
            if chapters.get(chapter) in EDITIONS:
                none.add(chapter)
                report["none"] += 1
            else:
                reject(where, "none", "unknown chapter")
            continue
        if "missing" in record:
            problem = span_problem(words, chapters, record)
            if problem:
                reject(where, "missing", problem)
                continue
            name = str(record["missing"]).strip()
            place = named_place(places_named, name, record.get("type"))
            if place is None:
                missing[name] += 1
                missing_chapters.add(chapter)
                report["missing"] += 1
                continue
            report["missing: now a place"] += 1
            record = {**record, "place_id": place}
        problem = span_problem(words, chapters, record)
        if problem is None and record.get("place_id") not in places:
            problem = "not a place"
        if problem:
            reject(where, "settings", problem)
            continue
        key = (record["place_id"], record["first_word_id"], record["last_word_id"])
        if key in staged:
            report["settings: duplicate skipped"] += 1
            continue
        staged[key] = (chapter, where)

    kept = []
    by_place = {}
    for key, (chapter, where) in sorted(staged.items(), key=lambda item: words.get(item[0][1])[0]):
        place, first, last = key
        span = (words.get(first)[0], words.get(last)[0])
        if any(span[0] <= other[1] and other[0] <= span[1] for other in by_place.get((place, chapter), ())):
            reject(where, "settings", "overlaps the same place")
            continue
        by_place.setdefault((place, chapter), []).append(span)
        kept.append((key, chapter))

    with_settings = {chapter for _, chapter in kept}
    report["chapters marked none and also given settings"] += len(none & with_settings)
    report["chapters decided"] = len(none | with_settings | missing_chapters)
    report["chapters in all"] = len(chapters)
    return kept, missing


def verse_aligned(words, first, last):
    a, b = words.get(first), words.get(last)
    return words.verse_ends(a[3])[0] == first and words.verse_ends(b[3])[1] == last


def projections(projector, words, kept, report):
    """The Hebrew and Greek settings matching the KJV ones, each widened to whole verses when its KJV setting covers whole verses."""
    rows = []
    for (place, first, last), _ in kept:
        if projector.edition.get(first) != KJV:
            continue
        span = projector.project(first, last)
        if span is None or projector.edition[span[0]] != projector.edition[span[1]]:
            report["projection: unmatched"] += 1
            continue
        if verse_aligned(words, first, last):
            span = (words.verse_ends(projector.verse[span[0]])[0], words.verse_ends(projector.verse[span[1]])[1])
        rows.append(((place, *span), "projection Hebrew" if projector.edition[span[0]] == 2 else "projection Greek"))
    return rows


def main(path, source, check):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("pragma busy_timeout = 60000")
    db.execute("pragma foreign_keys = on")
    report = Counter()
    rejects = []
    words = Words(db)
    kept, missing = stage(db, source, words, report, rejects)
    if check:
        for where, problem in rejects:
            print(f"{where}: {problem}")
        print(f"{len(kept)} settings, {len(rejects)} problems, {sum(missing.values())} missing places")
        return
    rows = [(key, "settings") for key, _ in kept] + projections(Projector(db), words, kept, report)

    db.execute("begin immediate")
    try:
        db.execute("delete from setting")
        for row, label in rows:
            added = db.execute(
                "insert or ignore into setting (place_id, first_word_id, last_word_id) values (?, ?, ?)", row
            ).rowcount
            report[f"{label}: {'added' if added else 'already there'}"] += 1
    except sqlite3.DatabaseError as error:
        db.execute("rollback")
        sys.exit(f"rejected by the database, nothing applied: {error}")
    db.execute("commit")

    for key, n in sorted(report.items()):
        print(f"{key}: {n}")
    if missing:
        print("missing places:")
        for name, n in missing.most_common():
            print(f"  {name}: {n}")


if __name__ == "__main__":
    check = sys.argv[1] == "--check"
    main(*sys.argv[1 + check : 3 + check], check)
