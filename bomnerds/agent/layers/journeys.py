"""Journeys: someone traveling from one place to another, citing the words that tell it."""

import math

from ...passages import chapter_span
from ..layer import Layer, Problems, passage_of, where

TRAVELERS = ("person", "group")
PLACES = ("place",)

INSTRUCTIONS = """
Tag every journey in each chapter: someone traveling from one place to another.

- The traveler is a person or group. Places are entities of type place or one of its subtypes, such as city, land, water, mountain, or wilderness.
- Every journey needs a destination, "to". Leave "from" out when the text does not name the starting place.
- Give "days" only when the text gives the days of this travel, as a positive number. Leave it out otherwise.
- The passage is the words that tell the journey, not the whole verse.
- Each trip is its own journey. Alma traveling to Gideon twice is two journeys, each with its own passage.
- Leave out moving about inside one place and trips whose destination the text does not name.

Answer with one object per journey:

{ "traveler": "family-of-lehi", "to": "valley-of-lemuel", "days": 3,
  "passage": { "verse": "1 Nephi 2:6", "quote": "when he had traveled three days in the wilderness" } }
"""


class Journeys(Layer):
    name = "journeys"
    step = 7
    instructions = INSTRUCTIONS

    def parse(self, db, scope, answer):
        problems = Problems(db)
        tags = []
        for number, item in enumerate(problems.items(answer), 1):
            problems.at(where(number, item))
            if not problems.fields(item, ("traveler", "to", "passage"), ("from", "days")):
                continue
            before = len(problems.messages)
            traveler = problems.entity(item["traveler"], TRAVELERS)
            origin = item.get("from")
            if origin is not None:
                origin = problems.entity(origin, PLACES)
            destination = problems.entity(item["to"], PLACES)
            days = days_of(problems, item.get("days"))
            span = problems.passage(item["passage"], within=scope)
            if destination and origin == destination:
                problems.add(f"from and to are both {destination}. A journey goes between two different places")
            if len(problems.messages) == before:
                tags.append((traveler, origin, destination, days, *span))
        problems.unique(tags, lambda tag: self.render(db, tag))
        problems.raise_any()
        return tags

    def render(self, db, tag):
        traveler, origin, destination, days, first, last = tag
        answer = {"traveler": traveler}
        if origin is not None:
            answer["from"] = origin
        answer["to"] = destination
        if days is not None:
            answer["days"] = int(days) if days.is_integer() else days
        answer["passage"] = passage_of(db, first, last)
        return answer

    def store(self, db, scope, tags):
        db.executemany("insert into journey (traveler_id, from_id, to_id, days, first_word_id, last_word_id) values (?, ?, ?, ?, ?, ?)", tags)

    def unstore(self, db, scope, tags):
        db.executemany(
            "delete from journey where traveler_id = ? and from_id is ? and to_id = ? and days is ? and first_word_id = ? and last_word_id = ?", tags
        )

    def shown(self, db, edition, book_id, chapter):
        first, last = chapter_span(db, edition, book_id, chapter)
        rows = db.execute(
            "select traveler_id, from_id, to_id, days, first_word_id, last_word_id from journey where first_word_id >= ? and last_word_id <= ? order by first_word_id, last_word_id, id",
            (first, last),
        )
        return [self.render(db, tag) for tag in rows]


def days_of(problems: Problems, value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        problems.add("days must be a positive number, or left out when the text does not give it")
        return None
    return float(value)


LAYERS = [Journeys()]
