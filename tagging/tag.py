#!/usr/bin/env python3
import argparse
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATABASE = ROOT / "scripture.db"
RULES = ROOT / "docs" / "tagging.md"
FORMAT = ROOT / "tagging" / "answer.md"
KEYS = ROOT / "tagging" / "keys"
RUNS = ROOT / "tagging" / "runs"
GODHEAD = ("Jesus Christ", "God the Father", "Holy Ghost")

SPAN = r'(\d+):(\d+) "([^"]*)"(?:#(\d+))?'
RANGE = re.compile(rf"{SPAN}(?:\s*\.\.\s*{SPAN})?")
ENTITY = r"(#\d+|\+[\w.'-]+)"


def norm(text: str) -> str:
    return re.sub(r"[^\w'-]", "", text.replace("’", "'").lower())


@dataclass
class Passage:
    label: str
    edition: str
    book_id: int
    chapters: list[int]
    verses: list[tuple[int, int, int]] = field(default_factory=list)
    words: dict[tuple[int, int], list[tuple[int, str, str, str]]] = field(default_factory=dict)
    where: dict[int, tuple[int, int, int]] = field(default_factory=dict)

    @property
    def ids(self) -> set[int]:
        return set(self.where)


def passage(db: sqlite3.Connection, label: str) -> Passage:
    match = re.fullmatch(r"(.+?) (\d+)(?::(\d+)(?:-(\d+))?|-(\d+))?", label.strip())
    if not match:
        sys.exit(f"cannot read passage {label!r}: use Book C, Book C-C, or Book C:V-V")
    book, chapter, first_verse, last_verse, last_chapter = match.groups()
    row = db.execute(
        """select e.id, e.name, b.id from book b join edition_book eb on eb.book_id = b.id join edition e on e.id = eb.edition_id
           join language l on l.id = e.language_id where b.name = ? and l.iso_code = 'en'""",
        (book,),
    ).fetchone()
    if not row:
        sys.exit(f"no English edition has the book {book!r}")
    edition_id, edition, book_id = row
    chapters = list(range(int(chapter), int(last_chapter or chapter) + 1))
    found = Passage(label, edition, book_id, chapters)
    low = int(first_verse) if first_verse else None
    high = int(last_verse or first_verse) if first_verse else None
    rows = db.execute(
        f"""select v.id, c.number, coalesce(v.number, 0), w.id, w.text, w.before, w.after from word w
            join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id
            where c.edition_id = ? and c.book_id = ? and c.number in ({','.join('?' * len(chapters))}) order by w.sequence""",
        (edition_id, book_id, *chapters),
    )
    for verse_id, c, v, word_id, text, before, after in rows:
        if low is not None and not (low <= v <= high):
            continue
        if (c, v) not in found.words:
            found.verses.append((verse_id, c, v))
            found.words[(c, v)] = []
        found.words[(c, v)].append((word_id, text, before, after))
        found.where[word_id] = (c, v, len(found.words[(c, v)]) - 1)
    if not found.verses:
        sys.exit(f"no verses in {label}")
    return found


def span_text(p: Passage, first: int, last: int) -> str:
    c, v, a = p.where[first]
    if last in p.where and p.where[last][:2] == (c, v):
        b = p.where[last][2]
        return quoted(p, c, v, a, b)
    end = p.where.get(last)
    if not end:
        return f"{quoted(p, c, v, a, a)} .. (outside passage: word {last})"
    return f"{quoted(p, c, v, a, min(a + 2, len(p.words[(c, v)]) - 1))} .. {quoted(p, end[0], end[1], max(0, end[2] - 2), end[2])}"


def quoted(p: Passage, c: int, v: int, a: int, b: int) -> str:
    words = [norm(w[1]) for w in p.words[(c, v)]]
    target = words[a:b + 1]
    count = sum(1 for i in range(a + 1) if words[i:i + len(target)] == target)
    text = " ".join(w[1] for w in p.words[(c, v)][a:b + 1])
    return f'{c}:{v} "{text}"' + (f"#{count}" if count > 1 else "")


