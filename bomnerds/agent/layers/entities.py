"""The entity list: one job per book lists what the book contains, then merge jobs combine what was listed twice."""

import json
import re
import sqlite3
import sys
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
from itertools import combinations
from math import ceil
from pathlib import Path
from string import ascii_lowercase

from ...passages import Rejected, book_name, chapter_numbers, english_edition, parse_reference, reference
from ...text import slug
from ...words import WORD
from .. import jobs
from ..jobs import CLI
from ..layer import Layer, Problems, kinds

WORKS = ("bom", "dc", "pgp")
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Agents name events and topics themselves, so those names need not appear in the text.
NAMED_FREELY = ("event", "topic")
SIMILAR = 0.8
COMMON = {"a", "an", "and", "as", "at", "by", "for", "from", "he", "her", "his", "in", "is", "of", "on", "she", "that", "the", "to", "was", "who", "with"}

ENTITIES = """
List every entity this book names or points to: each person, group, place, event, object, office, and topic.

- Read every chapter first. Context says how.
- Pick an entity already on the list instead of adding it again. The Bible's people and places are on the list, so Moses, Isaiah, and Jerusalem are picked. Entities on the list whose names appear in this book are under Context. Search for anything else before you add it.
- One entity is one being or thing. A man, the people named for him, and their land are three entities: Nephi, the Nephites, and the land of Nephi.
- Types: person, group, place, event, object, office, topic. Use city, land, water, mountain, or wilderness instead of place when the text says which, and record for a record such as the plates of brass.
- People and groups the text never names get an entity when they speak or act, named the way the text describes them: "the daughter of Jared".
- Topics are subjects the book teaches about, such as faith or repentance. Add the ones a reader would look up.
- Copy names from the text. "name" is the name the text uses most, "other_names" holds the other names it goes by, and "titles" holds titles that point to it, such as "the Holy One of Israel". The description is one line that says who or what it is and sets it apart.
- An id is the name in lowercase, joined by hyphens: Sariah is sariah. When another entity on the list or in your answer has the same name, the id adds what sets this one apart: lehi-father-of-nephi. If the other one's id is the bare name, it gains what sets it apart too: give its new id in "renames" on your new entity, and pick it by its new id. The CLI checks every id and says what to fix.

Answer with one object per entity. Pick one already on the list, with any names this book uses for it that the list lacks:

{ "pick": "moses" }
{ "pick": "jesus-christ", "titles": ["the Holy One of Israel"] }

Or add one:

{ "id": "sariah", "type": "person", "name": "Sariah", "other_names": [], "description": "Wife of Lehi and mother of Nephi." }
{ "id": "lehi-father-of-nephi", "type": "person", "name": "Lehi", "other_names": [], "description": "Prophet who led his family from Jerusalem to the promised land.", "renames": { "lehi": "lehi-in-judah" } }
"""

MERGE = """
Some entities are on the list twice, because each book listed its own. Under Context are groups of entities that share a name or have nearly the same description. Decide which entities in each group are one and the same.

- Two entities are the same only when they are one person, group, place, or thing. Two men named Nephi are two people. A man, the people named for him, and their land are three entities.
- Keep one and merge the others into it. Every tag on a merged entity moves to the kept one, its names become other names of the kept one, and the merged entity is deleted. A merge cannot be undone, so merge only when the descriptions and books leave no doubt.
- Keep an entity from the Bible list over one made for another work. The CLI rejects merging a Bible entity away.
- Merge only entities of one kind within one group: a person with a person, a place with a city or land.
- Most groups have nothing to merge. Leave those out.

Answer with one object per entity kept, or an empty array when nothing merges:

{ "keep": "isaiah", "merge": ["isaiah-son-of-amoz"] }
"""


@dataclass(frozen=True)
class Pick:
    id: str
    other_names: tuple[str, ...] = ()
    titles: tuple[str, ...] = ()


@dataclass(frozen=True)
class New:
    id: str
    type: str
    name: str
    other_names: tuple[str, ...]
    titles: tuple[str, ...]
    description: str
    renames: tuple[tuple[str, str], ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.other_names, *self.titles)


@dataclass(frozen=True)
class Merge:
    keep: str
    merged: tuple[str, ...]


@dataclass(frozen=True)
class Row:
    type: str
    family: str
    name: str
    description: str


