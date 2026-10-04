"""The entity list: what all of scripture needs first, then what each book contains, in order, so a later book picks what an earlier one listed.

A scope is "scripture", a book, or book/first-last for a run of chapters of a book too long for one answer.
"""

import re
import sqlite3
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
from itertools import combinations
from math import ceil
from string import ascii_lowercase

from ...passages import book_name, chapter_numbers, english_edition, reference
from ...text import slug
from ...words import WORD
from .. import jobs
from ..layer import Layer, Problems, kinds

WORKS = ("bom", "dc", "pgp")
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Agents name events and topics themselves, so those names need not appear in the text.
NAMED_FREELY = ("event", "topic")
SIMILAR = 0.8
COMMON = {"a", "an", "and", "as", "at", "by", "for", "from", "he", "her", "his", "in", "is", "of", "on", "she", "that", "the", "to", "was", "who", "with"}

ENTITIES = """
List every entity these chapters name or point to: each person, group, place, event, object, office, and topic.

- Read every chapter of a section before you answer it.
- Pick an entity already on the list instead of adding it again. The Bible's people and places are on the list, so Moses, Isaiah, and Jerusalem are picked. Under each section are the entities on the list whose names appear in its chapters, and every entity this book already holds.
- One entity is one being or thing. A man, the people named for him, and their land are three entities: Nephi, the Nephites, and the land of Nephi.
- Types: person, group, place, event, object, office, topic. Use city, land, water, mountain, or wilderness instead of place when the text says which, and record for a record such as the plates of brass.
- People and groups the text never names get an entity when they speak or act, named the way the text describes them: "the daughter of Jared".
- Topics are subjects the text teaches about, such as faith or repentance. Add the ones a reader would look up.
- Copy names from the text. "name" is the name the text uses most, "other_names" holds the other names it goes by, and "titles" holds titles that point to it, such as "the Holy One of Israel". The description is one line that says who or what it is and sets it apart.
- An id is the name in lowercase, joined by hyphens: Sariah is sariah. When another entity on the list or in your answer has the same name, the id adds what sets this one apart: lehi-father-of-nephi. If the other one's id is the bare name, it gains what sets it apart too: give its new id in "renames" on your new entity, and pick it by its new id. The CLI checks every id and says what to fix.

The section "All of scripture" has no text. In it, add what every work needs that no single book's text names: the narrator of each work or book whose narrator is never named, such as the Bible's narrator, and the topics a reader would look up anywhere in scripture, such as faith, repentance, prayer, and the Atonement of Jesus Christ. Give each one "books": the ids of the books it belongs to, or [] for a topic that belongs to all of them. Later sections pick these.

Answer with one object per entity. Pick one already on the list, with any names these chapters use for it that the list lacks:

{ "pick": "moses" }
{ "pick": "jesus-christ", "titles": ["the Holy One of Israel"] }

Or add one:

{ "id": "sariah", "type": "person", "name": "Sariah", "other_names": [], "description": "Wife of Lehi and mother of Nephi." }
{ "id": "lehi-father-of-nephi", "type": "person", "name": "Lehi", "other_names": [], "description": "Prophet who led his family from Jerusalem to the promised land.", "renames": { "lehi": "lehi-in-judah" } }
"""

# Books longer than this many words are split into parts of about the same length, each its own scope.
PART_WORDS = 30000
SCRIPTURE = "scripture"


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
    # Set only for entities added for all of scripture, which name their books.
    books: tuple[str, ...] | None = None

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.other_names, *self.titles)


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


