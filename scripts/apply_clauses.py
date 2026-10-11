"""Add clauses and clause parts from staged decisions, one JSON line per sentence.

    python scripts/apply_clauses.py scripture.db decisions/clauses [--check]
    python scripts/apply_clauses.py scripture.db decisions/clauses/kjv-001.jsonl --check

A line names a sentence, the clauses to add, and parts or wider spans for clauses already there:

    {"sentence_id": 31727,
     "new": [{"words": [13185, 13196], "parts": [["S", 13185, 13185], ["V", 13186, 13186], ["A", 13189, 13191]]}],
     "existing": [{"clause_id": 147417, "parts": [["IO", 13199, 13200]]}]}

Roles are S, V, O, IO, C, A or their full names, each followed by the first and last word id of the part.
A new clause's parent is the smallest clause around it, and clauses it encloses move under it when it sits between them and their parent.
An existing clause may only widen, and only within its parent. Parts stay inside their clause and do not overlap each other.
A line that fails any check is skipped whole and printed. Clauses and parts already there are left alone, so a run can be repeated.
--check validates and reports without writing. Both modes list the gap words each touched sentence still has and sum them per edition.
"""

import json
import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_clause_packets import CODES, ROLE_CODES, Text  # noqa: E402

BATCH = 100


class Rejected(Exception):
    pass


def decision_files(target):
    if os.path.isfile(target):
        return [target]
    return sorted(os.path.join(target, n) for n in os.listdir(target) if n.endswith(".jsonl"))