class Catalog:
    """The entity list as it stands, read once per check."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.rows = {
            id: Row(type_id, family, name, description)
            for id, type_id, family, name, description in db.execute(
                "select e.id, e.type_id, coalesce(t.parent_id, t.id), e.name, e.description from entity e join entity_type t on t.id = e.type_id"
            )
        }
        self.by_base = defaultdict(list)
        for id, row in self.rows.items():
            self.by_base[slug(row.name)].append(id)
        self.names = defaultdict(set)
        self.proper_names = defaultdict(set)
        for id, row in self.rows.items():
            self.names[id].add(row.name.casefold())
            self.proper_names[id].add(row.name)
        for id, name, is_title in db.execute("select entity_id, name, is_title from entity_name"):
            self.names[id].add(name.casefold())
            if not is_title:
                self.proper_names[id].add(name)

    def line(self, id: str) -> str:
        row = self.rows[id]
        others = sorted(self.proper_names[id] - {row.name})
        description = row.description if row.description.endswith((".", "!", "?")) else row.description + "."
        return f"{id} ({row.type}) {row.name}. {description}" + (f" Also: {', '.join(others)}." if others else "")

    def books(self) -> dict[str, list[tuple[str, str, str]]]:
        """Each entity's books as (book id, book name, work id), in reading order."""
        found = defaultdict(list)
        for entity, book, name, work in self.db.execute(
            "select eb.entity_id, b.id, b.name, b.work_id from entity_book eb join book b on b.id = eb.book_id "
            "join edition_book p on p.book_id = b.id join edition e on e.id = p.edition_id and e.language = 'en' "
            "order by case b.work_id when 'bible' then 0 when 'bom' then 1 when 'dc' then 2 else 3 end, p.position"
        ):
            found[entity].append((book, name, work))
        return found


def entity_books(db: sqlite3.Connection) -> list[str]:
    """Every book of the works other than the Bible, in edition order."""
    return [
        book
        for (book,) in db.execute(
            "select b.id from book b join edition_book p on p.book_id = b.id join edition e on e.id = p.edition_id "
            "where e.language = 'en' and b.work_id in ('bom', 'dc', 'pgp') "
            "order by case b.work_id when 'bom' then 0 when 'dc' then 1 else 2 end, p.position"
        )
    ]


def tokens(text: str) -> list[str]:
    return [re.sub(r"'s$", "", word.replace("’", "'")) for word in WORD.findall(text)]


class BookText:
    """A book's words, for finding names in it."""

    def __init__(self, db: sqlite3.Connection, book: str):
        words = tokens(" ".join(text for (text,) in db.execute("select text from word where edition_id = ? and book_id = ? order by id", (english_edition(db, book), book))))
        self.text = f" {' '.join(words)} "
        self.folded = self.text.casefold()
        self.words = set(words)
        self.folded_words = {word.casefold() for word in words}

    def has(self, name: str, folded: bool = True) -> bool:
        parts = tokens(name)
        if not parts:
            return False
        if folded:
            return parts[0].casefold() in self.folded_words and f" {' '.join(parts).casefold()} " in self.folded
        return parts[0] in self.words and f" {' '.join(parts)} " in self.text


TEXTS: OrderedDict = OrderedDict()


def book_text(db: sqlite3.Connection, book: str) -> BookText:
    if (db, book) not in TEXTS:
        TEXTS[(db, book)] = BookText(db, book)
        while len(TEXTS) > 4:
            TEXTS.popitem(last=False)
    return TEXTS[(db, book)]


