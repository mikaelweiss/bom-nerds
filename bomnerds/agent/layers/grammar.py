"""Grammar: every English sentence's clauses and each clause's parts, completed around the ones two parsers agree on."""

import json
import sqlite3
from collections import defaultdict

from ...passages import chapter_span, english_edition
from ..jobs import Job, read
from ..layer import Layer, Problems, kinds, passage_of, scope_span, split_chapter

INSTRUCTIONS = """
Complete the grammar of every sentence in this chapter: its clauses, and each clause's parts.

A clause is a group of words built around one verb. Clauses can hold clauses. Each part of a clause has one role:

- subject: who or what the clause is about, or who does the verb: "I, Nephi".
- verb: the verb with its auxiliaries and any "not" between them: "hath commanded", "shalt not kill". Leave out "to": in "to behold", the verb is "behold".
- object: who or what the verb acts on. A person commanded or told is the object: in "the Lord hath commanded me", "me" is the object. What is said or commanded is an object too, so "commanded me that ye should go" has two objects.
- indirect_object: the one something is given or said to: "unto my father".
- complement: what the subject or object is or becomes: "a man", "exceedingly young", "Nephi" in "called his name Nephi".
- adverbial: when, where, how, or why: "into the wilderness", "in the first year".

Rules:

- The sentences are already split. Each ends at a period, question mark, or exclamation mark, never at a colon, semicolon, or dash. Answer every sentence listed under "Sentences and their fixed clauses", once each, and add none.
- Start from that list. Its clauses, subjects, and verbs are fixed: keep each one with the same words and role, and add the clauses and parts that are missing. Move a fixed clause inside a clause you add when its words sit inside it.
- A colon usually opens a speech, as in "said unto my father: I will go". The speech stays inside its sentence as the object of the verb, and it is a clause of its own inside the clause of "said".
- A clause joined to another by "and" or "but" stands beside it, not inside it, and starts after the "and". A clause takes in a word that opens it, such as "that", "which", "when", "for", "if", or "because".
- Words that join clauses, such as "and", "but", "that", "when", "for", and "because", belong to no part. So do "behold" and "yea". A part that is a clause leaves out the word that joins it: in "I swear unto you, that ye shall prosper", the object is "ye shall prosper".
- A word such as "who", "which", or "whom" that stands for a person or thing takes the role it plays in its own clause: in "which my father saw", "which" is the object.
- A "to" verb or an "-ing" verb with its own words is a clause too: "to behold the things", "saying: Look!".
- A part takes its whole phrase, including any clause inside it. Parts of one clause never share words, and a clause has at most one verb part.
- When the subject splits a verb from its auxiliary, as in "shalt thou not kill", the verb part is the run that ends at the main verb: "not kill".
- Write each clause inside the smallest clause that holds it, under that clause's "clauses". Clauses side by side never share words.

Answer with one object per sentence. Each clause has a passage and one or more parts, and lists the clauses directly inside it under "clauses":

{ "sentence": { "verse": "1 Nephi 11:3" }, "clauses": [
  { "passage": { "verse": "1 Nephi 11:3", "quote": "I said: I desire to behold the things which my father saw" }, "parts": [
    { "role": "subject", "passage": { "verse": "1 Nephi 11:3", "quote": "I", "in": "I said" } },
    { "role": "verb", "passage": { "verse": "1 Nephi 11:3", "quote": "said" } },
    { "role": "object", "passage": { "verse": "1 Nephi 11:3", "quote": "I desire to behold the things which my father saw" } }
  ], "clauses": [
    { "passage": { "verse": "1 Nephi 11:3", "quote": "I desire to behold the things which my father saw" }, "parts": [
      { "role": "subject", "passage": { "verse": "1 Nephi 11:3", "quote": "I", "in": "I desire" } },
      { "role": "verb", "passage": { "verse": "1 Nephi 11:3", "quote": "desire" } },
      { "role": "object", "passage": { "verse": "1 Nephi 11:3", "quote": "to behold the things which my father saw" } }
    ], "clauses": [
      { "passage": { "verse": "1 Nephi 11:3", "quote": "to behold the things which my father saw" }, "parts": [
        { "role": "verb", "passage": { "verse": "1 Nephi 11:3", "quote": "behold" } },
        { "role": "object", "passage": { "verse": "1 Nephi 11:3", "quote": "the things which my father saw" } }
      ], "clauses": [
        { "passage": { "verse": "1 Nephi 11:3", "quote": "which my father saw" }, "parts": [
          { "role": "object", "passage": { "verse": "1 Nephi 11:3", "quote": "which" } },
          { "role": "subject", "passage": { "verse": "1 Nephi 11:3", "quote": "my father" } },
          { "role": "verb", "passage": { "verse": "1 Nephi 11:3", "quote": "saw" } }
        ] }
      ] }
    ] }
  ] }
] }
"""

