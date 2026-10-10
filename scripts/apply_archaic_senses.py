"""Apply staged archaic sense decisions: tag English words with a sense of their headword, or add a sense and tag with it.

    python scripts/apply_archaic_senses.py scripture.db decisions/archaic-senses

Each senses_*.jsonl line is one of
    {"word_id": 1, "meaning_id": 2}
    {"word_id": 1, "skip": "why the context does not decide"}
    {"headword_id": 3, "gloss": "...", "definition": "...", "word_ids": [1, 4]}
A word is tagged only when the sense belongs to its headword and the word has no sense yet, or already has that one.
A word given two different answers anywhere in the directory is left alone. Reruns change nothing.
"""

import glob
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict


def read_lines(path, report):
    name = os.path.basename(path)
    for number, line in enumerate(open(path, encoding="utf-8"), 1):
        if not line.strip():
            continue
        try:
            decision = json.loads(line)
        except json.JSONDecodeError:
            report[f"{name}: unreadable line"] += 1
            continue
        if {"word_id", "meaning_id"} <= decision.keys():
            yield "tag", decision
        elif {"word_id", "skip"} <= decision.keys():
            yield "skip", decision
        elif {"headword_id", "gloss", "word_ids"} <= decision.keys():
            yield "new", decision
        else:
            report[f"{name}: line {number} has no known shape"] += 1


def answers_by_word(paths, report):
    answers = defaultdict(set)
    for path in paths:
        for kind, decision in read_lines(path, report):
            if kind == "tag":
                answers[decision["word_id"]].add(("meaning", decision["meaning_id"]))
            elif kind == "skip":
                answers[decision["word_id"]].add(("skip",))
            else:
                key = ("new", decision["headword_id"], decision["gloss"], decision.get("definition"))
                for word in decision["word_ids"]:
                    answers[word].add(key)
    return {word for word, found in answers.items() if len(found) > 1}


def tag(db, word, meaning, report):
    row = db.execute(
        "select w.headword_id, w.meaning_id, m.headword_id from word w left join meaning m on m.id = ? where w.id = ?",
        (meaning, word),
    ).fetchone()
    if row is None or row[2] is None:
        report["rejected: unknown word or sense"] += 1
    elif row[0] != row[2]:
        report["rejected: sense belongs to another headword"] += 1
    elif row[1] == meaning:
        report["already tagged with this sense"] += 1
    elif row[1] is not None:
        report["rejected: word already has another sense"] += 1
    else:
        db.execute("update word set meaning_id = ? where id = ? and meaning_id is null", (meaning, word))
        report["tagged"] += 1


def add_sense(db, decision, report):
    headword = decision["headword_id"]
    if not db.execute("select 1 from headword where id = ? and language_id = 1", (headword,)).fetchone():
        report["new senses: rejected, unknown English headword"] += 1
        return None
    if not decision["gloss"].strip():
        report["new senses: rejected, empty gloss"] += 1
        return None
    existing = db.execute(
        "select id from meaning where headword_id = ? and gloss = ? and definition is ?",
        (headword, decision["gloss"], decision.get("definition")),
    ).fetchone()
    if existing:
        report["new senses: already there"] += 1
        return existing[0]
    number = db.execute("select coalesce(max(number), 0) + 1 from meaning where headword_id = ?", (headword,)).fetchone()[0]
    report["new senses: added"] += 1
    return db.execute(
        "insert into meaning (headword_id, number, gloss, definition) values (?, ?, ?, ?)",
        (headword, number, decision["gloss"], decision.get("definition")),
    ).lastrowid


def open_word(db, word, headword, conflicted):
    return word not in conflicted and db.execute(
        "select 1 from word where id = ? and headword_id = ? and meaning_id is null", (word, headword)
    ).fetchone()


def apply_file(db, path, conflicted, report):
    db.execute("begin immediate")
    for kind, decision in read_lines(path, Counter()):
        if kind == "skip":
            report["skipped as ambiguous"] += 1
            continue
        words = [decision["word_id"]] if kind == "tag" else decision["word_ids"]
        if kind == "new" and not any(open_word(db, word, decision["headword_id"], conflicted) for word in words):
            report["new senses: no untagged word left, line passed over"] += 1
            continue
        meaning = decision["meaning_id"] if kind == "tag" else add_sense(db, decision, report)
        if meaning is None:
            continue
        for word in words:
            if word in conflicted:
                report["rejected: word has conflicting answers"] += 1
            else:
                tag(db, word, meaning, report)
    problems = db.execute("pragma foreign_key_check(word)").fetchall()
    if problems:
        db.execute("rollback")
        sys.exit(f"{os.path.basename(path)}: foreign key problems, file not applied: {problems[:10]}")
    db.execute("commit")


def main(path, directory):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("pragma busy_timeout = 60000")
    db.execute("pragma foreign_keys = on")
    paths = sorted(glob.glob(os.path.join(directory, "senses_*.jsonl")))
    report = Counter()
    conflicted = answers_by_word(paths, report)
    for path in paths:
        apply_file(db, path, conflicted, report)
    report["files"] = len(paths)
    for key, n in sorted(report.items()):
        print(f"{key}: {n}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