class Entities(Layer):
    name = "entities"
    step = 3
    scope = "book"
    mode = "check"
    instructions = ENTITIES

    def scopes(self, db):
        return entity_books(db)

    def ready(self, db, lookup, scope):
        books = self.scopes(db)
        at = books.index(scope)
        if at and lookup.get(self.name, books[at - 1]).settled() is None:
            return f"entities/{books[at - 1]} must settle first, so this book picks what earlier books listed"
        return None

    def context(self, db, lookup, scope):
        edition = english_edition(db, scope)
        numbers = chapter_numbers(db, edition, scope)
        first, last = reference(db, scope, numbers[0]), reference(db, scope, numbers[-1])
        read = f'Read "{first}" before you answer:' if first == last else f'Read every chapter from "{first}" to "{last}" before you answer, each with a command like:'
        lines = ["## Chapters", "", read, "", f'{CLI} show "{first}"']
        catalog = Catalog(db)
        found = appearing(db, catalog, scope)
        if found:
            lines += ["", "## Entities on the list whose names appear in this book", ""] + [catalog.line(id) for id in found]
        return "\n".join(lines)

    def parse(self, db, scope, answer):
        problems = Problems(db)
        items = problems.items(answer)
        types = kinds(db, "entity_type")
        found = []
        for number, item in enumerate(items, 1):
            problems.at(f"item {number}")
            if "pick" in item:
                tag = read_pick(problems, item)
            elif "id" in item:
                tag = read_new(problems, item, types)
            else:
                problems.add('each item picks an entity with "pick" or adds one with "id", as in the examples')
                tag = None
            if tag:
                found.append((number, tag))
        catalog = Catalog(db)
        if answer != jobs.Job(self, scope).settled():
            check_ids(problems, catalog, found)
        check_text(problems, catalog, book_text(db, scope), found, db.execute("select name from book where id = ?", (scope,)).fetchone()[0])
        check_once(problems, found)
        problems.raise_any()
        return [tag for _, tag in found]

    def render(self, db, tag):
        if isinstance(tag, Pick):
            item = {"pick": tag.id}
            if tag.other_names:
                item["other_names"] = list(tag.other_names)
            if tag.titles:
                item["titles"] = list(tag.titles)
            return item
        item = {"id": tag.id, "type": tag.type, "name": tag.name, "other_names": list(tag.other_names)}
        if tag.titles:
            item["titles"] = list(tag.titles)
        item["description"] = tag.description
        if tag.renames:
            item["renames"] = dict(tag.renames)
        return item

    def store(self, db, scope, tags):
        renamed = rename(db, [pair for tag in tags if isinstance(tag, New) for pair in tag.renames])
        for tag in tags:
            if isinstance(tag, New):
                insert(db, tag)
            else:
                db.executemany("insert or ignore into entity_name (entity_id, name, is_title) values (?, ?, ?)", name_rows(tag))
            db.execute("insert or ignore into entity_book (entity_id, book_id) values (?, ?)", (tag.id, scope))
        for old, new in renamed:
            jobs.rename_entity(old, new)

    def unstore(self, db, scope, tags):
        # Replay deletes and stores again in one transaction, so tags in later layers may point at these entities until it commits.
        db.execute("pragma defer_foreign_keys = on")
        claimed = claimed_names(scope)
        for tag in tags:
            db.execute("delete from entity_book where entity_id = ? and book_id = ?", (tag.id, scope))
            if isinstance(tag, New):
                db.executemany("delete from entity_name where entity_id = ? and name = ?", [(tag.id, name) for name in tag.names])
                db.execute("delete from entity where id = ?", (tag.id,))
            else:
                db.executemany("delete from entity_name where entity_id = ? and name = ?", [(tag.id, name) for _, name, _ in name_rows(tag) if (tag.id, name) not in claimed])

    def commands(self, subparsers):
        command = subparsers.add_parser("add-entity", help="add an entity an agent reported missing, and print the jobs that must rerun")
        command.add_argument("--job", required=True, help="the job that reported it, such as names/1-nephi/4")
        command.add_argument("--name", required=True)
        command.add_argument("--type", required=True)
        command.add_argument("--description", required=True)
        command.add_argument("--verse", required=True, help="a verse that names it. The entity is found in its book")
        command.add_argument("--id", help="the name in lowercase joined by hyphens unless another entity shares the name")
        command.add_argument("--other-name", action="append", default=[], dest="other_names")
        command.add_argument("--title", action="append", default=[], dest="titles")
        command.add_argument("--rename", action="append", default=[], metavar="OLD=NEW", help="the new id of an older entity with the same name whose id is the bare name")
        command.set_defaults(run=add_entity)


class Merges(Layer):
    name = "merge"
    step = 3
    scope = "letter"
    mode = "check"
    instructions = MERGE

    def scopes(self, db):
        return list(ascii_lowercase)

    def chapters(self, db, scope):
        return []

    def ready(self, db, lookup, scope):
        for book in entity_books(db):
            if lookup.get("entities", book).settled() is None:
                return f"every entities job must settle first, and entities/{book} has not"
        return None

    def context(self, db, lookup, scope):
        catalog = Catalog(db)
        found = groups(catalog).get(scope, [])
        if not found:
            return "No entities in this part of the list look listed twice. Answer with an empty array."
        books = catalog.books()
        sections = []
        for number, group in enumerate(found, 1):
            lines = [f"### Group {number}", ""]
            for id in group:
                where = found_in(books.get(id, []))
                bible = any(work == "bible" for _, _, work in books.get(id, []))
                lines.append(catalog.line(id) + (f" Found in {where}." if where else "") + (" Bible list, so it can only be kept." if bible else ""))
            sections.append("\n".join(lines))
        return "## Groups\n\n" + "\n\n".join(sections)

    def parse(self, db, scope, answer):
        problems = Problems(db)
        items = problems.items(answer)
        strict = answer != jobs.Job(self, scope).settled()
        if strict:
            catalog = Catalog(db)
            group_of = {id: n for n, group in enumerate(group for letter in groups(catalog).values() for group in letter) for id in group}
            bible = {id for (id,) in db.execute("select distinct eb.entity_id from entity_book eb join book b on b.id = eb.book_id where b.work_id = 'bible'")}
        tags, where = [], defaultdict(list)
        for number, item in enumerate(items, 1):
            problems.at(f"item {number}")
            if not problems.fields(item, ("keep", "merge")):
                continue
            keep, merged = item["keep"], item["merge"]
            if not isinstance(keep, str) or not isinstance(merged, list) or not merged or not all(isinstance(m, str) for m in merged):
                problems.add('"keep" takes one id and "merge" a list of ids')
                continue
            if len(set(merged)) < len(merged) or keep in merged:
                problems.add('list each id once, and leave the kept one out of "merge"')
                continue
            if strict and not merge_problems(problems, catalog, group_of, bible, keep, merged):
                continue
            for id in (keep, *merged):
                where[id].append(number)
            tags.append(Merge(keep, tuple(sorted(merged))))
        for id, numbers in where.items():
            if len(numbers) > 1:
                problems.at("").add(f"{id} is in items {', '.join(map(str, numbers))}. Each id belongs in one item")
        problems.raise_any()
        return tags

    def render(self, db, tag):
        return {"keep": tag.keep, "merge": list(tag.merged)}

    def store(self, db, scope, tags):
        merged = []
        for tag in tags:
            for old in tag.merged:
                if exists(db, old) and exists(db, tag.keep):
                    repoint(db, old, tag.keep)
                    merged.append((old, tag.keep))
        for old, new in merged:
            follow_merge(old, new)

    def unstore(self, db, scope, tags):
        if tags:
            print(f"merge/{scope}: merges are never undone. The merged entities are gone and their tags belong to the kept ones.", file=sys.stderr)


