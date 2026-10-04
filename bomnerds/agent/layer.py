"""What every job layer provides, and the checks most layers share.

A layer asks agents one question. It turns an answer into tags, renders tags back into the form an agent writes,
and stores them. Tags are hashable values with passages resolved to word ids, so two answers compare as sets.
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..passages import Rejected, book_name, chapter_span, english_edition, reference, render as render_passage, resolve

Tag = Any

# Scope sets by connection, since listing every scope of a layer takes a query over the whole text.
# Each entry holds its connection, so its id is never reused while cached.
SCOPES: dict[int, tuple[sqlite3.Connection, dict[str, set[str]]]] = {}

JSON_LINES = "Write one JSON object per line, shaped like the examples above."


@dataclass
class Reading:
    """What an agent wrote for one scope: the items its layer parses, the ones it flagged as unsure, and what it marked as needing no tag."""

    items: list[dict] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    skipped: list[Any] = field(default_factory=list)
    # Names the writer found no entity for, each with the passage that names it.
    unlisted: list[dict] = field(default_factory=list)


class Layer:
    name: str
    step: int
    # Every scope of one layer is the same kind: "chapter" (book/chapter), "book", or one the layer defines.
    scope: str = "chapter"
    # False for layers whose answers name no passages or entities, so their prompts leave out how to point at text and the entity list.
    points: bool = True
    # Layers whose tags the job's context shows. None shows every layer from an earlier step.
    sees: tuple[str, ...] | None = None
    # True when each scope reads what the scope before it stored, so a batch stores its scopes in order and stops at the first that fails.
    ordered: bool = False
    # How an agent writes one scope's answer, shown in every prompt.
    format: str = JSON_LINES

    def scopes(self, db: sqlite3.Connection) -> list[str]:
        """Every scope this layer has a job for, in the order the jobs should run."""
        return chapter_scopes(db)

    def chapters(self, db: sqlite3.Connection, scope: str) -> list[tuple[str, int]]:
        """The chapters a scope covers, which decide whether it is in the pilot set and what its context shows."""
        if self.scope == "chapter":
            return [split_chapter(scope)]
        if self.scope == "book":
            return [(scope, chapter) for (chapter,) in db.execute("select distinct chapter from word where book_id = ? order by chapter", (scope,))]
        raise NotImplementedError(f"{self.name} must say which chapters a {self.scope} scope covers")

    def scope_set(self, db: sqlite3.Connection) -> set[str]:
        cached = SCOPES.setdefault(id(db), (db, {}))[1]
        if self.name not in cached:
            cached[self.name] = set(self.scopes(db))
        return cached[self.name]

    def label(self, db: sqlite3.Connection, scope: str) -> str:
        """The heading of the scope's section, in the prompt and in the answer."""
        if self.scope == "chapter":
            return chapter_name(db, scope)
        if self.scope == "book":
            return book_name(db, scope)
        return scope

    def text_chapters(self, db: sqlite3.Connection, scope: str) -> list[tuple[str, int]]:
        """The chapters whose text the prompt shows for this scope."""
        return self.chapters(db, scope)

    def preamble(self, db: sqlite3.Connection, scopes: list[str]) -> str:
        """What the prompt shows once, before the first scope: lists every scope of a batch shares."""
        return ""

    def extra(self, db: sqlite3.Connection, jobs, scope: str, batch: tuple[str, ...] = ()) -> str:
        """What the agent reads for one scope beyond its chapters' text. batch holds every scope the same prompt shows."""
        return ""

    def read(self, db: sqlite3.Connection, scope: str, lines: list[str]) -> Reading:
        """Turn the lines of one scope's section into the items parse checks. A line ending in "?" is flagged as unsure."""
        reading = Reading()
        problems = Problems(db)
        for number, line in enumerate(lines, 1):
            text, unsure = unflag(line)
            try:
                item = json.loads(text)
            except json.JSONDecodeError as error:
                problems.at(f"line {number}").add(f"not a JSON object: {error.msg}")
                continue
            if not isinstance(item, dict):
                problems.at(f"line {number}").add("each line holds one JSON object")
                continue
            reading.items.append(item)
            if unsure:
                reading.flagged.append(text)
        problems.raise_any()
        return reading

    def complete(self, db: sqlite3.Connection, scope: str, reading: Reading) -> list[str]:
        """Problems with what an answer leaves out, checked when a batch stores it."""
        return []

    def fixed(self, db: sqlite3.Connection, scope: str) -> list[Tag]:
        """Tags a script settles for this scope, shown to the agents as given and stored with their answer."""
        return []

    def given(self, db: sqlite3.Connection, scope: str) -> list[Tag]:
        """Tags of this layer already in the database for this scope from somewhere other than this job, such as a script layer."""
        return []

    def already_shown(self, db: sqlite3.Connection, tags: list[Tag]) -> list[dict]:
        """The settled tags a prompt lists under Already tagged. A layer with hundreds of them lists fewer and says so in its context."""
        return [self.render(db, t) for t in tags]

    def parse(self, db: sqlite3.Connection, scope: str, answer: Any) -> list[Tag]:
        """Check an answer and turn it into tags. Raise Rejected naming every problem found.

        Never reject a tag for being in the database already: parse also reads back answers this job stored.
        """
        raise NotImplementedError

    def render(self, db: sqlite3.Connection, tag: Tag) -> dict:
        """The tag as an agent writes it. parse must read it back as the same tag."""
        raise NotImplementedError

    def store(self, db: sqlite3.Connection, scope: str, tags: list[Tag]):
        raise NotImplementedError

    def unstore(self, db: sqlite3.Connection, scope: str, tags: list[Tag]):
        """Delete exactly the rows store wrote for these tags. Deleting rows already gone is not an error."""
        raise NotImplementedError

    def shown(self, db: sqlite3.Connection, edition: str, book_id: str, chapter: int) -> list[dict]:
        """This layer's tags in one chapter, as an agent writes them, for the show command."""
        return []

    def commands(self, subparsers):
        """Add operator commands this layer needs to the CLI. Each sets `run` to a function taking (db, args)."""

    def seen(self) -> tuple[str, ...]:
        from .layers import LAYERS

        if self.sees is not None:
            return self.sees
        return tuple(layer.name for layer in LAYERS.values() if layer.step < self.step)


