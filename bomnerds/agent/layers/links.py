"""Passage links the AI finds: allusions, fulfillments, and cross-references between works."""

import json

from ...passages import chapter_span
from ..layer import Layer, Problems, in_chapter, kinds, passage_of, scope_span, chapter_name

WRITTEN = ("alludes_to", "fulfills", "cross_reference")

INSTRUCTIONS = """
Link passages of each chapter to passages elsewhere in scripture. Write only these kinds:

- alludes_to: the words echo another passage without quoting it closely.
- fulfills: this passage tells the fulfillment of a prophecy or promise made at the other passage.
- cross_reference: the two passages treat the same event, person, or teaching, and they are in different works (Bible, Book of Mormon, Doctrine and Covenants, Pearl of Great Price).

- "from" sits in the chapter of its section. "to" can be anywhere. Outside this prompt's chapters, point "to" at whole verses unless you know the words exactly. When a quote misses, submit shows the verse's real text.
- Link a verse, a run of verses, or the words that carry the connection. Use a whole chapter only when the whole chapter is the connection.
- Link only what a careful reader would call a clear connection. Leave loose similarity out.
- A cross-reference runs both ways, so one object covers it. Do not write it twice.
- The script already links passages that follow the Bible closely (quotes and parallel) and every Bible cross-reference within the Bible. Do not repeat them as other kinds.
  The Bible cross-references are too many to list here, so each chapter shows only how many it has. Submit refuses a link already stored.

Answer with one object per link:

{ "kind": "fulfills", "from": { "verse": "Matthew 1:23" }, "to": { "verse": "Isaiah 7:14" } }
"""


class Links(Layer):
    name = "links"
    step = 7
    entities = False
    instructions = INSTRUCTIONS

    def extra(self, db, jobs, scope, batch=()):
        _, bulk = split_links(db, *scope_span(db, scope))
        return "## Cross-references the script stored\n\n" + json.dumps(bulk_line(db, scope, bulk), ensure_ascii=False) if bulk else ""

    def given(self, db, scope):
        return split_links(db, *scope_span(db, scope))[0]

    def parse(self, db, scope, answer):
        problems = Problems(db)
        two_way = {kind: bool(flag) for kind, flag in db.execute("select id, two_way from link_kind")}
        allowed = [kind for kind in kinds(db, "link_kind") if kind in WRITTEN]
        tags = []
        for number, item in enumerate(problems.items(answer), 1):
            problems.at(f"item {number}")
            if not problems.fields(item, ("kind", "from", "to")):
                continue
            kind = problems.kind(item["kind"], allowed)
            start = problems.at(f"item {number} from").passage(item["from"])
            end = problems.at(f"item {number} to").passage(item["to"])
            problems.at(f"item {number}")
            if not (kind and start and end):
                continue
            if not self.sits_right(db, scope, problems, two_way[kind], start, end, kind):
                continue
            if two_way[kind] and start > end:
                start, end = end, start
            tags.append((kind, *start, *end))
        problems.at("")
        problems.unique(tags, lambda tag: self.render(db, tag))
        problems.raise_any()
        return tags

    def sits_right(self, db, scope, problems, two_way, start, end, kind) -> bool:
        """Whether the ends sit where the kind allows, adding a problem for each way they do not."""
        before = len(problems.messages)
        sits = [in_chapter(db, scope, *span) for span in (start, end)]
        if not any(sits) if two_way else not sits[0]:
            where = "an end" if two_way else '"from"'
            problems.add(f"{where} must sit inside {chapter_name(db, scope)}")
        if start[0] <= end[1] and end[0] <= start[1]:
            problems.add('"from" and "to" overlap. A passage cannot link to itself')
        if kind == "cross_reference" and work_of(db, start[0]) == work_of(db, end[0]):
            problems.add(
                f"a cross-reference joins two works, but both passages are in the {work_name(db, work_of(db, start[0]))}. "
                "For a link inside one work use alludes_to or fulfills, or leave it out"
            )
        return len(problems.messages) == before

    def render(self, db, tag):
        kind, from_first, from_last, to_first, to_last = tag
        return {"kind": kind, "from": passage_of(db, from_first, from_last), "to": passage_of(db, to_first, to_last)}

    def store(self, db, scope, tags):
        db.executemany(
            "insert or ignore into passage_link (kind_id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id) values (?, ?, ?, ?, ?)", tags
        )

    def unstore(self, db, scope, tags):
        db.executemany(
            "delete from passage_link where kind_id = ? and from_first_word_id = ? and from_last_word_id = ? and to_first_word_id = ? and to_last_word_id = ?", tags
        )

    def shown(self, db, edition, book_id, chapter):
        listed, bulk = split_links(db, *chapter_span(db, edition, book_id, chapter))
        lines = [self.render(db, tag) for tag in listed]
        if bulk:
            lines.append(bulk_line(db, f"{book_id}/{chapter}", bulk))
        return lines


def split_links(db, first: int, last: int) -> tuple[list[tuple], int]:
    """The links with an end in words first through last that an agent can read, and how many Bible cross-references there are besides."""
    listed, bulk = [], 0
    for tag, same_work in touching(db, first, last):
        if tag[0] == "cross_reference" and same_work:
            bulk += 1
        else:
            listed.append(tag)
    return listed, bulk


def touching(db, first: int, last: int) -> list[tuple[tuple, bool]]:
    """Each link with an end in words first through last as a tag, with whether both its ends are in one work."""
    rows = db.execute(
        "select l.kind_id, l.from_first_word_id, l.from_last_word_id, l.to_first_word_id, l.to_last_word_id, a.work_id = b.work_id "
        "from passage_link l "
        "join word wf on wf.id = l.from_first_word_id join edition a on a.id = wf.edition_id "
        "join word wt on wt.id = l.to_first_word_id join edition b on b.id = wt.edition_id "
        "where l.id in ("
        "select id from passage_link where from_first_word_id <= :last and from_last_word_id >= :first "
        "union select id from passage_link where to_first_word_id <= :last and to_last_word_id >= :first) "
        "order by min(l.from_first_word_id, l.to_first_word_id), l.id",
        {"first": first, "last": last},
    )
    return [(tuple(row[:5]), bool(row[5])) for row in rows]


def bulk_line(db, scope: str, count: int) -> dict:
    return {"kind": "cross_reference", "count": count}


def work_of(db, word_id: int) -> str:
    return db.execute("select e.work_id from word w join edition e on e.id = w.edition_id where w.id = ?", (word_id,)).fetchone()[0]


def work_name(db, work_id: str) -> str:
    return db.execute("select name from work where id = ?", (work_id,)).fetchone()[0]


LAYERS = [Links()]