def resolve(p: Passage, text: str) -> tuple[int, int]:
    match = RANGE.fullmatch(text.strip())
    if not match:
        raise ValueError(f"not a span: {text}")
    groups = match.groups()
    first = find(p, *groups[:4])
    last = find(p, *groups[4:]) if groups[4] else first
    if p.where[last[1]] < p.where[first[0]]:
        raise ValueError(f"span runs backward: {text}")
    return first[0], last[1]


def find(p: Passage, c: str, v: str, words: str, occurrence: str | None) -> tuple[int, int]:
    verse = p.words.get((int(c), int(v)))
    if verse is None:
        raise ValueError(f"no verse {c}:{v} in the passage")
    target = [norm(w) for w in words.split()]
    if not target:
        raise ValueError(f"empty quote in {c}:{v}")
    texts = [norm(w[1]) for w in verse]
    hits = [i for i in range(len(texts)) if texts[i:i + len(target)] == target]
    n = int(occurrence or 1)
    if len(hits) < n:
        raise ValueError(f'"{words}" does not appear {n} time(s) in {c}:{v}')
    i = hits[n - 1]
    return verse[i][0], verse[i + len(target) - 1][0]


def lists(db: sqlite3.Connection) -> dict[str, dict[str, int]]:
    return {
        "type": {n.lower(): i for i, n in db.execute("select id, name from entity_type")},
        "kind": {n.lower(): i for i, n in db.execute("select id, name from relationship_kind")},
        "mode": {n.lower(): i for i, n in db.execute("select id, name from speech_mode")},
        "system": {n.lower(): i for i, n in db.execute("select id, name from counting_system")},
    }


def current(db: sqlite3.Connection, p: Passage) -> list[str]:
    ids = sorted(p.ids)
    low, high = ids[0], ids[-1]
    lines = []
    for kind, entity, first, last in db.execute(
        "select mention_kind_id, entity_id, first_word_id, last_word_id from mention where first_word_id between ? and ? order by first_word_id, last_word_id",
        (low, high),
    ):
        if first in p.where:
            lines.append(f"{'M' if kind == 1 else 'A'} {span_text(p, first, last)} #{entity}")
    kinds = dict(db.execute("select id, name from relationship_kind"))
    evidence = defaultdict(list)
    for rid, first, last in db.execute("select relationship_id, first_word_id, last_word_id from relationship_evidence where first_word_id between ? and ?", (low, high)):
        if first in p.where:
            evidence[rid].append(span_text(p, first, last))
    for rid, spans in sorted(evidence.items()):
        s, k, o = db.execute("select subject_id, relationship_kind_id, object_id from relationship where id = ?", (rid,)).fetchone()
        lines.append(f"R #{s} | {kinds[k]} | #{o} | {'; '.join(spans)}")
    modes = dict(db.execute("select id, name from speech_mode"))
    for sid, speaker, through, mode, first, last in db.execute(
        "select id, speaker_id, through_id, speech_mode_id, first_word_id, last_word_id from speech where first_word_id between ? and ?", (low, high)
    ):
        listeners = ", ".join(f"#{e}" for e, in db.execute("select entity_id from speech_listener where speech_id = ?", (sid,)))
        lines.append(f"S #{speaker} | {modes[mode]} | {listeners} | {span_text(p, first, last)}" + (f" | through #{through}" if through else ""))
    for traveler, start, end, days, first, last in db.execute(
        "select traveler_id, from_id, to_id, days, first_word_id, last_word_id from journey where first_word_id between ? and ?", (low, high)
    ):
        lines.append(f"J #{traveler} | {f'#{start}' if start else '-'} | #{end} | {days or '-'} | {span_text(p, first, last)}")
    systems = dict(db.execute("select id, name from counting_system"))
    for row in db.execute(
        """select first_word_id, last_word_id, entity_id, counting_system_id, from_year, from_month, from_day, to_year, to_month, to_day,
                  evidence_first_word_id, evidence_last_word_id from date
           where first_word_id between ? and ? or evidence_first_word_id between ? and ?""",
        (low, high, low, high),
    ):
        first, last, entity, system, fy, fm, fd, ty, tm, td, ef, el = row
        target = span_text(p, first, last) if first in p.where else f"#{entity}"
        evidence_span = span_text(p, ef, el) if ef in p.where else "-"
        lines.append(f"D {target} | {systems[system]} | {ymd(fy, fm, fd)} | {ymd(ty, tm, td)} | {evidence_span}")
    return lines