# The dataset records no provenance, so store keeps the parser-agreed rows it found in the job folder, and unstore removes everything else.
AGREED = "agreed"

# A clause is (first, last, parts, clauses): parts are (first, last, role) and clauses the clauses directly inside it, both in reading order.
# A tag is one sentence: (first, last, clauses).


class Grammar(Layer):
    name = "grammar"
    step = 7
    sees = ()
    instructions = INSTRUCTIONS

    def ready(self, db, jobs, scope):
        earlier = super().ready(db, jobs, scope)
        if earlier:
            return earlier
        if db.execute("select 1 from sentence where first_word_id between ? and ? limit 1", scope_span(db, scope)).fetchone() is None:
            return "the chapter has no sentences yet. Run the scripts first: python3 -m bomnerds.build sentences taggers grammar"
        return None

    def context(self, db, jobs, scope):
        book, chapter = split_chapter(scope)
        sentences = "\n".join(json.dumps(s, ensure_ascii=False) for s in self.shown(db, english_edition(db, book), book, chapter))
        return (
            super().context(db, jobs, scope)
            + "\n\n## Sentences and their fixed clauses\n\n"
            + "Every sentence of the chapter, one per line, with the clauses, subjects, and verbs two parsers agree on. "
            + "All of them are fixed: copy each line into your answer, keep everything in it, and complete it.\n\n"
            + sentences
        )

    def parse(self, db, scope, answer):
        problems = Problems(db)
        roles = kinds(db, "clause_role")
        stored = {(first, last): clauses for first, last, clauses in sentence_trees(db, *scope_span(db, scope))}
        tags, answered, resolved = [], {}, True
        for number, item in enumerate(problems.items(answer), 1):
            where = f"item {number}"
            problems.at(where)
            if not problems.fields(item, ("sentence", "clauses")):
                resolved = False
                continue
            span = problems.passage(item["sentence"], within=scope)
            if span is None or span not in stored:
                if span is not None:
                    problems.add(not_a_sentence(db, span, stored))
                resolved = False
                continue
            if span in answered:
                problems.add(f"this sentence is item {answered[span]} too. Answer each sentence once")
                continue
            answered[span] = number
            clauses = read_clauses(problems, item["clauses"], span, where, roles)
            if clauses is not None and keeps_fixed(db, problems.at(where), stored[span], clauses):
                tags.append((*span, clauses))
        if resolved:
            problems.at("")
            for span in stored:
                if span not in answered:
                    problems.add(f"the sentence {line(passage_of(db, *span))} is missing. Answer every sentence of the chapter")
        problems.raise_any()
        return tags

    def render(self, db, tag):
        first, last, clauses = tag
        return {"sentence": passage_of(db, first, last), "clauses": [render_clause(db, c) for c in clauses]}

    def store(self, db, scope, tags):
        job = Job(self, scope)
        if read(job.path / f"{AGREED}.json") is None:
            job.write(AGREED, sentence_trees(db, *scope_span(db, scope)))
        for first, last, clauses in tags:
            sentence = db.execute("select id from sentence where first_word_id = ? and last_word_id = ?", (first, last)).fetchone()[0]
            rows = clause_rows(db, sentence)
            for (start, end), parent, parts in walk(clauses):
                parent_id = rows[parent] if parent else None
                if (start, end) in rows:
                    db.execute("update clause set parent_id = ? where id = ?", (parent_id, rows[(start, end)]))
                else:
                    rows[(start, end)] = db.execute(
                        "insert into clause (sentence_id, parent_id, first_word_id, last_word_id) values (?, ?, ?, ?)", (sentence, parent_id, start, end)
                    ).lastrowid
                clause = rows[(start, end)]
                have = set(db.execute("select first_word_id, last_word_id, role_id from clause_part where clause_id = ?", (clause,)))
                db.executemany(
                    "insert into clause_part (clause_id, role_id, first_word_id, last_word_id) values (?, ?, ?, ?)",
                    [(clause, role, a, b) for a, b, role in parts if (a, b, role) not in have],
                )

    def unstore(self, db, scope, tags):
        agreed = {(first, last): clauses for first, last, clauses in frozen(read(Job(self, scope).path / f"{AGREED}.json") or [])}
        for first, last, clauses in tags:
            sentence = db.execute("select id from sentence where first_word_id = ? and last_word_id = ?", (first, last)).fetchone()
            if sentence is None:
                continue
            rows = clause_rows(db, sentence[0])
            kept = {span: (parent, parts) for span, parent, parts in walk(agreed.get((first, last), ()))}
            for span, (parent, _) in kept.items():
                if span in rows:
                    db.execute("update clause set parent_id = ? where id = ?", (rows.get(parent), rows[span]))
            for span, _, parts in reversed(list(walk(clauses))):
                if span not in rows:
                    continue
                keep = kept[span][1] if span in kept else set()
                db.executemany(
                    "delete from clause_part where clause_id = ? and role_id = ? and first_word_id = ? and last_word_id = ?",
                    [(rows[span], role, a, b) for a, b, role in parts if (a, b, role) not in keep],
                )
                if span not in kept:
                    db.execute("delete from clause where id = ?", (rows[span],))

    def shown(self, db, edition, book_id, chapter):
        return [self.render(db, tag) for tag in sentence_trees(db, *chapter_span(db, edition, book_id, chapter))]