def read_pick(problems: Problems, item: dict) -> Pick | None:
    if not problems.fields(item, ("pick",), ("other_names", "titles")):
        return None
    if not isinstance(item["pick"], str):
        problems.add('"pick" takes an entity id')
        return None
    other, titles = name_list(problems, item, "other_names"), name_list(problems, item, "titles")
    if other is None or titles is None or not apart(problems, other, titles):
        return None
    return Pick(item["pick"], tuple(sorted(other)), tuple(sorted(titles)))


def read_new(problems: Problems, item: dict, types: list[str]) -> New | None:
    if not problems.fields(item, ("id", "type", "name", "other_names", "description"), ("titles", "renames")):
        return None
    texts = [key for key in ("id", "type", "name", "description") if not isinstance(item[key], str) or not item[key].strip()]
    if texts:
        problems.add(f"{', '.join(texts)} must be text")
        return None
    other, titles = name_list(problems, item, "other_names"), name_list(problems, item, "titles")
    renames = item.get("renames", {})
    if not isinstance(renames, dict) or not all(isinstance(old, str) and isinstance(new, str) for old, new in renames.items()):
        problems.add('"renames" maps each older id to its new id, like { "lehi": "lehi-in-judah" }')
        return None
    if other is None or titles is None or not apart(problems, other, titles):
        return None
    if item["type"] not in types:
        problems.add(f"type {item['type']!r} is not one of: {', '.join(types)}")
        return None
    name, description = item["name"].strip(), item["description"].strip()
    if "\n" in description:
        problems.add("the description is one line")
        return None
    if name.casefold() in {n.casefold() for n in other + titles}:
        problems.add(f'"{name}" is the name, so leave it out of other_names and titles')
        return None
    return New(item["id"], item["type"], name, tuple(sorted(other)), tuple(sorted(titles)), description, tuple(sorted(renames.items())))


def name_list(problems: Problems, item: dict, key: str) -> list[str] | None:
    value = item.get(key, [])
    if not isinstance(value, list) or not all(isinstance(name, str) and name.strip() for name in value):
        problems.add(f'"{key}" must be a list of names')
        return None
    names = [name.strip() for name in value]
    if len({name.casefold() for name in names}) < len(names):
        problems.add(f'"{key}" lists a name twice')
        return None
    return names


def apart(problems: Problems, other: list[str], titles: list[str]) -> bool:
    both = {name.casefold() for name in other} & {name.casefold() for name in titles}
    if both:
        problems.add(f"{', '.join(sorted(both))} is in both other_names and titles. Put each name in one")
    return not both


def check_ids(problems: Problems, catalog: Catalog, found: list[tuple[int, Pick | New]]):
    """The id rule, and that every pick is on the list, checked against the list as it stands."""
    news = [(number, tag) for number, tag in found if isinstance(tag, New)]
    renamed = {}
    for number, tag in news:
        for old, new in tag.renames:
            if old in renamed:
                problems.at(f"item {number}").add(f"{old} is renamed twice")
            renamed[old] = new
    for number, tag in news:
        check_new(problems.at(f"item {number}"), catalog, tag, [other for _, other in news if other is not tag])
    missing_renames(problems, catalog, news, renamed)
    ids = {tag.id for _, tag in news}
    for id, count in Counter(renamed.values()).items():
        if count > 1 or id in ids:
            problems.at("").add(f"the id {id} is given to more than one entity")
    for number, tag in found:
        if isinstance(tag, Pick):
            check_pick(problems.at(f"item {number}"), catalog, tag, renamed)