def ymd(y, m, d) -> str:
    return "-".join(str(x) for x in (y, m, d) if x is not None)


def candidates(db: sqlite3.Connection, p: Passage, shown: list[str]) -> list[int]:
    found = {int(i) for i in re.findall(r'(?<!")#(\d+)', "\n".join(shown))}
    chapters = range(min(p.chapters) - 1, max(p.chapters) + 2)
    found |= {i for i, in db.execute(
        f"""select distinct m.entity_id from mention m join word w on w.id = m.first_word_id join verse v on v.id = w.verse_id
            join chapter c on c.id = v.chapter_id where c.book_id = ? and c.number in ({','.join('?' * len(chapters))})
            and c.edition_id = (select id from edition where name = ?)""",
        (p.book_id, *chapters, p.edition),
    )}
    text = " " + " ".join(re.sub(r"[^\w'’-]", "", w[1]) for words in p.words.values() for w in words) + " "
    for i, name in db.execute("select id, name from entity union all select entity_id, name from entity_name"):
        if name[:1].isupper() and f" {name} " in text:
            found.add(i)
    found |= {i for i, in db.execute(f"select id from entity where name in ({','.join('?' * len(GODHEAD))})", GODHEAD)}
    return sorted(found)


def entity_lines(db: sqlite3.Connection, ids: list[int]) -> list[str]:
    lines = []
    for i in ids:
        t, name, description = db.execute("select t.name, e.name, e.description from entity e join entity_type t on t.id = e.entity_type_id where e.id = ?", (i,)).fetchone()
        names = ", ".join(n + (" (title)" if title else "") for n, title in db.execute("select name, is_title from entity_name where entity_id = ? order by name", (i,)))
        lines.append(f"#{i} | {t} | {name} | {description}" + (f" | other names: {names}" if names else ""))
    return lines


def prompt(db: sqlite3.Connection, p: Passage) -> str:
    shown = current(db, p)
    named = lists(db)
    verses = [f"{c}:{v} " + "".join(f"{b}{t}{a}" for _, t, b, a in p.words[(c, v)]).strip() for _, c, v in p.verses]
    parts = [
        "You are tagging one passage of scripture. Follow the rules and the answer format below. Everything you need is in this message: do not use tools or read files. Reply with the answer lines only.",
        "# Rules\n\n" + RULES.read_text(),
        FORMAT.read_text(),
        "# Lists\n\n" + "\n".join(f"{k.title()}s: " + ", ".join(sorted(v)) for k, v in named.items()),
        "# Entities that may appear\n\n" + "\n".join(entity_lines(db, candidates(db, p, shown))),
        f"# Passage: {p.label} ({p.edition})\n\n" + "\n".join(verses),
        "# Current tags\n\n" + ("\n".join(shown) or "(none)"),
    ]
    return "\n\n".join(parts) + "\n"


@dataclass
class Answer:
    mentions: set = field(default_factory=set)
    entities: dict = field(default_factory=dict)
    names: set = field(default_factory=set)
    removed_names: set = field(default_factory=set)
    relationships: dict = field(default_factory=dict)
    speeches: list = field(default_factory=list)
    journeys: list = field(default_factory=list)
    dates: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def parse(db: sqlite3.Connection, p: Passage, text: str) -> Answer:
    named = lists(db)
    answer = Answer()
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().strip("`")
        if not line:
            continue
        try:
            read_line(line, p, named, answer)
        except (ValueError, KeyError) as error:
            answer.errors.append(f"line {number}: {error}: {line}")
    return answer


def field_list(line: str, n: int) -> list[str]:
    fields = [f.strip() for f in line[1:].split("|")]
    if len(fields) < n:
        raise ValueError(f"expected {n} fields")
    return fields


