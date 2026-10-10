"""Write one annotation packet per chapter of the KJV, Book of Mormon, Doctrine and Covenants, and Pearl of Great Price, for the settings pass.

    python scripts/export_setting_packets.py scripture.db <packet directory>

Each packet lists the chapter's verses with their first and last word ids and the places tagged in each verse, the last verses of the chapter before,
the places named in both with what contains them, the journeys and events in the chapter, and the chapter's word count.
The directory also gets index.tsv, the chapters in reading order with their sizes, and places.tsv, every place to search when a chapter does not name its own.
"""

import os
import re
import sqlite3
import sys
from bisect import bisect_right
from collections import defaultdict

EDITIONS = (1, 4, 5, 6)
CONTEXT_WORDS = 60
CONTEXT_VERSES = 3
DESCRIPTION_LENGTH = 90


def short(text, length=DESCRIPTION_LENGTH):
    return text if len(text) <= length else text[: length - 3].rstrip() + "..."


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class Library:
    def __init__(self, db):
        self.chapters = db.execute(
            "select c.id, c.edition_id, b.name, c.number from chapter c join book b on b.id = c.book_id "
            "join edition_book eb on eb.edition_id = c.edition_id and eb.book_id = c.book_id "
            f"where c.edition_id in {EDITIONS} "
            "order by case c.edition_id when 1 then 1 when 4 then 2 when 5 then 3 else 4 end, eb.position, c.number"
        ).fetchall()

        self.verses = defaultdict(list)
        self.verse_rows = []
        for verse, chapter, number, first, last in db.execute(
            "select v.id, v.chapter_id, v.number, min(w.id), max(w.id) from verse v join word w on w.verse_id = v.id "
            f"join chapter c on c.id = v.chapter_id where c.edition_id in {EDITIONS} group by v.id order by min(w.sequence)"
        ):
            row = {"id": verse, "chapter": chapter, "number": number, "first": first, "last": last, "text": [], "places": []}
            self.verses[chapter].append(row)
            self.verse_rows.append(row)
        self.verse_rows.sort(key=lambda row: row["first"])
        self.verse_starts = [row["first"] for row in self.verse_rows]
        by_id = {row["id"]: row for row in self.verse_rows}

        for verse, before, text, after in db.execute(
            "select w.verse_id, w.before, w.text, w.after from word w join verse v on v.id = w.verse_id "
            f"join chapter c on c.id = v.chapter_id where c.edition_id in {EDITIONS} order by w.sequence"
        ):
            by_id[verse]["text"].append(before + text + after)
        for row in self.verse_rows:
            row["text"] = re.sub(r"\s+", " ", "".join(row["text"])).strip()

        self.places = {
            id: (name, kind, description)
            for id, name, kind, description in db.execute(
                "select x.id, x.name, t.name, x.description from entity x join entity_type t on t.id = x.entity_type_id "
                "left join entity_type p on p.id = t.parent_id where 'Place' in (t.name, p.name)"
            )
        }
        self.names = dict(db.execute("select id, name from entity"))
        self.alternates = defaultdict(list)
        for entity, name in db.execute("select entity_id, name from entity_name order by entity_id, name"):
            if entity in self.places:
                self.alternates[entity].append(name)
        self.container = defaultdict(list)
        for inner, outer in db.execute(
            "select r.subject_id, r.object_id from relationship r join relationship_kind k on k.id = r.relationship_kind_id "
            "where k.name = 'located in'"
        ):
            if outer in self.places:
                self.container[inner].append(outer)
        self.site = defaultdict(list)
        for event, place in db.execute(
            "select r.subject_id, r.object_id from relationship r join relationship_kind k on k.id = r.relationship_kind_id "
            "where k.name = 'took place at'"
        ):
            if place in self.places:
                self.site[event].append(place)

        self.events = defaultdict(set)
        for entity, first in db.execute("select distinct entity_id, first_word_id from mention"):
            row = self.verse_of(first)
            if row is None:
                continue
            if entity in self.places and entity not in row["places"]:
                row["places"].append(entity)
            elif entity in self.site:
                self.events[row["chapter"]].add(entity)

        self.journeys = defaultdict(list)
        for traveler, origin, destination, days, first, last in db.execute(
            "select traveler_id, from_id, to_id, days, first_word_id, last_word_id from journey order by first_word_id"
        ):
            start, end = self.verse_of(first), self.verse_of(last)
            if start is not None and end is not None and start["number"] is not None:
                self.journeys[start["chapter"]].append((traveler, origin, destination, days, start["number"], end["number"]))

    def verse_of(self, word):
        i = bisect_right(self.verse_starts, word) - 1
        if i < 0 or self.verse_rows[i]["last"] < word:
            return None
        return self.verse_rows[i]

    def place_line(self, place):
        name, kind, description = self.places[place]
        line = f"  {place} {name} ({kind}) {short(description)}"
        alternates = self.alternates.get(place, [])
        if alternates:
            line += " | also: " + ", ".join(alternates[:4]) + (", ..." if len(alternates) > 4 else "")
        if self.container.get(place):
            line += " | in: " + ", ".join(f"{self.places[o][0]} {o}" for o in self.container[place])
        return line