def check_new(problems: Problems, catalog: Catalog, tag: New, others: list[New]):
    base = slug(tag.name)
    if not ID.fullmatch(tag.id):
        problems.add(f'id "{tag.id}" must be lowercase words joined by hyphens, like {base or "sariah"}')
        return
    if tag.id in catalog.rows:
        problems.add(f'{tag.id} is already on the list: {catalog.line(tag.id)} If it is the same one, pick it with {{ "pick": "{tag.id}" }}. If not, give this one an id that sets it apart')
        return
    sharing = [id for id in catalog.by_base.get(base, [])] + [other.id for other in others if slug(other.name) == base]
    if not sharing and tag.id != base:
        problems.add(f'no other entity is named "{tag.name}", so the id is {base}')
    elif sharing and not tag.id.startswith(base + "-"):
        problems.add(f'"{tag.name}" also names {", ".join(sharing)}, so the id is {base} followed by what sets this one apart, such as {base}-son-of-... for a person or {base}-in-... for a place')
    for old, new in tag.renames:
        row = catalog.rows.get(old)
        if row is None:
            problems.add(f'"renames": {old} is already renamed to {new}, so leave it out' if new in catalog.rows else f'"renames": {old} is not on the list')
            continue
        if slug(row.name) != base:
            problems.add(f'"renames": {old} is named "{row.name}", not "{tag.name}". Rename only an entity that shares this one\'s name')
        elif old != base:
            problems.add(f'"renames": {old} already has what sets it apart, so leave it out')
        elif not ID.fullmatch(new) or not new.startswith(base + "-"):
            problems.add(f'"renames": the new id for {old} must be {base} followed by what sets it apart')
        elif new in catalog.rows:
            problems.add(f'"renames": {new} is already on the list')


def missing_renames(problems: Problems, catalog: Catalog, news: list[tuple[int, New]], renamed: dict[str, str]):
    """An older entity whose id is the bare name gains a qualifier once a new entity shares its name."""
    reported = set()
    for number, tag in news:
        base = slug(tag.name)
        row = catalog.rows.get(base)
        if row and slug(row.name) == base and base not in renamed and base not in reported:
            reported.add(base)
            problems.at(f"item {number}").add(
                f'{base} is {catalog.line(base)} If that is the same one, pick it. If not, it needs what sets it apart too: '
                f'add "renames": {{ "{base}": "{base}-..." }} with its new id'
            )


def check_pick(problems: Problems, catalog: Catalog, tag: Pick, renamed: dict[str, str]):
    if tag.id in renamed:
        problems.add(f"{tag.id} is renamed to {renamed[tag.id]} in this answer, so pick it by that id")
        return
    source = next((old for old, new in renamed.items() if new == tag.id), tag.id)
    if source not in catalog.rows:
        problems.add(f'{tag.id!r} is not on the entity list. Search for it, or add it with "id"')
        return
    for name in tag.other_names + tag.titles:
        if name.casefold() in catalog.names[source]:
            problems.add(f'"{name}" is already a name of {tag.id}, so leave it out')


def check_text(problems: Problems, catalog: Catalog, text: BookText, found: list[tuple[int, Pick | New]], book: str):
    """Names are copied from the book, except the names of events and topics."""
    for number, tag in found:
        problems.at(f"item {number}")
        if isinstance(tag, New):
            type_id, names = tag.type, tag.names
        else:
            type_id, names = catalog.rows[tag.id].type if tag.id in catalog.rows else None, tag.other_names + tag.titles
        if type_id in NAMED_FREELY:
            continue
        for name in names:
            if not text.has(name):
                problems.add(f'"{name}" is not in {book}. Copy names as the text writes them')


def check_once(problems: Problems, found: list[tuple[int, Pick | New]]):
    where = defaultdict(list)
    for number, tag in found:
        where[tag.id].append(number)
    for id, numbers in where.items():
        if len(numbers) > 1:
            problems.at("").add(f"{id} is in items {', '.join(map(str, numbers))}. List each entity once")


def appearing(db: sqlite3.Connection, catalog: Catalog, book: str) -> list[str]:
    """Entities whose names appear in the book, with topics matched in any case, and entities already found in it."""
    text = book_text(db, book)
    names = defaultdict(set)
    for id, row in catalog.rows.items():
        names[id].add(row.name)
    for id, name in db.execute("select entity_id, name from entity_name"):
        names[id].add(name)
    found = {id for (id,) in db.execute("select entity_id from entity_book where book_id = ?", (book,))}
    found |= {id for id, carried in names.items() if any(text.has(name, folded=catalog.rows[id].type == "topic") for name in carried)}
    return sorted(found, key=lambda id: (catalog.rows[id].name.casefold(), id))


