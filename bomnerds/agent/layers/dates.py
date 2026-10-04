"""Dates: the years the text counts, or we estimate, for a passage, an event, or a relationship."""

import json

from ...passages import chapter_span
from ..layer import Layer, Problems, kinds, passage_of, scope_span

INSTRUCTIONS = """
Date what happens in this chapter. A date is a range of years in one counting system, with a month and day when the text gives them.

Systems: since_lehi (years since Lehi left Jerusalem), reign_of_judges (years of the reign of the judges), since_sign (years since the sign of Christ's birth), bc_ad.

- "on" says what the date belongs to. Use one of:
  - a passage inside this chapter, the words that happen in that year. A year covers the events after it, until the text names another year, says that year ended, or the chapter ends.
  - an event, `{ "entity": "id" }`. It must be an event entity from the list.
  - a relationship listed below, `{ "relationship": { "subject": "id", "kind": "child_of", "object": "id" } }`. The date is when it was true.
- "evidence" is the passage in this chapter that states the year. Every date needs it except a BC/AD estimate, which cites no words.
- Where the text gives a year, give two objects with the same "on": the text's own count with its evidence, and a bc_ad estimate with no evidence. Estimate only when you can place the year within about a century. Otherwise leave the estimate out.
- Where the text states a BC/AD year itself, as the Doctrine and Covenants does, give one bc_ad object with its evidence.
- BC/AD counts 1 BC as 0 and 2 BC as -1, so 600 BC is -599. AD years are as written: AD 30 is 30.
- "from" and "to" are whole-number years. A single year takes the same number in both.
- Add from_month and to_month (1 to 12), and from_day and to_day, only when the text states them. Give both ends or neither. A day needs its month.
- Dates the text states in a fixed formula, such as "in the first year of the reign of the judges", are already tagged. Leave them out, but still give the bc_ad estimate for each, with the same "on".
- Give one thing one date in each system.

Answer with one object per date:

{ "on": { "entity": "birth-of-jesus-christ" }, "system": "since_lehi", "from": 600, "to": 600,
  "evidence": { "verse": "1 Nephi 10:4", "quote": "six hundred years from the time that my father left Jerusalem" } }
{ "on": { "entity": "birth-of-jesus-christ" }, "system": "bc_ad", "from": 0, "to": 0 }
{ "on": { "verse": "D&C 20:1" }, "system": "bc_ad", "from": 1830, "from_month": 4, "from_day": 6, "to": 1830, "to_month": 4, "to_day": 6,
  "evidence": { "verse": "D&C 20:1", "quote": "the sixth day of the month which is called April" } }
"""

REQUIRED = ("on", "system", "from", "to")
OPTIONAL = ("from_month", "from_day", "to_month", "to_day", "evidence")
DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

# A tag is (target, system, from year, month, day, to year, month, day, evidence span or None).
# A target is ("passage", first, last), ("entity", id), or ("relationship", subject, kind, object).
COLUMNS = (
    "d.first_word_id, d.last_word_id, d.entity_id, r.subject_id, r.kind_id, r.object_id, d.system_id, "
    "d.from_year, d.from_month, d.from_day, d.to_year, d.to_month, d.to_day, d.evidence_first_word_id, d.evidence_last_word_id"
)