def entity_ref(text: str) -> str:
    if not re.fullmatch(ENTITY, text.strip()):
        raise ValueError(f"not an entity: {text}")
    return text.strip()


def lookup(table: dict[str, int], text: str, what: str) -> int:
    if text.strip().lower() not in table:
        raise ValueError(f"unknown {what}: {text}")
    return table[text.strip().lower()]


def read_line(line: str, p: Passage, named: dict, answer: Answer):
    tag = line[0]
    if tag in "MA":
        match = re.fullmatch(rf"[MA]\s+(.+)\s+{ENTITY}", line)
        if not match:
            raise ValueError("expected a span and an entity")
        first, last = resolve(p, match.group(1))
        answer.mentions.add((first, last, match.group(2), 1 if tag == "M" else 2))
    elif tag == "E":
        e, t, name, description = field_list(line, 4)[:4]
        answer.entities[entity_ref(e)] = (lookup(named["type"], t, "type"), name, description)
    elif tag == "N":
        e, name, kind = field_list(line, 3)[:3]
        answer.names.add((entity_ref(e), name, int(kind.lower() == "title")))
    elif tag == "X":
        e, name = field_list(line, 2)[:2]
        answer.removed_names.add((entity_ref(e), name))
    elif tag == "R":
        s, k, o, spans = field_list(line, 4)[:4]
        key = (entity_ref(s), lookup(named["kind"], k, "relationship kind"), entity_ref(o))
        answer.relationships.setdefault(key, set()).update(resolve(p, x) for x in spans.split(";") if x.strip())
    elif tag == "S":
        fields = field_list(line, 4)
        speaker, mode, listeners, span = fields[:4]
        through = None
        if len(fields) > 4:
            through = entity_ref(fields[4].removeprefix("through").strip())
        answer.speeches.append((entity_ref(speaker), lookup(named["mode"], mode, "mode"), frozenset(entity_ref(x) for x in listeners.split(",") if x.strip()), *resolve(p, span), through))
    elif tag == "J":
        traveler, start, end, days, span = field_list(line, 5)[:5]
        answer.journeys.append((entity_ref(traveler), None if start == "-" else entity_ref(start), entity_ref(end), None if days == "-" else float(days), *resolve(p, span)))
    elif tag == "D":
        target, system, start, end, evidence = field_list(line, 5)[:5]
        where = entity_ref(target) if target.startswith(("#", "+")) else resolve(p, target)
        answer.dates.append((where, lookup(named["system"], system, "counting system"), date(start), date(end), None if evidence == "-" else resolve(p, evidence)))
    else:
        raise ValueError("unknown line type")


def date(text: str) -> tuple:
    parts = [int(x) for x in re.fullmatch(r"(-?\d+)(?:-(\d+))?(?:-(\d+))?", text.strip()).groups() if x is not None]
    return tuple(parts + [None] * (3 - len(parts)))


def overlap(a: tuple[int, int], b: tuple[int, int], p: Passage) -> float:
    order = {w: i for i, w in enumerate(sorted(p.ids))}
    a0, a1 = order.get(a[0], -1), order.get(a[1], 10**9)
    b0, b1 = order.get(b[0], -1), order.get(b[1], 10**9)
    inter = min(a1, b1) - max(a0, b0) + 1
    union = max(a1, b1) - min(a0, b0) + 1
    return max(0, inter) / union