def name_rows(tag: Pick | New) -> list[tuple[str, str, int]]:
    rows = [(tag.id, tag.name, 0)] if isinstance(tag, New) else []
    return rows + [(tag.id, name, 0) for name in tag.other_names] + [(tag.id, name, 1) for name in tag.titles]


def insert(db: sqlite3.Connection, tag: New):
    db.execute("insert into entity (id, type_id, name, description) values (?, ?, ?, ?)", (tag.id, tag.type, tag.name, tag.description))
    db.executemany("insert into entity_name (entity_id, name, is_title) values (?, ?, ?)", name_rows(tag))


def rename(db: sqlite3.Connection, renames: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Give older entities their new ids, skipping any already renamed. Every table cascades the change."""
    done = []
    for old, new in renames:
        if exists(db, old) and not exists(db, new):
            db.execute("update entity set id = ? where id = ?", (new, old))
            done.append((old, new))
    return done


def exists(db: sqlite3.Connection, id: str) -> bool:
    return db.execute("select 1 from entity where id = ?", (id,)).fetchone() is not None


def claimed_names(scope: str) -> set[tuple[str, str]]:
    """Every (entity, name) another settled entities job lists, which this job's reset must leave in place."""
    claimed = set()
    for path in (jobs.JOBS / "entities").glob("*/settled.json"):
        if path.parent.name == scope:
            continue
        for item in jobs.read(path) or []:
            id = item.get("pick", item.get("id"))
            claimed |= {(id, name) for name in [*item.get("other_names", []), *item.get("titles", []), *([item["name"]] if "name" in item else [])]}
    return claimed


def groups(catalog: Catalog) -> dict[str, list[list[str]]]:
    """Entities that may be one listed twice, by the letter of the job that shows them.

    A group joins an entity made for a work other than the Bible to every entity of its kind that shares one of its names
    or has nearly the same description. Entities on the Bible list join only through such an entity.
    """
    books = catalog.books()
    made = {id for id, found in books.items() if found and all(work != "bible" for _, _, work in found)}
    parent = {}

    def root(id):
        while parent.setdefault(id, id) != id:
            parent[id] = parent[parent[id]]
            id = parent[id]
        return id

    carriers = defaultdict(set)
    for id, names in catalog.proper_names.items():
        for name in names:
            carriers[slug(name)].add(id)
    for key, ids in carriers.items():
        for id in ids & made:
            for other in ids - {id}:
                if catalog.rows[other].family == catalog.rows[id].family:
                    parent[root(other)] = root(id)
    for a, b in similar_descriptions(catalog, made):
        parent[root(b)] = root(a)

    members = defaultdict(list)
    for id in list(parent):
        members[root(id)].append(id)
    found = defaultdict(list)
    for group in members.values():
        if len(group) < 2:
            continue
        first = min(slug(catalog.rows[id].name) or id for id in group if id in made)
        letter = first[0] if first[0] in ascii_lowercase else "a"
        found[letter].append(sorted(group, key=lambda id: (catalog.rows[id].name.casefold(), id)))
    for letter in found:
        found[letter].sort(key=lambda group: min(slug(catalog.rows[id].name) for id in group))
    return found


def similar_descriptions(catalog: Catalog, made: set[str]) -> list[tuple[str, str]]:
    """Pairs of one kind, at least one made outside the Bible, whose descriptions share nearly all their words."""
    words = {}
    for id, row in catalog.rows.items():
        content = {word.casefold() for word in WORD.findall(row.description)} - COMMON
        if len(content) >= 3:
            words[id] = content
    frequency = Counter(word for content in words.values() for word in content)
    index = defaultdict(list)
    for id, content in words.items():
        rarest = sorted(content, key=lambda word: (frequency[word], word))
        for word in rarest[: len(rarest) - ceil(SIMILAR * len(rarest)) + 1]:
            index[word].append(id)
    pairs = set()
    for ids in index.values():
        for a, b in combinations(ids, 2):
            if (a in made or b in made) and catalog.rows[a].family == catalog.rows[b].family:
                shared = words[a] & words[b]
                if len(shared) >= SIMILAR * len(words[a] | words[b]):
                    pairs.add((min(a, b), max(a, b)))
    return sorted(pairs)


def found_in(books: list[tuple[str, str, str]]) -> str:
    works = {"bible": "the Bible", "bom": "the Book of Mormon", "dc": "the Doctrine and Covenants", "pgp": "the Pearl of Great Price"}
    by_work = defaultdict(list)
    for _, name, work in books:
        by_work[work].append(name)
    return ", ".join(", ".join(names) if len(names) <= 4 else f"{len(names)} books of {works[work]}" for work, names in by_work.items())


def merge_problems(problems: Problems, catalog: Catalog, group_of: dict[str, int], bible: set[str], keep: str, merged: list[str]) -> bool:
    unknown = [id for id in (keep, *merged) if id not in catalog.rows]
    if unknown:
        problems.add(f"{', '.join(unknown)} is not on the entity list")
        return False
    before = len(problems.messages)
    for id in merged:
        if id in bible:
            problems.add(f"{id} is on the Bible list, which a script builds, so keep it and merge the other into it")
        elif catalog.rows[id].family != catalog.rows[keep].family:
            problems.add(f"{id} is a {catalog.rows[id].type} and {keep} a {catalog.rows[keep].type}. Merge only entities of one kind")
        elif id not in group_of or group_of.get(id) != group_of.get(keep):
            problems.add(f"{id} and {keep} are not in one group")
    return len(problems.messages) == before


def repoint(db: sqlite3.Connection, old: str, new: str):
    """Move every reference from one entity to another, dropping what would repeat, then delete the old one."""
    for table in ("mention", "speech_listener", "entity_name", "entity_book"):
        db.execute(f"update or ignore {table} set entity_id = ? where entity_id = ?", (new, old))
        db.execute(f"delete from {table} where entity_id = ?", (old,))
    db.execute("update speech set through_id = null where (speaker_id, through_id) in ((?, ?), (?, ?))", (old, new, new, old))
    db.execute("update speech set speaker_id = ? where speaker_id = ?", (new, old))
    db.execute("update speech set through_id = ? where through_id = ?", (new, old))
    db.execute("update journey set from_id = null where (from_id, to_id) in ((?, ?), (?, ?))", (old, new, new, old))
    for column in ("traveler_id", "from_id", "to_id"):
        db.execute(f"update journey set {column} = ? where {column} = ?", (new, old))
    db.execute("update date set entity_id = ? where entity_id = ?", (new, old))
    db.execute("delete from relationship where (subject_id, object_id) in ((?, ?), (?, ?))", (old, new, new, old))
    for id, subject, kind, object, two_way in db.execute(
        "select r.id, r.subject_id, r.kind_id, r.object_id, k.two_way from relationship r join relationship_kind k on k.id = r.kind_id where ? in (r.subject_id, r.object_id)", (old,)
    ).fetchall():
        subject, object = (new if subject == old else subject), (new if object == old else object)
        same = db.execute(
            "select id, subject_id from relationship where kind_id = ? and min(subject_id, object_id) = min(?, ?) and max(subject_id, object_id) = max(?, ?) and id <> ?",
            (kind, subject, object, subject, object, id),
        ).fetchone()
        if same is None:
            db.execute("update relationship set subject_id = ?, object_id = ? where id = ?", (subject, object, id))
            continue
        # The same fact found under both entities keeps one row with all its evidence. A one-way fact running the other way contradicts it and is dropped.
        if two_way or same[1] == subject:
            db.execute("insert or ignore into relationship_evidence (relationship_id, first_word_id, last_word_id) select ?, first_word_id, last_word_id from relationship_evidence where relationship_id = ?", (same[0], id))
            db.execute("update date set relationship_id = ? where relationship_id = ?", (same[0], id))
        db.execute("delete from relationship where id = ?", (id,))
    db.execute("delete from entity where id = ?", (old,))


def follow_merge(old: str, new: str):
    """Make saved answers point at the kept entity, as the database now does."""
    for path in (jobs.JOBS / "entities").glob("**/*.json"):
        items = jobs.read(path)
        if isinstance(items, list):
            folded = fold_into(items, old, new)
            if folded != items:
                write(path, folded)
    follow_rename(old, new)


def follow_rename(old: str, new: str):
    """Rename an entity in saved answers, where merge answers rename only their kept ids."""
    merges = {path: jobs.read(path) for path in (jobs.JOBS / "merge").glob("**/*.json")}
    jobs.rename_entity(old, new)
    # A merge answer names entities that are gone on purpose, so only its kept ids follow a rename.
    for path, items in merges.items():
        if isinstance(items, list):
            kept = [{**item, "keep": new} if isinstance(item, dict) and item.get("keep") == old else item for item in items]
            if jobs.read(path) != kept:
                write(path, kept)


def fold_into(items: list, old: str, new: str) -> list:
    """An entities answer with the merged entity turned into a pick of the kept one, listed once."""
    folded = []
    for item in items:
        if isinstance(item, dict):
            if item.get("id") == old:
                item = {"pick": new}
            elif item.get("pick") == old:
                item = {**item, "pick": new}
            target = item.get("id", item.get("pick"))
            earlier = next((i for i, f in enumerate(folded) if isinstance(f, dict) and target == new and f.get("id", f.get("pick")) == new), None)
            if earlier is not None:
                first, second = (item, folded[earlier]) if "id" in item else (folded[earlier], item)
                folded[earlier] = with_names(first, second)
                continue
        folded.append(item)
    return folded


def with_names(item: dict, other: dict) -> dict:
    combined = dict(item)
    other_names = {*item.get("other_names", []), *other.get("other_names", [])} - {item.get("name")}
    titles = {*item.get("titles", []), *other.get("titles", [])} - other_names - {item.get("name")}
    if other_names or "id" in item:
        combined["other_names"] = sorted(other_names)
    if titles:
        combined["titles"] = sorted(titles)
    return combined


def write(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def add_entity(db: sqlite3.Connection, args):
    """Add a reported entity, rename the older one that shares its name, and print the resets that must follow."""
    job = jobs.find(db, args.job)
    book = parse_reference(db, args.verse)[0]
    renames = {}
    for pair in args.rename:
        old, _, new = pair.partition("=")
        if not old or not new:
            raise Rejected(f"--rename takes OLD=NEW, not {pair!r}")
        renames[old] = new
    item = {"id": args.id or slug(args.name), "type": args.type, "name": args.name, "other_names": args.other_names, "titles": args.titles, "description": args.description, "renames": renames}
    problems = Problems(db)
    tag = read_new(problems, item, kinds(db, "entity_type"))
    problems.raise_any()
    catalog = Catalog(db)
    check_new(problems, catalog, tag, [])
    missing_renames(problems, catalog, [(1, tag)], dict(tag.renames))
    check_text(problems, catalog, book_text(db, book), [(1, tag)], db.execute("select name from book where id = ?", (book,)).fetchone()[0])
    if problems.messages:
        raise Rejected("\n".join(problems.messages) + '\nIn add-entity, "id" is --id and "renames" is --rename OLD=NEW.')
    shared = [name for name in tag.names if any(name.casefold() in carried for carried in catalog.names.values())]
    with db:
        renamed = rename(db, list(tag.renames))
        insert(db, tag)
        db.execute("insert into entity_book (entity_id, book_id) values (?, ?)", (tag.id, book))
    jobs.resolve_report(job.id, args.name)
    print(f"Added {tag.id} ({tag.type}) {tag.name}, found in {book_name(db, book)}.")
    for old, new in renamed:
        print(f"Renamed {old} to {new}. Saved answers changed: {jobs.rename_entity(old, new)}.")
    if shared:
        print(f"Other entities also carry {', '.join(f'{name!r}' for name in shared)}, so chapters that name it may hold mentions of {tag.id}.")
    rerun = reruns(db, job, shared)
    if not rerun:
        print("No job that must rerun has answers yet, so nothing needs a reset.")
        return
    print("Reset these jobs, latest step first, so they run again:")
    for found in rerun:
        print(f"{CLI} reset {found.id}")


def reruns(db: sqlite3.Connection, reporting: jobs.Job, names: list[str]) -> list[jobs.Job]:
    """The reporting job and every chapter job on a chapter that holds one of the names, where the job has answers."""
    from . import LAYERS

    chapters = chapters_naming(db, names)
    found = [reporting]
    for layer in sorted((layer for layer in LAYERS.values() if layer.scope == "chapter"), key=lambda layer: -layer.step):
        found += [jobs.Job(layer, scope) for scope in chapters if scope in layer.scope_set(db)]
    found.sort(key=lambda job: -job.layer.step)
    seen, listed = set(), []
    for job in found:
        if job.id not in seen and any((job.path / f"{name}.json").exists() for name in (*jobs.ROLES[job.layer.mode], "settled")):
            seen.add(job.id)
            listed.append(job)
    return listed


def chapters_naming(db: sqlite3.Connection, names: list[str]) -> list[str]:
    """book/chapter for every English chapter whose text holds one of the names as written, or with a capital first letter."""
    found = {}
    for name in names:
        parts = tokens(name)
        if not parts:
            continue
        wanted = {f" {' '.join(parts)} ", f" {' '.join([parts[0][:1].upper() + parts[0][1:], *parts[1:]])} "}
        for edition, book, chapter, first in db.execute(
            "select w.edition_id, w.book_id, w.chapter, min(w.id) from word w join edition e on e.id = w.edition_id "
            "where e.language = 'en' and w.text like ? group by w.edition_id, w.book_id, w.chapter",
            (parts[0] + "%",),
        ).fetchall():
            text = f" {' '.join(tokens(' '.join(t for (t,) in db.execute('select text from word where edition_id = ? and book_id = ? and chapter = ? order by id', (edition, book, chapter)))))} "
            if any(w in text for w in wanted):
                found[f"{book}/{chapter}"] = first
    return sorted(found, key=found.get)


LAYERS = [Entities(), Merges()]