class Dates(Layer):
    name = "dates"
    after = ("relationships",)
    step = 7
    instructions = INSTRUCTIONS

    def seen(self):
        from . import LAYERS

        return super().seen() + (("relationships",) if "relationships" in LAYERS else ())

    def context(self, db, jobs, scope):
        first, last = scope_span(db, scope)
        events = db.execute(
            "select id, name, description from entity where type_id = 'event' "
            "and id in (select entity_id from mention where first_word_id between ? and ?) order by name, id",
            (first, last),
        )
        listed = "\n".join(f"{id} {name}. {description}" for id, name, description in events)
        return super().context(db, jobs, scope) + ("\n\n## Events named in this chapter\n\n" + listed if listed else "")

    def given(self, db, scope):
        return stored(db, *scope_span(db, scope))

    def parse(self, db, scope, answer):
        problems = Problems(db)
        tags = []
        for number, item in enumerate(problems.items(answer), 1):
            problems.at(f"item {number}")
            tag = self.read(db, scope, problems, item)
            if tag:
                tags.append(tag)
        problems.at("")
        problems.unique(tags, lambda tag: self.render(db, tag))
        dated = {}
        for tag in tags:
            other = dated.setdefault((tag[0], tag[1]), tag)
            if other != tag:
                problems.add(f"one thing has two dates in {tag[1]}: {line(self.render(db, other))} and {line(self.render(db, tag))}")
        problems.raise_any()
        return tags

    def read(self, db, scope, problems, item):
        if not problems.fields(item, REQUIRED, OPTIONAL):
            return None
        before = len(problems.messages)
        target = self.target(db, scope, problems, item["on"])
        system = problems.kind(item["system"], kinds(db, "counting_system"), "system")
        years = read_years(problems, item)
        evidence = None
        if "evidence" in item:
            evidence = problems.passage(item["evidence"], within=scope)
        elif system and system != "bc_ad":
            problems.add('"evidence" is required. Only a bc_ad estimate cites no words')
        if len(problems.messages) > before:
            return None
        return (target, system, *years, evidence)

    def target(self, db, scope, problems, on):
        if isinstance(on, dict) and {"entity", "relationship"} & set(on):
            if set(on) == {"entity"}:
                entity = problems.entity(on["entity"], ("event",))
                return ("entity", entity) if entity else None
            if set(on) == {"relationship"}:
                return relationship_target(db, problems, on["relationship"])
            problems.add('"on" takes one of: a passage, { "entity": id }, or { "relationship": { "subject", "kind", "object" } }')
            return None
        span = problems.passage(on, within=scope)
        return ("passage", *span) if span else None

    def render(self, db, tag):
        target, system, from_year, from_month, from_day, to_year, to_month, to_day, evidence = tag
        kind, *rest = target
        if kind == "passage":
            on = passage_of(db, *rest)
        elif kind == "entity":
            on = {"entity": rest[0]}
        else:
            on = {"relationship": dict(zip(("subject", "kind", "object"), rest))}
        answer = {"on": on, "system": system, "from": from_year}
        answer.update({k: v for k, v in (("from_month", from_month), ("from_day", from_day)) if v is not None})
        answer["to"] = to_year
        answer.update({k: v for k, v in (("to_month", to_month), ("to_day", to_day)) if v is not None})
        if evidence:
            answer["evidence"] = passage_of(db, *evidence)
        return answer

    def store(self, db, scope, tags):
        db.executemany(
            "insert into date (first_word_id, last_word_id, entity_id, relationship_id, system_id, from_year, from_month, from_day, "
            "to_year, to_month, to_day, evidence_first_word_id, evidence_last_word_id) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [row_values(db, tag, required=True) for tag in tags],
        )

    def unstore(self, db, scope, tags):
        """Deletes one row per tag, so a date two chapters both settled stays for the other."""
        for tag in tags:
            values = row_values(db, tag, required=False)
            if values:
                db.execute(
                    "delete from date where id = (select id from date where first_word_id is ? and last_word_id is ? and entity_id is ? "
                    "and relationship_id is ? and system_id = ? and from_year = ? and from_month is ? and from_day is ? and to_year = ? "
                    "and to_month is ? and to_day is ? and evidence_first_word_id is ? and evidence_last_word_id is ? limit 1)",
                    values,
                )

    def shown(self, db, edition, book_id, chapter):
        return [self.render(db, tag) for tag in stored(db, *chapter_span(db, edition, book_id, chapter))]


def read_years(problems, item) -> list[int | None]:
    """from year, month, day, then to year, month, day, checked against the schema and the calendar."""
    years = [whole(problems, item, key, low, high) for key, low, high in (
        ("from", None, None), ("from_month", 1, 12), ("from_day", 1, 31), ("to", None, None), ("to_month", 1, 12), ("to_day", 1, 31))]
    from_year, from_month, from_day, to_year, to_month, to_day = years
    for end, month, day in (("from", from_month, from_day), ("to", to_month, to_day)):
        if day is not None and month is None and f"{end}_month" not in item:
            problems.add(f"{end}_day needs {end}_month")
        if month is not None and day is not None and day > DAYS_IN_MONTH[month - 1]:
            problems.add(f"month {month} has no day {day}")
    for name in ("month", "day"):
        if (f"from_{name}" in item) != (f"to_{name}" in item):
            problems.add(f"give from_{name} and to_{name} together, or neither")
    if from_year is not None and to_year is not None and (to_year, to_month or 0, to_day or 0) < (from_year, from_month or 0, from_day or 0):
        problems.add('the date runs backward: "to" comes before "from"')
    return years