def chapter_scopes(db: sqlite3.Connection, works: tuple[str, ...] = ("bible", "bom", "dc", "pgp")) -> list[str]:
    """book/chapter for every chapter of the English editions, in reading order."""
    return [
        f"{book}/{chapter}"
        for book, chapter in db.execute(
            f"select w.book_id, w.chapter from word w join edition e on e.id = w.edition_id "
            f"where e.language = 'en' and e.work_id in ({','.join('?' * len(works))}) group by w.edition_id, w.book_id, w.chapter order by min(w.id)",
            works,
        )
    ]


def split_chapter(scope: str) -> tuple[str, int]:
    book, chapter = scope.rsplit("/", 1)
    return book, int(chapter)


def chapter_name(db: sqlite3.Connection, scope: str) -> str:
    return reference(db, *split_chapter(scope))


def scope_span(db: sqlite3.Connection, scope: str) -> tuple[int, int]:
    """First and last word id of a chapter scope in its English edition."""
    book, chapter = split_chapter(scope)
    return chapter_span(db, english_edition(db, book), book, chapter)


def chapter_words(db: sqlite3.Connection, scope: str) -> list[tuple[int, str]]:
    first, last = scope_span(db, scope)
    return list(db.execute("select id, text from word where id between ? and ? order by id", (first, last)))


def in_chapter(db: sqlite3.Connection, scope: str, first: int, last: int) -> bool:
    start, end = scope_span(db, scope)
    return start <= first and last <= end