def score(db: sqlite3.Connection, p: Passage, got: Answer, key: Answer) -> dict:
    mapping = match_new(got, key)
    m = lambda e: mapping.get(e, e)
    results = {}
    results["mentions"] = tally({(a, b, m(e), k) for a, b, e, k in got.mentions}, key.mentions)
    two_way = {i for i, in db.execute("select id from relationship_kind where two_way = 1")}

    def rel_key(s, k, o):
        s, o = m(s), m(o)
        return (k, *sorted((s, o))) if k in two_way else (s, k, o)

    results["relationships"] = tally({rel_key(*r) for r in got.relationships}, {rel_key(*r) for r in key.relationships})
    results["speeches"] = fuzzy(
        [(m(s), mode, (a, b)) for s, mode, _, a, b, _ in got.speeches], [(s, mode, (a, b)) for s, mode, _, a, b, _ in key.speeches], p
    )
    results["journeys"] = fuzzy(
        [((m(t), m(f) if f else None, m(e)), 0, (a, b)) for t, f, e, _, a, b in got.journeys], [((t, f, e), 0, (a, b)) for t, f, e, _, a, b in key.journeys], p
    )
    results["dates"] = tally({(m(w) if isinstance(w, str) else w, s, a, b) for w, s, a, b, _ in got.dates}, {(w, s, a, b) for w, s, a, b, _ in key.dates})
    total = {k: sum(r[k] for r in results.values()) for k in ("right", "missed", "extra")}
    results["all"] = finish(total)
    results["unreadable"] = len(got.errors)
    results["new_entities"] = {"got": len([e for e in got.entities if e.startswith("+")]), "key": len([e for e in key.entities if e.startswith("+")])}
    return results


def tally(got: set, key: set) -> dict:
    return finish({"right": len(got & key), "missed": len(key - got), "extra": len(got - key)})


def fuzzy(got: list, key: list, p: Passage) -> dict:
    unmatched = list(key)
    right = 0
    for who, mode, span in got:
        best = max((k for k in unmatched if k[0] == who and k[1] == mode), key=lambda k: overlap(span, k[2], p), default=None)
        if best and overlap(span, best[2], p) >= 0.8:
            unmatched.remove(best)
            right += 1
    return finish({"right": right, "missed": len(unmatched), "extra": len(got) - right})


