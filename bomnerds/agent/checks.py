"""Script checks that look across batches before each review. Each finding names the layer and scope a review fixes it in.

A finding is something to look at, not a proven error: a name tied to two entities in one book is often two people who share it.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from ..passages import locate, reference
from .layer import scope_span, split_chapter

PLURAL = {"we", "us", "our", "ours", "ourselves", "ye", "you", "your", "yours", "yourselves", "they", "them", "their", "theirs", "themselves"}
SINGULAR = {"i", "me", "my", "mine", "myself", "thou", "thee", "thy", "thine", "thyself", "he", "him", "his", "himself", "she", "her", "hers", "herself"}
FAMILY = ("child_of", "spouse_of", "sibling_of")
LISTED = 8


@dataclass(frozen=True)
class Finding:
    layer: str
    scope: str
    text: str


def findings(db: sqlite3.Connection, pass_name: str, units: list[str]) -> list[Finding]:
    check = CHECKS.get(pass_name)
    return check(db, units) if check else []


def verse_of(db: sqlite3.Connection, word: int) -> str:
    _, book, chapter, verse = locate(db, word)
    return reference(db, book, chapter, verse)


def scope_of(db: sqlite3.Connection, word: int) -> str:
    _, book, chapter, _ = locate(db, word)
    return f"{book}/{chapter}"


def entities(db: sqlite3.Connection, units: list[str]) -> list[Finding]:
    """Entities that may be one listed twice: they share a name or have nearly the same description."""
    from .layers import LAYERS
    from .layers.entities import SCRIPTURE, Catalog, found_in, groups, split_scope

    catalog = Catalog(db)
    books = catalog.books()
    # Each group goes to the first scope of the whole list holding one of its books, so exactly one review settles it.
    first_scope = {}
    for unit in LAYERS["entities"].scopes(db):
        first_scope.setdefault(split_scope(unit)[0], unit)
    found = []
    for letter in groups(catalog).values():
        for group in letter:
            lines = [catalog.line(id) + (f" Found in {found_in(books[id])}." if books.get(id) else "") for id in group]
            scope = next((first_scope[book] for id in group for book, _, _ in books.get(id, []) if book in first_scope), SCRIPTURE)
            if scope not in units:
                continue
            found.append(Finding("entities", scope, "These may be one entity listed twice. If so, keep one and pick it in place of the others:\n" + "\n".join(lines)))
    return found


def people(db: sqlite3.Connection, units: list[str]) -> list[Finding]:
    return names(db, units) + speakers(db, units)


def names(db: sqlite3.Connection, units: list[str]) -> list[Finding]:
    """One name tied to two or more entities in one book, with the verses of every entity but the one it names most."""
    uses: dict[tuple[str, str], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for scope in units:
        book, _ = split_chapter(scope)
        first, last = scope_span(db, scope)
        for entity, start, text in db.execute(
            "select m.entity_id, m.first_word_id, (select group_concat(text, ' ') from word where id between m.first_word_id and m.last_word_id) "
            "from mention m left join word_headword h on h.word_id = m.first_word_id and m.first_word_id = m.last_word_id "
            "where m.kind_id = 'names' and m.first_word_id between ? and ? and coalesce(h.part_of_speech, '') <> 'pronoun'",
            (first, last),
        ):
            uses[(book, text)][entity].append(start)
    found = []
    for (book, text), by_entity in uses.items():
        if len(by_entity) < 2:
            continue
        ranked = sorted(by_entity.items(), key=lambda pair: -len(pair[1]))
        counts = ", ".join(f"{entity} {len(words)} times" for entity, words in ranked)
        rest = [word for _, words in ranked[1:] for word in words]
        verses = ", ".join(verse_of(db, word) for word in rest[:LISTED]) + (f" and {len(rest) - LISTED} more" if len(rest) > LISTED else "")
        found.append(Finding("names", scope_of(db, rest[0]), f'"{text}" names {counts} in this book. Check the less common ones: {verses}'))
    return found


def speakers(db: sqlite3.Connection, units: list[str]) -> list[Finding]:
    """A speech whose speaker is never named in it or in the two chapters before it, leaving out narration and narrators."""
    found = []
    for scope in units:
        book, chapter = split_chapter(scope)
        first, last = scope_span(db, scope)
        earlier = [f"{book}/{n}" for n in (chapter - 2, chapter - 1) if n >= 1]
        window = min([first] + [scope_span(db, s)[0] for s in earlier if exists(db, s)])
        for speaker, start, end in db.execute(
            "select s.speaker_id, s.first_word_id, s.last_word_id from speech s where s.first_word_id between ? and ? and s.mode_id <> 'narration' "
            "and exists (select 1 from entity_book b where b.entity_id = s.speaker_id)",
            (first, last),
        ).fetchall():
            named = db.execute("select 1 from mention where entity_id = ? and kind_id = 'names' and first_word_id between ? and ? limit 1", (speaker, window, end)).fetchone()
            if not named:
                found.append(Finding("speakers", scope, f"{speaker} speaks from {verse_of(db, start)} but is not named there or in the two chapters before. Check the speaker"))
    return found


def exists(db: sqlite3.Connection, scope: str) -> bool:
    book, chapter = split_chapter(scope)
    return db.execute("select 1 from word where book_id = ? and chapter = ? limit 1", (book, chapter)).fetchone() is not None


def pronouns(db: sqlite3.Connection, units: list[str]) -> list[Finding]:
    """A plural pronoun pointing at one person, or a singular one pointing at a group."""
    found = []
    for scope in units:
        first, last = scope_span(db, scope)
        for entity, family, text, word in db.execute(
            "select m.entity_id, coalesce(t.parent_id, t.id), w.text, w.id from mention m join word w on w.id = m.first_word_id "
            "join word_headword h on h.word_id = w.id join entity e on e.id = m.entity_id join entity_type t on t.id = e.type_id "
            "where m.kind_id = 'names' and m.first_word_id = m.last_word_id and h.part_of_speech = 'pronoun' and m.first_word_id between ? and ?",
            (first, last),
        ):
            folded = text.casefold()
            if (folded in PLURAL and family == "person") or (folded in SINGULAR and family == "group"):
                number = "plural" if folded in PLURAL else "singular"
                found.append(Finding("pronouns", scope, f'"{text}" in {verse_of(db, word)} is {number} but points to {entity}, a {family}'))
    return found


def facts(db: sqlite3.Connection, units: list[str]) -> list[Finding]:
    return relationships(db, units) + dates(db, units)


def relationships(db: sqlite3.Connection, units: list[str]) -> list[Finding]:
    """Two entities joined by more than one family kind, such as both spouses and siblings, with evidence in these chapters."""
    spans = [scope_span(db, scope) for scope in units]
    found = []
    pairs = defaultdict(set)
    where = {}
    for first, last in spans:
        for subject, kind, object, word in db.execute(
            "select r.subject_id, r.kind_id, r.object_id, min(v.first_word_id) from relationship r join relationship_evidence v on v.relationship_id = r.id "
            "where v.first_word_id between ? and ? group by r.id",
            (first, last),
        ):
            if kind in FAMILY:
                key = tuple(sorted((subject, object)))
                pairs[key].add(kind)
                where.setdefault(key, word)
    for a, b in pairs:
        stored = {kind for (kind,) in db.execute("select kind_id from relationship where min(subject_id, object_id) = ? and max(subject_id, object_id) = ?", (a, b))}
        family = sorted(stored & set(FAMILY))
        if len(family) > 1:
            found.append(Finding("relationships", scope_of(db, where[(a, b)]), f"{a} and {b} are stored as {' and '.join(family)}. Check which the text says"))
    return found


def dates(db: sqlite3.Connection, units: list[str]) -> list[Finding]:
    """A passage dated before the passage dated just ahead of it in the same book and counting system."""
    found = []
    by_book = defaultdict(list)
    for scope in units:
        by_book[split_chapter(scope)[0]].append(scope)
    for book, scopes in by_book.items():
        first, last = scope_span(db, scopes[0])[0], scope_span(db, scopes[-1])[1]
        previous = {}
        for word, system, start, end in db.execute(
            "select first_word_id, system_id, from_year, to_year from date where first_word_id between ? and ? order by first_word_id", (first, last)
        ):
            before = previous.get(system)
            if before and end < before[1]:
                found.append(Finding("dates", scope_of(db, word), f"{verse_of(db, word)} is dated {start} to {end} in {system}, before {verse_of(db, before[0])} just ahead of it, dated from {before[1]}. Check both"))
            previous[system] = (word, start)
    return found


def links(db: sqlite3.Connection, units: list[str]) -> list[Finding]:
    """A link whose two passages overlap."""
    found = []
    for scope in units:
        first, last = scope_span(db, scope)
        for kind, a, b, c, d in db.execute(
            "select kind_id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id from passage_link "
            "where from_first_word_id between ? and ? and to_first_word_id <= from_last_word_id and from_first_word_id <= to_last_word_id",
            (first, last),
        ):
            found.append(Finding("links", scope, f"a {kind} link from {verse_of(db, a)} overlaps its own target {verse_of(db, c)}"))
    return found


CHECKS = {"entities": entities, "people": people, "facts": facts, "links": links, "pronouns": pronouns}


def heading(db: sqlite3.Connection, finding: Finding) -> str:
    from .layers import LAYERS

    layer = LAYERS[finding.layer]
    return f"{finding.layer}: {layer.label(db, finding.scope)}" if finding.scope else finding.layer