class Problems:
    """Collects every problem in an answer, so the agent can fix them all in one try."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.messages: list[str] = []
        self.where = ""

    def at(self, where: str) -> "Problems":
        self.where = where
        return self

    def add(self, message: str):
        self.messages.append(f"{self.where}: {message}" if self.where else message)

    def raise_any(self):
        if self.messages:
            raise Rejected("\n".join(self.messages))

    def items(self, answer: Any, name: str = "item") -> list[dict]:
        """The answer as a list of objects, or a problem when it is not one."""
        if not isinstance(answer, list) or not all(isinstance(item, dict) for item in answer):
            self.add("the answer must be a JSON array of objects")
            self.raise_any()
        return answer

    def fields(self, item: dict, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> bool:
        missing = [key for key in required if key not in item]
        unknown = [key for key in item if key not in required and key not in optional]
        if missing:
            self.add(f"missing {', '.join(missing)}")
        if unknown:
            self.add(f"unknown field {', '.join(unknown)}. Fields: {', '.join(required + optional)}")
        return not missing and not unknown

    def passage(self, passage: Any, edition: str | None = None, within: str | None = None) -> tuple[int, int] | None:
        """Resolve a passage. With `within`, a chapter scope the passage must sit inside."""
        if not isinstance(passage, dict):
            self.add("a passage must be an object")
            return None
        try:
            span = resolve(self.db, passage, edition)
        except Rejected as error:
            self.add(str(error))
            return None
        if within and not in_chapter(self.db, within, *span):
            self.add(f"the passage must sit inside {chapter_name(self.db, within)}")
            return None
        return span

    def entity(self, entity_id: Any, types: tuple[str, ...] | None = None) -> str | None:
        """An entity id on the list, optionally of one of these types or their subtypes."""
        row = self.db.execute("select e.type_id, coalesce(t.parent_id, t.id) from entity e join entity_type t on t.id = e.type_id where e.id = ?", (entity_id,)).fetchone() if isinstance(entity_id, str) else None
        if row is None:
            self.add(f"{entity_id!r} is not on the entity list. Pick one from the list, or write an unlisted line")
            return None
        if types and not {row[0], row[1]} & set(types):
            self.add(f"{entity_id} is a {row[0]}, but this must be a {' or '.join(types)}")
            return None
        return entity_id

    def kind(self, value: Any, allowed: list[str], field: str = "kind") -> str | None:
        if value not in allowed:
            self.add(f"{field} {value!r} is not one of: {', '.join(allowed)}")
            return None
        return value

    def unique(self, tags: list[Tag], render) -> list[Tag]:
        """Reject a fact that appears twice in one answer."""
        seen = set()
        for tag in tags:
            if tag in seen:
                self.at("").add(f"this appears twice: {render(tag)}")
            seen.add(tag)
        return tags


def where(number: int, item: Any) -> str:
    """How a problem names an item: its number, and the verse and quote it points at when it has them."""
    passage = item.get("passage") if isinstance(item, dict) else None
    if isinstance(passage, dict) and "verse" in passage:
        quote = f' "{passage["quote"]}"' if "quote" in passage else ""
        return f"item {number}, {passage['verse']}{quote}"
    return f"item {number}"


def kinds(db: sqlite3.Connection, table: str) -> list[str]:
    return [row[0] for row in db.execute(f"select id from {table} order by rowid")]


def passage_of(db: sqlite3.Connection, first: int, last: int) -> dict:
    return render_passage(db, first, last)



def unflag(line: str) -> tuple[str, bool]:
    """A line without its trailing "?", and whether it had one."""
    text = line.rstrip()
    if text.endswith("?"):
        return text[:-1].rstrip(), True
    return text, False


NUMBERS = re.compile(r"(?:^|\s)(\d+(?:\s*[-,]\s*\d+)*)\s*=")


def numbered(problems: Problems, line: str) -> tuple[str, list[tuple[list[int], str, bool]]] | None:
    """A numbered line, "3:7  1-4=nephi  5=lord?", as its verse key and each group of numbers with its value and whether it is flagged."""
    key, _, rest = line.strip().partition(" ")
    starts = list(NUMBERS.finditer(rest))
    if not starts or rest[: starts[0].start()].strip():
        problems.add('write the verse, then each number with "=" and its answer, such as "3:7  1-2=nephi  3=-"')
        return None
    groups = []
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(rest)
        value, unsure = unflag(rest[match.end():end].strip())
        if not value:
            problems.add(f"{match.group(1)}= has no answer")
            continue
        numbers = []
        for part in re.sub(r"\s+", "", match.group(1)).split(","):
            low, _, high = part.partition("-")
            numbers += list(range(int(low), int(high or low) + 1))
        groups.append((numbers, value, unsure))
    return key, groups


def verse_number(problems: Problems, key: str, chapter: int) -> int | None:
    """The verse of a "3:7" key, which must name this chapter."""
    parts = key.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        problems.add(f'"{key}" must be chapter and verse, such as {chapter}:7')
        return None
    if int(parts[0]) != chapter:
        problems.add(f"{key} is not in chapter {chapter}. Write each line under its own chapter's heading")
        return None
    return int(parts[1])