def read_lines(path, report, rejects):
    for number, line in enumerate(open(path, encoding="utf-8"), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            report["lines unreadable"] += 1
            rejects.append(f"{os.path.basename(path)}:{number}: unreadable JSON")
            continue
        yield number, record


class Sentence:
    """The clauses and parts of one sentence, as word sequences, with the changes a decision asks for."""

    def __init__(self, db, text, roles, sentence):
        self.text = text
        self.roles = roles
        span = db.execute("select first_word_id, last_word_id from sentence where id = ?", (sentence,)).fetchone()
        if span is None:
            raise Rejected("unknown sentence")
        self.id = sentence
        self.edition = text.words[span[0]][4]
        self.first, self.last = text.seq(span[0]), text.seq(span[1])
        self.spans, self.parent, self.parts = {}, {}, {}
        for clause, parent, a, b in db.execute(
            "select id, parent_id, first_word_id, last_word_id from clause where sentence_id = ?", (sentence,)
        ):
            self.spans[clause] = (text.seq(a), text.seq(b))
            self.parent[clause] = parent
            self.parts[clause] = set()
        for clause, role, a, b in db.execute(
            "select clause_id, clause_role_id, first_word_id, last_word_id from clause_part "
            "where clause_id in (select id from clause where sentence_id = ?)",
            (sentence,),
        ):
            self.parts[clause].add((role, text.seq(a), text.seq(b)))
        self.original = dict(self.spans)
        self.new_parts = {}
        self.added = []
        self.repeats = 0

    def words(self, pair, what):
        if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(w, int) for w in pair)):
            raise Rejected(f"{what}: words must be [first_word_id, last_word_id]")
        if any(w not in self.text.words for w in pair):
            raise Rejected(f"{what}: unknown word id in {pair}")
        a, b = self.text.seq(pair[0]), self.text.seq(pair[1])
        if a > b:
            raise Rejected(f"{what}: {pair} runs backward")
        if a < self.first or b > self.last:
            raise Rejected(f"{what}: {pair} is outside the sentence")
        return a, b

    def add_parts(self, clause, parts, what):
        if not isinstance(parts, list):
            raise Rejected(f"{what}: parts must be a list")
        a, b = self.spans[clause]
        wanted = self.new_parts.setdefault(clause, [])
        for part in parts:
            if not (isinstance(part, list) and len(part) == 3 and isinstance(part[0], str) and part[0] in self.roles):
                raise Rejected(f"{what}: part {part} must be [role, first_word_id, last_word_id]")
            x, y = self.words(part[1:], f"{what} part {part}")
            if x < a or y > b:
                raise Rejected(f"{what}: part {part} is outside its clause")
            entry = (self.roles[part[0]], x, y)
            if entry in self.parts[clause] or entry in wanted:
                self.repeats += 1
                continue
            for _, p, q in list(self.parts[clause]) + wanted:
                if x <= q and p <= y:
                    raise Rejected(f"{what}: part {part} overlaps another part of the clause")
            wanted.append(entry)

    def widen(self, change):
        if not isinstance(change, dict):
            raise Rejected("each existing entry must be an object")
        clause = change.get("clause_id")
        if clause not in self.spans:
            raise Rejected(f"clause {clause} is not in this sentence")
        if "words" in change:
            a, b = self.words(change["words"], f"clause {clause}")
            old = self.spans[clause]
            if a > old[0] or b < old[1]:
                raise Rejected(f"clause {clause}: words may only widen the clause")
            self.spans[clause] = (a, b)
        return clause

    def add(self, clause, index):
        what = f"new clause {index + 1}"
        if not isinstance(clause, dict):
            raise Rejected(f"{what} must be an object")
        span = self.words(clause.get("words"), what)
        same = [c for c, s in self.spans.items() if s == span]
        if same:
            return innermost(same)
        key = f"new{index}"
        self.spans[key] = span
        self.parts[key] = set()
        self.added.append(key)
        return key

    def settle(self):
        """Give each new clause its parent, move enclosed clauses under it, and check widened clauses."""
        for clause in self.added:
            self.parent[clause] = self.smallest_around(clause)
        for clause in self.original:
            span = self.spans[clause]
            parent = self.parent[clause]
            if parent is not None and parent in self.spans and not inside(span, self.spans[parent]):
                raise Rejected(f"clause {clause} would reach past its parent {parent}")
            if span != self.original[clause] and any(s == span for c, s in self.spans.items() if c != clause):
                raise Rejected(f"clause {clause} would match another clause exactly")
            closer = [
                c for c in self.added
                if inside(span, self.spans[c]) and span != self.spans[c] and self.descends(c, parent)
            ]
            if closer:
                self.parent[clause] = min(closer, key=lambda c: size(self.spans[c]))

    def smallest_around(self, clause):
        span = self.spans[clause]
        around = [c for c, s in self.spans.items() if c != clause and inside(span, s) and s != span]
        if not around:
            return None
        least = min(size(self.spans[c]) for c in around)
        return innermost([c for c in around if size(self.spans[c]) == least])

    def descends(self, clause, ancestor):
        while clause is not None:
            clause = self.parent[clause]
            if clause == ancestor:
                return True
        return ancestor is None

    def changed(self):
        widened = any(self.spans[c] != s for c, s in self.original.items())
        return bool(self.added or widened or any(self.new_parts.values()))

    def write(self, db, report):
        ids = {}
        for clause in sorted(self.added, key=lambda c: -size(self.spans[c])):
            parent = self.parent[clause]
            ids[clause] = db.execute(
                "insert into clause (sentence_id, parent_id, first_word_id, last_word_id) values (?, ?, ?, ?)",
                (self.id, ids.get(parent, parent), self.text.at[self.spans[clause][0]], self.text.at[self.spans[clause][1]]),
            ).lastrowid
            report["clauses added"] += 1
        for clause, span in self.original.items():
            if self.spans[clause] != span:
                db.execute(
                    "update clause set first_word_id = ?, last_word_id = ? where id = ?",
                    (self.text.at[self.spans[clause][0]], self.text.at[self.spans[clause][1]], clause),
                )
                report["clauses widened"] += 1
        for clause in self.original:
            parent = self.parent[clause]
            if parent in ids:
                db.execute("update clause set parent_id = ? where id = ?", (ids[parent], clause))
                report["clauses moved under a new clause"] += 1
        for clause, parts in self.new_parts.items():
            for role, a, b in parts:
                db.execute(
                    "insert into clause_part (clause_id, clause_role_id, first_word_id, last_word_id) values (?, ?, ?, ?)",
                    (ids.get(clause, clause), role, self.text.at[a], self.text.at[b]),
                )
                report["parts added"] += 1


def innermost(clauses):
    """Of clauses sharing a span, the one stored last, which hangs below the others."""
    existing = [c for c in clauses if isinstance(c, int)]
    return max(existing) if existing else clauses[0]