def entity_scopes(db: sqlite3.Connection) -> list[str]:
    """The whole-scripture scope, then each book, or each part of a book longer than PART_WORDS, in reading order."""
    scopes = [SCRIPTURE]
    for book in entity_books(db):
        edition = english_edition(db, book)
        sizes = list(db.execute("select chapter, count(*) from word where edition_id = ? and book_id = ? group by chapter order by chapter", (edition, book)))
        total = sum(size for _, size in sizes)
        parts = ceil(total / PART_WORDS)
        if parts <= 1:
            scopes.append(book)
            continue
        target, run, cuts, first = total / parts, 0, 1, sizes[0][0]
        for i, (chapter, size) in enumerate(sizes):
            run += size
            if i + 1 == len(sizes) or run >= target * cuts:
                scopes.append(f"{book}/{first}-{chapter}")
                cuts += 1
                if i + 1 < len(sizes):
                    first = sizes[i + 1][0]
    return scopes


def split_scope(scope: str) -> tuple[str | None, int | None, int | None]:
    """The book of an entities scope and its first and last chapter, or None for whole books and for the whole-scripture scope."""
    if scope == SCRIPTURE:
        return None, None, None
    book, _, chapters = scope.partition("/")
    if not chapters:
        return book, None, None
    first, _, last = chapters.partition("-")
    return book, int(first), int(last)


def tokens(text: str) -> list[str]:
    return [re.sub(r"'s$", "", word.replace("’", "'")) for word in WORD.findall(text)]


class BookText:
    """A book's words, or the words of a run of its chapters, for finding names in it."""

    def __init__(self, db: sqlite3.Connection, book: str, first: int | None = None, last: int | None = None):
        low, high = (first, last) if first is not None else (0, 10**6)
        words = tokens(" ".join(text for (text,) in db.execute(
            "select text from word where edition_id = ? and book_id = ? and chapter between ? and ? order by id", (english_edition(db, book), book, low, high)
        )))
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


def book_text(db: sqlite3.Connection, book: str, first: int | None = None, last: int | None = None) -> BookText:
    if (db, book, first, last) not in TEXTS:
        TEXTS[(db, book, first, last)] = BookText(db, book, first, last)
        while len(TEXTS) > 4:
            TEXTS.popitem(last=False)
    return TEXTS[(db, book, first, last)]