def whole(problems, item, key, low, high) -> int | None:
    """An integer field in its range, or None when it is absent or wrong."""
    if key not in item:
        return None
    value = item[key]
    if not isinstance(value, int) or isinstance(value, bool):
        problems.add(f'"{key}" must be a whole number, not {json.dumps(value)}')
    elif low is not None and not low <= value <= high:
        problems.add(f'"{key}" must be {low} to {high}, not {value}')
    else:
        return value
    return None


def relationship_target(db, problems, value):
    """A relationship already stored, as its subject, kind, and object in the direction it is stored."""
    if not isinstance(value, dict):
        problems.add('"relationship" takes { "subject": id, "kind": kind, "object": id }')
        return None
    if not problems.fields(value, ("subject", "kind", "object")):
        return None
    kind = problems.kind(value["kind"], kinds(db, "relationship_kind"), "relationship kind")
    subject, other = value["subject"], value["object"]
    if not isinstance(subject, str) or not isinstance(other, str):
        problems.add("subject and object must be entity ids")
        return None
    if not kind:
        return None
    found = db.execute(
        "select subject_id, object_id from relationship where kind_id = ? and ((subject_id = ? and object_id = ?) or (subject_id = ? and object_id = ?))",
        (kind, subject, other, other, subject),
    ).fetchone()
    if found is None:
        problems.add(f"no relationship {subject} {kind} {other} is stored. Only a relationship already stored can take a date")
        return None
    two_way = db.execute("select two_way from relationship_kind where id = ?", (kind,)).fetchone()[0]
    if found != (subject, other) and not two_way:
        problems.add(f"the stored relationship runs the other way: {found[0]} {kind} {found[1]}")
        return None
    return ("relationship", found[0], kind, found[1])


def row_values(db, tag, required: bool):
    """The date columns a tag fills, or None when `required` is false and its relationship is gone."""
    target, system, *when, evidence = tag
    kind, *rest = target
    first, last, entity, relationship = None, None, None, None
    if kind == "passage":
        first, last = rest
    elif kind == "entity":
        entity = rest[0]
    else:
        row = db.execute("select id from relationship where subject_id = ? and kind_id = ? and object_id = ?", rest).fetchone()
        if row is None:
            if required:
                raise ValueError(f"no relationship {' '.join(rest)} is stored to date")
            return None
        relationship = row[0]
    return (first, last, entity, relationship, system, *when, *(evidence or (None, None)))


def stored(db, first: int, last: int) -> list:
    """Every stored date on or backed by words first through last, and on an event named or a relationship cited there."""
    rows = db.execute(
        f"select {COLUMNS} from date d left join relationship r on r.id = d.relationship_id "
        "where (d.first_word_id <= :last and d.last_word_id >= :first) "
        "or (d.evidence_first_word_id <= :last and d.evidence_last_word_id >= :first) "
        "or d.entity_id in (select entity_id from mention where first_word_id between :first and :last) "
        "or d.relationship_id in (select relationship_id from relationship_evidence where first_word_id between :first and :last) "
        "order by coalesce(d.first_word_id, d.evidence_first_word_id, 0), d.id",
        {"first": first, "last": last},
    )
    return [row_tag(row) for row in rows]


def row_tag(row) -> tuple:
    first, last, entity, subject, kind, other, system, *when, evidence_first, evidence_last = row
    if first is not None:
        target = ("passage", first, last)
    elif entity is not None:
        target = ("entity", entity)
    else:
        target = ("relationship", subject, kind, other)
    return (target, system, *when, None if evidence_first is None else (evidence_first, evidence_last))


def line(answer: dict) -> str:
    return json.dumps(answer, ensure_ascii=False)


LAYERS = [Dates()]