def inside(span, around):
    return around[0] <= span[0] and span[1] <= around[1]


def size(span):
    return span[1] - span[0]


def apply(db, text, roles, record, report):
    if not isinstance(record, dict) or not isinstance(record.get("sentence_id"), int):
        raise Rejected("line has no sentence_id")
    unknown = set(record) - {"sentence_id", "new", "existing", "note"}
    if unknown:
        raise Rejected(f"unknown keys {sorted(unknown)}")
    sentence = Sentence(db, text, roles, record["sentence_id"])
    changes = record.get("existing", [])
    clauses = record.get("new", [])
    if not isinstance(changes, list) or not isinstance(clauses, list):
        raise Rejected("new and existing must be lists")
    widened = [(sentence.widen(change), change) for change in changes]
    added = [(sentence.add(clause, i), clause) for i, clause in enumerate(clauses)]
    report["clauses already there"] += sum(1 for key, _ in added if key not in sentence.added)
    sentence.settle()
    for clause, change in widened:
        sentence.add_parts(clause, change.get("parts", []), f"clause {clause}")
    for i, (clause, entry) in enumerate(added):
        sentence.add_parts(clause, entry.get("parts", []), f"new clause {i + 1}")
    if not sentence.changed():
        report["lines with nothing new"] += 1
    sentence.write(db, report)
    report["parts already there"] += sentence.repeats
    return sentence.edition


def gap_words(db, text, sentence):
    covered = set()
    for a, b in db.execute("select first_word_id, last_word_id from clause where sentence_id = ?", (sentence,)):
        covered.update(range(text.seq(a), text.seq(b) + 1))
    return [word for run in text.gaps(sentence, covered) for word in run]


def main(path, target, check=False):
    db = sqlite3.connect(path, isolation_level=None, timeout=60)
    db.execute("pragma busy_timeout = 60000")
    db.execute("pragma foreign_keys = on")
    text = Text(db)
    roles = {}
    for role, name in db.execute("select id, name from clause_role"):
        roles[name] = role
        roles[ROLE_CODES[name]] = role
    report, rejects, touched, left = Counter(), [], {}, {}
    records = [(f, n, r) for f in decision_files(target) for n, r in read_lines(f, report, rejects)]
    for start in range(0, len(records), BATCH):
        db.execute("begin immediate")
        for name, number, record in records[start:start + BATCH]:
            report["lines"] += 1
            try:
                db.execute("savepoint line")
                counts = Counter()
                edition = apply(db, text, roles, record, counts)
                db.execute("release line")
                report.update(counts)
                touched[record["sentence_id"]] = edition
                left[record["sentence_id"]] = gap_words(db, text, record["sentence_id"])
            except Rejected as problem:
                db.execute("rollback to line")
                db.execute("release line")
                report["lines rejected"] += 1
                rejects.append(f"{os.path.basename(name)}:{number}: sentence {record.get('sentence_id') if isinstance(record, dict) else '?'}: {problem}")
        problems = db.execute("pragma foreign_key_check").fetchall()
        if problems:
            db.execute("rollback")
            sys.exit(f"foreign key problems, batch not applied: {problems[:10]}")
        db.execute("rollback" if check else "commit")
    for problem in rejects:
        print(f"rejected {problem}")
    for sentence, words in left.items():
        if words:
            print(f"gaps left in sentence {sentence}: " + " ".join(f"{w}:{text.words[w][1]}" for w in words))
    for key, n in sorted(report.items()):
        print(f"{key}: {n}")
    by_edition = Counter()
    for sentence, edition in touched.items():
        edition = CODES[edition]
        by_edition[edition, "sentences"] += 1
        by_edition[edition, "gap words before"] += sum(len(run) for run in text.gaps(sentence))
        by_edition[edition, "gap words after"] += len(left[sentence])
        by_edition[edition, "sentences still with gaps"] += bool(left[sentence])
    for (edition, key), n in sorted(by_edition.items()):
        print(f"{edition} {key}: {n}")
    if check:
        print("checked only, nothing written")


if __name__ == "__main__":
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0], args[1], "--check" in flags)