def sentence_trees(db: sqlite3.Connection, first: int, last: int) -> list[tuple]:
    """Every stored sentence starting between the two words, with its clauses nested by parent, as tags."""
    within = "select id from sentence where first_word_id between ? and ?"
    parts = defaultdict(list)
    for clause, a, b, role in db.execute(
        f"select clause_id, first_word_id, last_word_id, role_id from clause_part where clause_id in (select id from clause where sentence_id in ({within}))", (first, last)
    ):
        parts[clause].append((a, b, role))
    children = defaultdict(list)
    for id, sentence, parent, a, b in db.execute(f"select id, sentence_id, parent_id, first_word_id, last_word_id from clause where sentence_id in ({within})", (first, last)):
        children[("clause", parent) if parent else ("sentence", sentence)].append((id, a, b))

    def build(key):
        found = [(a, b, tuple(sorted(parts[id])), build(("clause", id))) for id, a, b in children[key]]
        return tuple(sorted(found, key=reading_order))

    return [(a, b, build(("sentence", id))) for id, a, b in db.execute(f"select id, first_word_id, last_word_id from sentence where id in ({within}) order by first_word_id", (first, last))]


def reading_order(clause: tuple) -> tuple[int, int]:
    return clause[0], -clause[1]


def read_clauses(problems: Problems, items, outer: tuple[int, int], where: str, roles: list[str], path: str = "") -> tuple | None:
    """The clauses of a sentence or clause as tuples in reading order, or None after adding every problem found."""
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        problems.at(where).add('"clauses" must be a list of clause objects')
        return None
    found, clean = [], True
    for number, item in enumerate(items, 1):
        label = f"{where.split(',')[0]}, clause {path}{number}"
        problems.at(label)
        if not problems.fields(item, ("passage", "parts"), ("clauses",)):
            clean = False
            continue
        span = problems.passage(item["passage"])
        if span is None:
            clean = False
            continue
        if not inside(span, outer):
            problems.add(f"the clause must sit inside its {'parent clause' if path else 'sentence'}")
            clean = False
            continue
        if path and span == outer:
            problems.add("the clause covers the same words as its parent clause. A clause inside another is shorter than it")
            clean = False
            continue
        parts = read_parts(problems, item["parts"], span, label, roles)
        clauses = read_clauses(problems, item.get("clauses", []), span, label, roles, f"{path}{number}.")
        if parts is None or clauses is None:
            clean = False
            continue
        found.append((*span, parts, clauses))
    found.sort(key=reading_order)
    reach = None
    for clause in found:
        if reach and clause[0] <= reach[1]:
            problems.at(where).add(
                f"the clauses {line(passage_of(problems.db, *reach[:2]))} and {line(passage_of(problems.db, *clause[:2]))} share words. "
                'Write a clause inside another under that clause\'s "clauses". Clauses side by side never share words'
            )
            clean = False
        if reach is None or clause[1] > reach[1]:
            reach = clause
    return tuple(found) if clean else None


