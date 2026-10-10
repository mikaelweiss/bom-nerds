"""Tag office entities where a verse names the office and no mention records it.

    python3 scripts/tag_office_mentions.py [DB]

An office is tagged on its title word or phrase (apostle, priest's office, chief
captain) as a "Refers to" mention, only where nothing in the span is already a
mention of a group, a person, or another office. A rule marked person_ok also
tags a title that sits on a named holder ("Paul, an apostle"), since the title
is the office. Generic uses ("the priest shall burn it") go to the office of
the context: the Levitical priest in the Old Testament, the Aaronic or
Melchizedek offices in the Doctrine and Covenants, the Nephite offices in the
Book of Mormon. Rules without listed verses take every match in the edition.

King James mentions are copied onto the Hebrew and Greek through word_match
with the Projector of project_to_originals.py. Rerunning adds nothing new.
"""

import re
import sqlite3
import sys
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from pathlib import Path

from project_to_originals import Projector

KJV, BOM, DC, PGP = 1, 4, 5, 6
REFERS_TO = 1
MAX_ORIGINAL_WORDS = 4
OVERLAP_REACH = 300

APOSTLE, ELDER, HIGH_PRIEST, PRIEST_LAW, AARONIC, BISHOP_NT, CUPBEARER, ROYAL_SCRIBE = 9046, 9056, 9060, 13869, 9371, 12372, 14246, 14376
PRIEST_NEPHITE, TEACHER_NEPHITE, KING_NEPHITES, KING_LAMANITES, KING_JAREDITES = 9164, 9165, 9136, 9193, 9563
ELDER_MELCHIZEDEK, PRIEST_AARONIC, MELCHIZEDEK, BISHOP_DC, SEER, CHIEF_CAPTAIN = 9325, 9352, 9370, 9376, 9722, 9929
APOSTLE_RESTORED, AGENT, RECORDER = 10165, 10342, 10524
JS_HISTORY = "Joseph Smith" + chr(0x2014) + "History"


def places(spec):
    return {f"{book} {place}" for book, listed in spec for place in listed.split()}


class Rule:
    def __init__(self, entity, edition, pattern, only=None, skip=(), person_ok=False):
        self.entity = entity
        self.edition = edition
        self.pattern = re.compile(pattern)
        self.group = 1 if self.pattern.groups else 0
        self.only = places(only) if only else None
        self.skip = places(skip)
        self.person_ok = person_ok