class Entities(Layer):
    name = "entities"
    step = 3
    scope = "book, part of a book, or all of scripture"
    points = False
    ordered = True
    instructions = ENTITIES

    def scopes(self, db):
        return entity_scopes(db)

    def label(self, db, scope):
        book, first, last = split_scope(scope)
        if book is None:
            return "All of scripture"
        if first is None:
            return book_name(db, book)
        return reference(db, book, first) if first == last else f"{reference(db, book, first)}–{last}"

    def chapters(self, db, scope):
        book, first, last = split_scope(scope)
        if book is None:
            return []
        numbers = chapter_numbers(db, english_edition(db, book), book)
        return [(book, n) for n in numbers if first is None or first <= n <= last]

    def extra(self, db, lookup, scope, batch=()):
        catalog = Catalog(db)
        if scope == SCRIPTURE:
            found = [id for id, row in catalog.rows.items() if row.type == "topic" or not catalog.books().get(id)]
            listed = "\n".join(catalog.line(id) for id in sorted(found))
            return "## Already on the list\n\n" + (listed or "No topics or narrators yet.")
        found = appearing(db, catalog, scope)
        if not found:
            return ""
        return "## Entities on the list whose names appear here, or that this book already holds\n\n" + "\n".join(catalog.line(id) for id in found)

    def parse(self, db, scope, answer):
        problems = Problems(db)
        items = problems.items(answer)
        types = kinds(db, "entity_type")
        books = {id for (id,) in db.execute("select id from book")}
        found = []
        for number, item in enumerate(items, 1):
            problems.at(f"item {number}")
            if "pick" in item:
                tag = read_pick(problems, item)
            elif "id" in item:
                tag = read_new(problems, item, types)
                if tag and scope == SCRIPTURE and tag.books is None:
                    problems.add('every entity added for all of scripture takes "books": the ids of its books, or [] for a topic')
                    tag = None
                elif tag and scope != SCRIPTURE and tag.books is not None:
                    problems.add('"books" belongs only to entities added for all of scripture. This one is found in the book being read')
                    tag = None
                elif tag and set(tag.books or ()) - books:
                    problems.add(f"{', '.join(sorted(set(tag.books) - books))} is not a book id")
                    tag = None
            else:
                problems.add('each item picks an entity with "pick" or adds one with "id", as in the examples')
                tag = None
            if tag:
                found.append((number, tag))
        catalog = Catalog(db)
        if answer != jobs.Job(self, scope).settled():
            check_ids(problems, catalog, found)
        book, first, last = split_scope(scope)
        if book is not None:
            check_text(problems, catalog, book_text(db, book, first, last), found, self.label(db, scope))
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
        if tag.books is not None:
            item["books"] = list(tag.books)
        return item

    def store(self, db, scope, tags):
        book = split_scope(scope)[0]
        renamed = rename(db, [pair for tag in tags if isinstance(tag, New) for pair in tag.renames])
        for tag in tags:
            if isinstance(tag, New):
                insert(db, tag)
            else:
                db.executemany("insert or ignore into entity_name (entity_id, name, is_title) values (?, ?, ?)", name_rows(tag))
            for found in tag_books(tag, book):
                db.execute("insert or ignore into entity_book (entity_id, book_id) values (?, ?)", (tag.id, found))
        for old, new in renamed:
            jobs.rename_entity(old, new)

    def unstore(self, db, scope, tags):
        # Replay deletes and stores again in one transaction, so tags in later layers may point at these entities until it commits.
        db.execute("pragma defer_foreign_keys = on")
        book = split_scope(scope)[0]
        claimed = claimed_names(scope)
        for tag in tags:
            for found in tag_books(tag, book):
                if (tag.id, found) not in claimed:
                    db.execute("delete from entity_book where entity_id = ? and book_id = ?", (tag.id, found))
            if isinstance(tag, New):
                db.executemany("delete from entity_name where entity_id = ? and name = ?", [(tag.id, name) for name in tag.names])
                db.execute("delete from entity where id = ?", (tag.id,))
            else:
                db.executemany("delete from entity_name where entity_id = ? and name = ?", [(tag.id, name) for _, name, _ in name_rows(tag) if (tag.id, name) not in claimed])


def tag_books(tag, book: str | None) -> tuple[str, ...]:
    """The books an entities answer records an entity in: the book being read, or the books an entity for all of scripture names."""
    if book is not None:
        return (book,)
    return (tag.books or ()) if isinstance(tag, New) else ()


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
    if not problems.fields(item, ("id", "type", "name", "other_names", "description"), ("titles", "renames", "books")):
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
    books = item.get("books")
    if books is not None and (not isinstance(books, list) or not all(isinstance(book, str) for book in books)):
        problems.add('"books" must be a list of book ids')
        return None
    return New(item["id"], item["type"], name, tuple(sorted(other)), tuple(sorted(titles)), description, tuple(sorted(renames.items())), None if books is None else tuple(sorted(set(books))))


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


def appearing(db: sqlite3.Connection, catalog: Catalog, scope: str) -> list[str]:
    """Entities whose names appear in the scope's chapters, with topics matched in any case, and entities already found in its book."""
    book, first, last = split_scope(scope)
    text = book_text(db, book, first, last)
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
    """Every (entity, name) and (entity, book) another settled entities job lists, which this job's reset must leave in place."""
    claimed = set()
    root = jobs.JOBS / "entities"
    for path in root.glob("**/settled.json"):
        other = path.parent.relative_to(root).as_posix()
        if other == scope:
            continue
        book = split_scope(other)[0]
        for item in jobs.read(path) or []:
            id = item.get("pick", item.get("id"))
            claimed |= {(id, name) for name in [*item.get("other_names", []), *item.get("titles", []), *([item["name"]] if "name" in item else [])]}
            claimed |= {(id, found) for found in ([book] if book else item.get("books") or [])}
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


LAYERS = [Entities()]