def verse_line(row):
    label = "h" if row["number"] is None else str(row["number"])
    places = f" [p {' '.join(map(str, row['places']))}]" if row["places"] else ""
    return f"{label} {row['first']}-{row['last']} {row['text']}{places}"


def context(previous):
    taken, words = [], 0
    for row in reversed(previous):
        if row["number"] is None or len(taken) == CONTEXT_VERSES or (taken and words >= CONTEXT_WORDS):
            break
        taken.append(row)
        words += row["last"] - row["first"] + 1
    return taken[::-1]


def packet(library, chapter, edition, book, number, previous):
    rows = library.verses[chapter]
    before = context(library.verses[previous[0]]) if previous else []
    words = sum(row["last"] - row["first"] + 1 for row in rows)
    numbered = sum(row["number"] is not None for row in rows)
    lines = [f"== {chapter} {book} {number} | edition {edition} | {numbered} verses | {words} words"]
    if before:
        span = f"{before[0]['number']}-{before[-1]['number']}" if len(before) > 1 else str(before[0]["number"])
        lines.append(f"before ({previous[1]} {previous[2]}:{span}):")
        lines += ["  " + verse_line(row) for row in before]
    lines.append("verses:")
    lines += [verse_line(row) for row in rows]

    places = []
    for row in before + rows:
        places += [p for p in row["places"] if p not in places]
    for _, origin, destination, *_ in library.journeys[chapter]:
        places += [p for p in (origin, destination) if p in library.places and p not in places]
    for event in sorted(library.events[chapter]):
        places += [p for p in library.site[event] if p not in places]
    if places:
        lines.append("places:")
        lines += [library.place_line(p) for p in places]

    if library.journeys[chapter]:
        lines.append("journeys:")
        for traveler, origin, destination, days, start, end in library.journeys[chapter]:
            verses = str(start) if start == end else f"{start}-{end}"
            source = f"{library.names[origin]} {origin}" if origin else "?"
            length = f", {days:g} days" if days else ""
            lines.append(
                f"  v{verses} {library.names[traveler]} {traveler}: {source} -> {library.names[destination]} {destination}{length}"
            )

    if library.events[chapter]:
        lines.append("events:")
        for event in sorted(library.events[chapter]):
            sites = ", ".join(f"{library.places[p][0]} {p}" for p in library.site[event])
            lines.append(f"  {event} {library.names[event]} @ {sites}")
    return "\n".join(lines) + "\n", numbered, words


def main(path, directory):
    db = sqlite3.connect(path)
    db.execute("pragma busy_timeout = 60000")
    library = Library(db)
    os.makedirs(directory, exist_ok=True)

    index = ["order\tfile\tchapter_id\tedition_id\treference\tverses\twords\tbytes"]
    previous = None
    total_words = 0
    for order, (chapter, edition, book, number) in enumerate(library.chapters, 1):
        if previous and previous[3] != edition:
            previous = None
        text, verses, words = packet(library, chapter, edition, book, number, previous)
        name = f"{order:04d}-{slug(book)}-{number}.txt"
        with open(os.path.join(directory, name), "w", encoding="utf-8") as out:
            out.write(text)
        index.append(f"{order}\t{name}\t{chapter}\t{edition}\t{book} {number}\t{verses}\t{words}\t{len(text.encode())}")
        total_words += words
        previous = (chapter, book, number, edition)
    with open(os.path.join(directory, "index.tsv"), "w", encoding="utf-8") as out:
        out.write("\n".join(index) + "\n")

    with open(os.path.join(directory, "places.tsv"), "w", encoding="utf-8") as out:
        out.write("id\ttype\tname\talso\tin\tdescription\n")
        for place, (name, kind, description) in sorted(library.places.items(), key=lambda item: item[1][0]):
            inside = ", ".join(f"{library.places[o][0]} {o}" for o in library.container.get(place, []))
            out.write(f"{place}\t{kind}\t{name}\t{'; '.join(library.alternates.get(place, []))}\t{inside}\t{description}\n")

    print(f"packets: {len(library.chapters)}")
    print(f"words: {total_words}")
    print(f"places: {len(library.places)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