def finish(counts: dict) -> dict:
    r, missed, extra = counts["right"], counts["missed"], counts["extra"]
    precision = r / (r + extra) if r + extra else 1.0
    recall = r / (r + missed) if r + missed else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {**counts, "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def match_new(got: Answer, key: Answer) -> dict:
    spans = lambda answer, e: {(a, b) for a, b, x, _ in answer.mentions if x == e}
    pairs = []
    for g in [e for e in got.entities if e.startswith("+")]:
        for k in [e for e in key.entities if e.startswith("+")]:
            shared = len(spans(got, g) & spans(key, k))
            same_name = norm(got.entities[g][1]) == norm(key.entities[k][1])
            if shared or same_name:
                pairs.append((shared + same_name, g, k))
    mapping, used = {}, set()
    for _, g, k in sorted(pairs, reverse=True):
        if g not in mapping and k not in used:
            mapping[g] = k
            used.add(k)
    return mapping


def differences(db: sqlite3.Connection, p: Passage, got: Answer, key: Answer) -> list[str]:
    mapping = match_new(got, key)
    m = lambda e: mapping.get(e, e)
    label = lambda e: e if e.startswith("+") else f"{e} {db.execute('select name from entity where id = ?', (int(e[1:]),)).fetchone()[0]}"
    got_mentions = {(a, b, m(e), k) for a, b, e, k in got.mentions}
    lines = [f"missed {'M' if k == 1 else 'A'} {span_text(p, a, b)} {label(e)}" for a, b, e, k in sorted(key.mentions - got_mentions)]
    lines += [f"extra  {'M' if k == 1 else 'A'} {span_text(p, a, b)} {label(e)}" for a, b, e, k in sorted(got_mentions - key.mentions)]
    return lines + got.errors


def apply(db: sqlite3.Connection, p: Passage, answer: Answer):
    if answer.errors:
        sys.exit("fix these lines first:\n" + "\n".join(answer.errors))
    ids = sorted(p.ids)
    low, high = ids[0], ids[-1]
    owned = f"between {low} and {high}"
    new = {}

    def eid(ref: str) -> int:
        return new[ref] if ref.startswith("+") else int(ref[1:])

    with db:
        db.execute("pragma foreign_keys = on")
        for ref, (t, name, description) in answer.entities.items():
            if ref.startswith("+"):
                new[ref] = db.execute("insert into entity (entity_type_id, name, description) values (?, ?, ?)", (t, name, description)).lastrowid
            else:
                db.execute("update entity set entity_type_id = ?, name = ?, description = ? where id = ?", (t, name, description, eid(ref)))
        for ref, name in answer.removed_names:
            db.execute("delete from entity_name where entity_id = ? and name = ?", (eid(ref), name))
        for ref, name, title in answer.names:
            db.execute("insert into entity_name (entity_id, name, is_title) values (?, ?, ?) on conflict do update set is_title = excluded.is_title", (eid(ref), name, title))
        db.execute(f"delete from mention where first_word_id {owned}")
        db.executemany("insert into mention (entity_id, mention_kind_id, first_word_id, last_word_id) values (?, ?, ?, ?)", [(eid(e), k, a, b) for a, b, e, k in answer.mentions])
        touched = {r for r, in db.execute(f"select distinct relationship_id from relationship_evidence where first_word_id {owned}")}
        db.execute(f"delete from relationship_evidence where first_word_id {owned}")
        for (s, k, o), spans in answer.relationships.items():
            s, o = eid(s), eid(o)
            row = db.execute("select id from relationship where relationship_kind_id = ? and min(subject_id, object_id) = ? and max(subject_id, object_id) = ? and (subject_id = ? or ? in (select id from relationship_kind where two_way = 1))", (k, min(s, o), max(s, o), s, k)).fetchone()
            rid = row[0] if row else db.execute("insert into relationship (subject_id, relationship_kind_id, object_id) values (?, ?, ?)", (s, k, o)).lastrowid
            db.executemany("insert or ignore into relationship_evidence (relationship_id, first_word_id, last_word_id) values (?, ?, ?)", [(rid, a, b) for a, b in spans])
        for rid in touched:
            if not db.execute("select 1 from relationship_evidence where relationship_id = ?", (rid,)).fetchone():
                db.execute("delete from relationship where id = ?", (rid,))
        db.execute(f"delete from speech where first_word_id {owned}")
        for speaker, mode, listeners, a, b, through in answer.speeches:
            sid = db.execute("insert into speech (speaker_id, through_id, speech_mode_id, first_word_id, last_word_id) values (?, ?, ?, ?, ?)", (eid(speaker), eid(through) if through else None, mode, a, b)).lastrowid
            db.executemany("insert into speech_listener (speech_id, entity_id) values (?, ?)", [(sid, eid(x)) for x in listeners])
        db.execute(f"delete from journey where first_word_id {owned}")
        db.executemany("insert into journey (traveler_id, from_id, to_id, days, first_word_id, last_word_id) values (?, ?, ?, ?, ?, ?)", [(eid(t), eid(f) if f else None, eid(e), d, a, b) for t, f, e, d, a, b in answer.journeys])
        db.execute(f"delete from date where first_word_id {owned} or evidence_first_word_id {owned}")
        for where, system, start, end, evidence in answer.dates:
            span = (None, None) if isinstance(where, str) else where
            db.execute(
                """insert into date (first_word_id, last_word_id, entity_id, counting_system_id, from_year, from_month, from_day, to_year, to_month, to_day, evidence_first_word_id, evidence_last_word_id)
                   values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*span, eid(where) if isinstance(where, str) else None, system, *start, *end, *(evidence or (None, None))),
            )
        problems = db.execute("pragma foreign_key_check").fetchall()
        if problems:
            raise sqlite3.IntegrityError(f"foreign key problems: {problems[:5]}")


def run(runner: str, model: str, effort: str | None, text: str) -> tuple[str, dict, float]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as empty:
        if runner == "codex":
            command = ["codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "-s", "read-only", "-C", empty, "-m", model]
            if effort:
                command += ["-c", f"model_reasoning_effort={effort}"]
            done = subprocess.run(command + ["-"], input=text, capture_output=True, text=True)
            events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
            answer = "\n".join(e["item"]["text"] for e in events if e.get("type") == "item.completed" and e["item"].get("type") == "agent_message")
            usage = next((e["usage"] for e in reversed(events) if e.get("type") == "turn.completed"), {})
        elif runner == "cursor":
            command = ["cursor-agent", "-p", "--model", model, "--output-format", "json", "--trust", "--mode", "ask", "--workspace", empty, text]
            done = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            result = json.loads(done.stdout) if done.stdout.strip().startswith("{") else {}
            answer, usage = result.get("result", ""), result.get("usage", {})
        else:
            sys.exit(f"unknown runner {runner}: use codex or cursor")
    if done.returncode != 0 and not answer:
        sys.exit(f"{runner} failed:\n{done.stderr[-2000:]}")
    return answer, usage, time.monotonic() - started


def claude_usage(transcript: Path) -> dict:
    total, seen, model = defaultdict(int), set(), None
    for line in transcript.read_text().splitlines():
        event = json.loads(line)
        message = event.get("message") or {}
        if event.get("type") != "assistant" or message.get("id") in seen:
            continue
        seen.add(message.get("id"))
        model = message.get("model", model)
        for k, v in (message.get("usage") or {}).items():
            if isinstance(v, int):
                total[k] += v
    return {"model": model, **total}


def key_path(label: str) -> Path:
    return KEYS / (re.sub(r"[^\w]+", "-", label).strip("-").lower() + ".txt")


def record(db, p: Passage, label: str, answer_text: str, usage: dict, seconds: float | None):
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{re.sub(r'[^\w.]+', '-', label)}-{key_path(p.label).stem}"
    (RUNS / f"{name}.txt").write_text(answer_text)
    got = parse(db, p, answer_text)
    row = {"run": name, "passage": p.label, "label": label, "usage": usage, "seconds": seconds and round(seconds, 1)}
    if key_path(p.label).exists():
        key = parse(db, p, key_path(p.label).read_text())
        row["score"] = score(db, p, got, key)
        (RUNS / f"{name}.diff").write_text("\n".join(differences(db, p, got, key)) + "\n")
    else:
        row["unreadable"] = len(got.errors)
    with (RUNS / "results.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row, indent=1))


def main():
    parser = argparse.ArgumentParser(description="Tag passages of scripture.db with AI agents, and benchmark the agents against answer keys.")
    parser.add_argument("--db", type=Path, default=DATABASE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prompt", help="print the prompt for a passage").add_argument("passage")
    c = commands.add_parser("check", help="list unreadable lines in an answer")
    c.add_argument("passage")
    c.add_argument("answer", type=Path)
    c = commands.add_parser("score", help="score an answer against the passage's key")
    c.add_argument("passage")
    c.add_argument("answer", type=Path)
    c = commands.add_parser("run", help="run a Codex or Cursor model on a passage and record its score")
    c.add_argument("passage")
    c.add_argument("runner", choices=["codex", "cursor"])
    c.add_argument("model")
    c.add_argument("--effort")
    c = commands.add_parser("record", help="record a Claude subagent's answer, with usage from its transcript")
    c.add_argument("passage")
    c.add_argument("label")
    c.add_argument("answer", type=Path)
    c.add_argument("transcript", type=Path)
    c = commands.add_parser("apply", help="write an answer into the database")
    c.add_argument("passage")
    c.add_argument("answer", type=Path)
    args = parser.parse_args()

    db = sqlite3.connect(args.db)
    p = passage(db, args.passage)
    if args.command == "prompt":
        print(prompt(db, p), end="")
    elif args.command == "check":
        errors = parse(db, p, args.answer.read_text()).errors
        print("\n".join(errors) or "ok")
        sys.exit(1 if errors else 0)
    elif args.command == "score":
        key = parse(db, p, key_path(p.label).read_text())
        got = parse(db, p, args.answer.read_text())
        print(json.dumps(score(db, p, got, key), indent=1))
        print("\n".join(differences(db, p, got, key)))
    elif args.command == "run":
        answer, usage, seconds = run(args.runner, args.model, args.effort, prompt(db, p))
        record(db, p, f"{args.runner}:{args.model}:{args.effort or 'default'}", answer, usage, seconds)
    elif args.command == "record":
        usage = claude_usage(args.transcript)
        record(db, p, args.label, args.answer.read_text(), usage, None)
    elif args.command == "apply":
        apply(db, p, parse(db, p, args.answer.read_text()))
        print(f"applied {args.answer} to {p.label}")


if __name__ == "__main__":
    main()