RULES = [
    Rule(APOSTLE, KJV, r"\b(apostles?|apostleship)\b", person_ok=True, only=[
        ("Luke", "11:49"), ("Acts", "1:25 8:18 14:4 14:14"), ("Romans", "1:1 1:5 11:13 16:7"),
        ("1 Corinthians", "1:1 4:9 9:1 9:2 9:5 12:28 12:29 15:9"), ("2 Corinthians", "1:1 11:13 12:12"),
        ("Galatians", "1:1 2:8"), ("Ephesians", "1:1"), ("Colossians", "1:1"), ("1 Thessalonians", "2:6"),
        ("1 Timothy", "1:1 2:7"), ("2 Timothy", "1:1 1:11"), ("Titus", "1:1"), ("Hebrews", "3:1"),
        ("1 Peter", "1:1"), ("2 Peter", "1:1")]),
    Rule(ELDER, KJV, r"\belders?\b", only=[
        ("Deuteronomy", "19:12 21:2 29:10"), ("Joshua", "20:4"), ("1 Samuel", "15:30"), ("Ezra", "10:14"),
        ("Psalms", "107:32"), ("Proverbs", "31:23"), ("1 Timothy", "5:17 5:19"), ("Titus", "1:5"), ("James", "5:14")]),
    Rule(HIGH_PRIEST, KJV, r"\b(high priests?|priest)\b", only=[("Hebrews", "7:17 7:20 7:21 7:27 7:28")]),
    Rule(PRIEST_LAW, KJV, r"\b(priest's office)\b"),
    Rule(PRIEST_LAW, KJV, r"\b(priests?|priest's)\b", skip=[
        ("Exodus", "29:30"), ("Leviticus", "6:22"), ("2 Chronicles", "13:9 34:5"), ("Hosea", "10:5"), ("Zechariah", "6:13"),
        ("Hebrews", "7:3"), ("Revelation", "1:6 5:10 20:6")]),
    Rule(AARONIC, KJV, r"\bpriesthood\b", only=[
        ("Exodus", "40:15"), ("Numbers", "16:10 18:1 25:13"), ("Joshua", "18:7"), ("Ezra", "2:62"),
        ("Nehemiah", "7:64 13:29"), ("Hebrews", "7:12 7:14")]),
    Rule(BISHOP_NT, KJV, r"\b(bishop|bishoprick)\b", only=[("Acts", "1:20"), ("Titus", "1:7 3:15"), ("2 Timothy", "4:22")]),
    Rule(CUPBEARER, KJV, r"\bcupbearer\b", only=[("Nehemiah", "1:11")], person_ok=True),
    Rule(ROYAL_SCRIBE, KJV, r"\bscribe\b", only=[("2 Chronicles", "24:11")]),
    Rule(ELDER, BOM, r"\belders?\b", only=[("Moroni", "6:1 6:7")]),
    Rule(APOSTLE, BOM, r"\bapostles?\b", only=[("1 Nephi", "14:24 14:25 14:27"), ("Ether", "12:41")], person_ok=True),
    Rule(PRIEST_NEPHITE, BOM, r"\bpriests?\b", only=[
        ("2 Nephi", "5:26"), ("Mosiah", "18:18 25:21"), ("Alma", "1:3 1:26 30:28 30:31 45:22 45:23"), ("Moroni", "6:1")]),
    Rule(TEACHER_NEPHITE, BOM, r"\bteachers?\b", only=[
        ("2 Nephi", "5:26"), ("Mosiah", "25:20"), ("Alma", "1:3 1:26 30:31 45:22 45:23"), ("Helaman", "3:25"), ("Moroni", "6:1")]),
    Rule(SEER, BOM, r"\bseers?\b", only=[("2 Nephi", "27:5")]),
    Rule(CHIEF_CAPTAIN, BOM, r"\b(chief captains?)\b", only=[("Alma", "2:13 2:16 49:16"), ("3 Nephi", "3:17 3:19")]),
    Rule(KING_JAREDITES, BOM, r"\bkings?\b", only=[("Ether", "9:4 9:14 9:15 10:9 10:10 10:16")]),
    Rule(KING_NEPHITES, BOM, r"\bkings?\b", only=[
        ("2 Nephi", "5:18"), ("Mosiah", "23:6 23:7 23:8 23:13 29:1 29:2 29:5 29:16 29:17 29:21 29:23 29:30 29:33 29:35 29:38"),
        ("Alma", "46:4 46:5 51:5"), ("3 Nephi", "6:30 7:1")]),
    Rule(KING_LAMANITES, BOM, r"\bking\b", only=[("Mosiah", "24:3"), ("Alma", "52:3")]),
    Rule(ELDER_MELCHIZEDEK, DC, r"\belders?\b", person_ok=True, only=[
        ("Doctrine and Covenants", "20:2 20:3 21:1 21:11 36:7 57:16 58:56")]),
    Rule(APOSTLE, DC, r"\bapostles?\b", person_ok=True, only=[
        ("Doctrine and Covenants", "1:14 18:9 19:8 49:11 52:9 52:36 66:2 74:5 98:32 138:5")]),
    Rule(APOSTLE_RESTORED, DC, r"\bapostles?\b", person_ok=True, only=[("Doctrine and Covenants", "21:1 21:10 27:12")]),
    Rule(PRIEST_AARONIC, DC, r"\bpriests?\b", only=[("Doctrine and Covenants", "102:5")]),
    Rule(AGENT, DC, r"\bagent\b", only=[("Doctrine and Covenants", "51:8 51:12 53:4 58:49")]),
    Rule(RECORDER, DC, r"\brecorder\b", only=[("Doctrine and Covenants", "127:6")]),
    Rule(BISHOP_DC, DC, r"\bbishopric\b", only=[("Doctrine and Covenants", "114:2")]),
    Rule(MELCHIZEDEK, DC, r"\bpriesthood\b", only=[("Doctrine and Covenants", "127:8 128:21")]),
    Rule(MELCHIZEDEK, PGP, r"\bpriesthood\b", only=[("Moses", "6:7"), ("Abraham", "1:4 1:18 1:26 1:27 1:31 2:9 2:11")]),
    Rule(APOSTLE, PGP, r"\bapostles\b", only=[("Articles of Faith", "1:6")]),
    Rule(SEER, PGP, r"\bseers\b", only=[(JS_HISTORY, "1:35")]),
]


def normalize(text):
    return re.sub(r"[^\w'-]", "", text.lower().replace("’", "'"))


class Corpus:
    def __init__(self, db, editions):
        marks = ",".join("?" * len(editions))
        self.words = defaultdict(list)
        self.place = {}
        self.edition = {}
        for verse, word, sequence, text, book, chapter, number, edition in db.execute(
            "select v.id, w.id, w.sequence, w.text, b.name, c.number, v.number, c.edition_id from word w "
            "join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id join book b on b.id = c.book_id "
            f"where c.edition_id in ({marks}) and v.number is not null order by w.sequence",
            editions,
        ):
            self.words[verse].append((word, sequence, normalize(text)))
            self.place[verse] = f"{book} {chapter}:{number}"
            self.edition[verse] = edition