def read_parts(problems: Problems, items, clause: tuple[int, int], where: str, roles: list[str]) -> tuple | None:
    if not isinstance(items, list) or not items or not all(isinstance(item, dict) for item in items):
        problems.at(where).add('"parts" must be a list of one or more part objects')
        return None
    found, clean = [], True
    for number, item in enumerate(items, 1):
        problems.at(f"{where}, part {number}")
        if not problems.fields(item, ("role", "passage")):
            clean = False
            continue
        role = problems.kind(item["role"], roles, "role")
        span = problems.passage(item["passage"])
        if span and not inside(span, clause):
            problems.add("the part must sit inside its clause")
            span = None
        if role is None or span is None:
            clean = False
            continue
        found.append((*span, role))
    found.sort()
    problems.at(where)
    for before, after in zip(found, found[1:]):
        if after[0] <= before[1]:
            problems.add(f"the parts {line(passage_of(problems.db, *before[:2]))} and {line(passage_of(problems.db, *after[:2]))} share words. Parts of one clause never overlap")
            clean = False
    verbs = sum(1 for part in found if part[2] == "verb")
    if verbs > 1:
        problems.add(f'the clause has {verbs} verb parts, but a clause has one. A verb joined by "and" with words of its own heads a clause of its own')
        clean = False
    return tuple(found) if clean else None


def keeps_fixed(db: sqlite3.Connection, problems: Problems, fixed: tuple, clauses: tuple) -> bool:
    """Whether the answer keeps every stored clause of the sentence, each with its stored parts."""
    answered = {span: parts for span, _, parts in walk(clauses)}
    clean = True
    for span, _, parts in walk(fixed):
        if span not in answered:
            problems.add(f"the fixed clause {line(passage_of(db, *span))} is missing. Keep every fixed clause")
            clean = False
            continue
        for a, b, role in sorted(parts - answered[span]):
            problems.add(f"the fixed {role} {line(passage_of(db, a, b))} of the clause {line(passage_of(db, *span))} is missing. Keep every fixed part in its clause")
            clean = False
    return clean


def walk(clauses: tuple, parent: tuple[int, int] | None = None):
    """Each clause as ((first, last), parent span, set of parts), parents before the clauses inside them."""
    for first, last, parts, inner in clauses:
        yield (first, last), parent, set(parts)
        yield from walk(inner, (first, last))


def clause_rows(db: sqlite3.Connection, sentence: int) -> dict[tuple[int, int], int]:
    return {(a, b): id for id, a, b in db.execute("select id, first_word_id, last_word_id from clause where sentence_id = ?", (sentence,))}


def frozen(value):
    """JSON lists read back as the tuples they were written from."""
    return tuple(frozen(v) for v in value) if isinstance(value, list) else value


def inside(span: tuple[int, int], outer: tuple[int, int]) -> bool:
    return outer[0] <= span[0] and span[1] <= outer[1]


def not_a_sentence(db: sqlite3.Connection, span: tuple[int, int], stored) -> str:
    holding = next((s for s in stored if s[0] <= span[0] <= s[1]), None)
    if holding is None:
        return "this is not a sentence of the chapter"
    return f"this is not a whole sentence. The sentence holding its first word is {line(passage_of(db, *holding))}"


def render_clause(db: sqlite3.Connection, clause: tuple) -> dict:
    first, last, parts, inner = clause
    rendered = {"passage": passage_of(db, first, last), "parts": [{"role": role, "passage": passage_of(db, a, b)} for a, b, role in parts]}
    if inner:
        rendered["clauses"] = [render_clause(db, c) for c in inner]
    return rendered


def line(value) -> str:
    return json.dumps(value, ensure_ascii=False)


LAYERS = [Grammar()]
