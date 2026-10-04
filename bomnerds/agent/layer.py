"""What every job layer provides, and the checks most layers share.

A layer asks agents one question. It turns an answer into tags, renders tags back into the form an agent writes,
and stores them. Tags are hashable values with passages resolved to word ids, so two answers compare as sets.
"""

import sqlite3
from typing import Any

from ..passages import Rejected, chapter_span, english_edition, parse_reference, reference, render as render_passage, resolve

PILOT = [("1-nephi", 1), ("1-nephi", 2), ("1-nephi", 3), ("2-nephi", 12), ("isaiah", 2), ("mosiah", 2), ("mosiah", 3), ("mosiah", 4), ("mosiah", 5), ("genesis", 5), ("alma", 36), ("doctrine-and-covenants", 76)]

Tag = Any

# Scope sets by connection, since listing every scope of a layer takes a query over the whole text.
# Each entry holds its connection, so its id is never reused while cached.
SCOPES: dict[int, tuple[sqlite3.Connection, dict[str, set[str]]]] = {}


class Layer:
    name: str
    step: int
    # Every scope of one layer is the same kind: "chapter" (book/chapter), "book", or one the layer defines.
    scope: str = "chapter"
    # "compare": two runs and a decider. "check": a writer, then a checker who corrects the writer's answer.
    mode: str = "compare"
    instructions: str
    # Layers of the same step whose job on the same chapter must settle first, such as relationships before the dates placed on them.
    after: tuple[str, ...] = ()
    # False for layers whose answers name no passages or entities, so their prompts leave out how to point at text and search.
    points: bool = True
    # Layers whose tags the job's context shows. None shows every layer from an earlier step.
    sees: tuple[str, ...] | None = None

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

    def ready(self, db: sqlite3.Connection, jobs, scope: str) -> str | None:
        """Why the job cannot start yet, or None when it can.

        A chapter job waits for every chapter job of an earlier step, or named in `after`, on the same chapter, because each step gives the next its context.
        """
        if self.scope != "chapter":
            return None
        from .layers import LAYERS

        for layer in LAYERS.values():
            if (layer.step < self.step or layer.name in self.after) and layer.scope == "chapter" and scope in layer.scope_set(db) and jobs.get(layer.name, scope).settled() is None:
                return f"{layer.name}/{scope} must settle first"
        return None

    def scope_set(self, db: sqlite3.Connection) -> set[str]:
        cached = SCOPES.setdefault(id(db), (db, {}))[1]
        if self.name not in cached:
            cached[self.name] = set(self.scopes(db))
        return cached[self.name]

    def context(self, db: sqlite3.Connection, jobs, scope: str) -> str:
        """What the agent reads beyond the instructions: by default each chapter with the tags earlier layers placed on it."""
        from .show import show

        return "\n\n".join(show(db, book, chapter, layers=self.seen()) for book, chapter in self.chapters(db, scope))

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
            self.add(f"{entity_id!r} is not on the entity list. Search for it, or report it missing")
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


def kinds(db: sqlite3.Connection, table: str) -> list[str]:
    return [row[0] for row in db.execute(f"select id from {table} order by rowid")]


def passage_of(db: sqlite3.Connection, first: int, last: int) -> dict:
    return render_passage(db, first, last)