class Coverage:
    def __init__(self, db):
        self.rows = sorted(
            db.execute(
                "select f.sequence, l.sequence, m.entity_id, t.name, m.mention_kind_id from mention m join entity e on e.id = m.entity_id "
                "join entity_type t on t.id = e.entity_type_id join word f on f.id = m.first_word_id "
                "join word l on l.id = m.last_word_id where t.name <> 'Topic' and l.sequence - f.sequence < ?",
                (OVERLAP_REACH,),
            )
        )
        self.starts = [row[0] for row in self.rows]

    def over(self, first, last):
        low = bisect_left(self.starts, first - OVERLAP_REACH)
        high = bisect_right(self.starts, last)
        return [row for row in self.rows[low:high] if row[0] <= last and row[1] >= first and row[4] == REFERS_TO]

    def add(self, first, last, entity, kind):
        row = (first, last, entity, kind, REFERS_TO)
        index = bisect_left(self.rows, row)
        self.rows.insert(index, row)
        self.starts.insert(index, first)


def matches(rule, corpus):
    for verse, words in corpus.words.items():
        place = corpus.place[verse]
        if corpus.edition[verse] != rule.edition or place in rule.skip or (rule.only and place not in rule.only):
            continue
        text = " ".join(t for _, _, t in words)
        starts, position = [], 0
        for _, _, t in words:
            starts.append(position)
            position += len(t) + 1
        for found in rule.pattern.finditer(text):
            first = bisect_right(starts, found.start(rule.group)) - 1
            last = bisect_right(starts, found.end(rule.group) - 1) - 1
            yield words[first], words[last]


def tag_english(db, corpus, coverage, report):
    targets = []
    for rule in RULES:
        rows = []
        for first, last in matches(rule, corpus):
            report["matched", rule.edition] += 1
            covering = coverage.over(first[1], last[1])
            if any(entity == rule.entity for _, _, entity, _, _ in covering):
                if rule.edition == KJV:
                    targets.append((rule.entity, first[0], last[0]))
                continue
            blocked = {"Group", "Office"} if rule.person_ok else {"Group", "Office", "Person"}
            if any(kind in blocked for _, _, _, kind, _ in covering) or (covering and not rule.person_ok):
                report["covered", rule.edition] += 1
                continue
            rows.append((rule.entity, REFERS_TO, first[0], last[0]))
            if rule.edition == KJV:
                targets.append((rule.entity, first[0], last[0]))
            coverage.add(first[1], last[1], rule.entity, "Office")
        added = db.executemany(
            "insert or ignore into mention (entity_id, mention_kind_id, first_word_id, last_word_id) values (?, ?, ?, ?)", rows
        ).rowcount
        report["added", rule.edition] += added
        db.commit()
    return targets


def project(db, targets, report):
    projector = Projector(db)
    for entity, first, last in set(targets):
        span = projector.project(first, last)
        if span is None:
            report["original unmatched", 0] += 1
            continue
        low, high = span
        width = projector.seq[high] - projector.seq[low] + 1
        if projector.edition[low] != projector.edition[high] or width > MAX_ORIGINAL_WORDS:
            report["original span too wide", 0] += 1
            continue
        added = db.execute(
            "insert or ignore into mention (entity_id, mention_kind_id, first_word_id, last_word_id) values (?, ?, ?, ?)",
            (entity, REFERS_TO, low, high),
        ).rowcount
        report["added", projector.edition[low]] += added
    db.commit()


def office_counts(db):
    return dict(
        db.execute(
            "select entity_id, count(*) from mention where entity_id in (select id from entity where entity_type_id = 12) group by 1"
        )
    )


def main(path):
    db = sqlite3.connect(path, timeout=60)
    db.execute("pragma busy_timeout = 60000")
    db.execute("pragma foreign_keys = on")
    before = office_counts(db)

    corpus = Corpus(db, sorted({rule.edition for rule in RULES}))
    report = Counter()
    targets = tag_english(db, corpus, Coverage(db), report)
    project(db, targets, report)

    after = office_counts(db)
    names = dict(db.execute("select id, name from entity where entity_type_id = 12"))
    print("office mentions before -> after")
    for entity in sorted(after, key=lambda e: (names[e], e)):
        if after[entity] != before.get(entity, 0):
            print(f"  {names[entity]} ({entity}): {before.get(entity, 0)} -> {after[entity]}")
    for (label, edition), n in sorted(report.items()):
        print(f"{label}, edition {edition}: {n}" if edition else f"{label}: {n}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent.parent / "scripture.db"))
