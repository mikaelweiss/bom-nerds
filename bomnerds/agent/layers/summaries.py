"""Summaries: short study summaries of a chapter, a verse range, or a book, one kind at a time.

A scope is kind/book/chapter, kind/range/range-id, or kind/book. Verse ranges are chosen by a person with the range commands.
"""

import json
import re
import sqlite3

from ...passages import Rejected, book_key, book_name, cache, chapter_numbers, chapter_span, chapter_verses, english_edition, locate, parse_reference, reference, resolve
from ..jobs import CLI, Job
from ..layer import Layer, Problems, chapter_scopes, kinds, passage_of, split_chapter, where

CHAPTER_WORDS = (15, 120)
BOOK_WORDS = (50, 250)
RANGE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SENTENCE_END = re.compile(r"[.?!][\"'”’)]*$")
VERSES_LISTED = 3

INSTRUCTIONS = """
Write study summaries: each section is one kind, for one chapter, verse range, or book. The kind, what it covers, and the target are under This job in each section.

- Write from a Latter-day Saint perspective, in plain modern English and full sentences. Capitalize pronouns for God: "His commandments".
- A chapter or verse range gets a few sentences. A book gets one paragraph. Write prose: no lists, headings, or line breaks.
- Cover only what the kind covers, and only what this passage holds. Name verses the way people write them: 1 Nephi 3:7.
- Write from the scripture text shown here. The speeches beside it show who is speaking to whom. Where the kind needs background the text does not give, such as setting or culture, use only well-established facts and leave out anything you are unsure of.
- Never copy or paraphrase the Church's chapter summaries, section headings, footnotes, or other study helps, even from memory. Write in your own words, quoting the text only briefly.
- When the passage holds nothing of this kind, such as no prophecy at all, leave the section empty rather than stretching.

Answer each section with one object, its kind and target exactly as This job gives them:

{ "kind": "doctrine", "on": { "chapter": "1 Nephi 17" },
  "text": "The Lord gives strength and a way forward to people who keep His commandments. He guides the faithful the same way He led Israel out of Egypt. People who keep rejecting His word slowly lose the ability to feel the Spirit." }
"""


class Summaries(Layer):
    name = "summaries"
    step = 9
    scope = "kind per chapter, range, or book"
    points = False
    # Speeches say who is talking. Every other layer's tags would bury the text.
    sees = ("speakers",)
    instructions = INSTRUCTIONS

    def scopes(self, db):
        """Chapter and range jobs first, then book jobs, each only for the kinds that apply to its work."""
        kind_works = list(db.execute("select id, work_id from summary_kind order by rowid"))
        works = dict(db.execute("select id, work_id from book"))
        chapters = chapter_scopes(db)
        ranges = db.execute(
            "select r.id, e.work_id from verse_range r join word w on w.id = r.first_word_id join edition e on e.id = w.edition_id order by r.first_word_id"
        ).fetchall()

        def applying(work):
            return [kind for kind, only in kind_works if only in (None, work)]

        books = dict.fromkeys(split_chapter(chapter)[0] for chapter in chapters)
        return (
            [f"{kind}/{chapter}" for chapter in chapters for kind in applying(works[split_chapter(chapter)[0]])]
            + [f"{kind}/range/{range_id}" for range_id, work in ranges for kind in applying(work)]
            + [f"{kind}/{book}" for book in books for kind in applying(works[book])]
        )

    def chapters(self, db, scope):
        _, book, chapter, range_id = target(scope)
        if chapter is not None:
            return [(book, chapter)]
        if range_id is not None:
            first, last = range_span(db, range_id)
            _, book, start, _ = locate(db, first)
            end = locate(db, last)[2]
            return [(book, number) for number in chapter_numbers(db, english_edition(db, book), book) if start <= number <= end]
        return [(book, number) for number in chapter_numbers(db, english_edition(db, book), book)]

    def label(self, db, scope):
        kind, book, chapter, range_id = target(scope)
        name = db.execute("select name from summary_kind where id = ?", (kind,)).fetchone()[0]
        if chapter is not None:
            return f"{name}: {reference(db, book, chapter)}"
        if range_id is not None:
            return f"{name}: {range_id}"
        return f"{name}: {book_name(db, book)}"

    def text_chapters(self, db, scope):
        _, _, chapter, range_id = target(scope)
        return self.chapters(db, scope) if chapter is not None or range_id is not None else []

    def extra(self, db, jobs, scope, batch=()):
        kind, book, chapter, range_id = target(scope)
        name, description = db.execute("select name, description from summary_kind where id = ?", (kind,)).fetchone()
        answer = json.dumps([{"kind": kind, "on": on_of(db, book, chapter, range_id), "text": "..."}], ensure_ascii=False)
        low, high = limits(chapter, range_id)
        if chapter is not None:
            where = f"{reference(db, book, chapter)}, a chapter. Write a few sentences: {low} to {high} words."
        elif range_id is not None:
            range_name, first, last = db.execute("select name, first_word_id, last_word_id from verse_range where id = ?", (range_id,)).fetchone()
            passage = json.dumps(passage_of(db, first, last), ensure_ascii=False)
            where = f"the verse range {range_name}, {passage}. Summarize only the verses inside it. The chapters it touches are shown in full above. Write a few sentences: {low} to {high} words."
        else:
            where = f"the book {book_name(db, book)}. Write one paragraph: {low} to {high} words. Below are its chapters, each with the {name} summary another session wrote for it."
        job = f"## This job\n\nKind: {name}. {description}\nTarget: {where}\nAnswer: {answer}"
        if chapter is None and range_id is None:
            return f"{job}\n\n{book_chapters(db, kind, name, book)}"
        if kind == "original_words":
            return f"{job}\n\n" + original_words(db, *span_of(db, book, chapter, range_id))
        return job

    def parse(self, db, scope, answer):
        kind, book, chapter, range_id = target(scope)
        problems = Problems(db)
        items = problems.items(answer)
        if len(items) > 1:
            problems.add(f"answer with one summary, or leave the section empty when the passage holds nothing of this kind. This answer has {len(items)}")
        tags = []
        for number, item in enumerate(items, 1):
            problems.at(where(number, item))
            if not problems.fields(item, ("kind", "on", "text")):
                continue
            before = len(problems.messages)
            if item["kind"] != kind:
                problems.add(f'kind must be "{kind}", the kind this job writes')
            if not names_target(db, item["on"], book, chapter, range_id):
                problems.add(f'"on" must be {json.dumps(on_of(db, book, chapter, range_id), ensure_ascii=False)}, the target of this job')
            text = text_of(problems, item["text"], chapter, range_id)
            if len(problems.messages) == before:
                tags.append((kind, book, chapter, range_id, text))
        problems.raise_any()
        return tags

    def render(self, db, tag):
        kind, book, chapter, range_id, text = tag
        return {"kind": kind, "on": on_of(db, book, chapter, range_id), "text": text}

    def store(self, db, scope, tags):
        db.executemany("insert into summary (kind_id, book_id, chapter, range_id, text) values (?, ?, ?, ?, ?)", tags)

    def unstore(self, db, scope, tags):
        db.executemany("delete from summary where kind_id = ? and book_id is ? and chapter is ? and range_id is ? and text = ?", tags)

    def commands(self, subparsers):
        command = subparsers.add_parser("range-add", help="add a verse range for summaries, as a person chose it")
        command.add_argument("id", help="such as king-benjamins-sermon")
        command.add_argument("--name", required=True, help="such as \"King Benjamin's sermon\"")
        command.add_argument("--passage", required=True, help='a passage as agents write it, such as \'{"from": "Mosiah 2:9", "to": "Mosiah 5:15"}\'')
        command.set_defaults(run=self.add_range)

        command = subparsers.add_parser("ranges", help="list the verse ranges for summaries")
        command.set_defaults(run=self.list_ranges)

        command = subparsers.add_parser("range-remove", help="remove a verse range that has no summaries")
        command.add_argument("id")
        command.set_defaults(run=self.remove_range)

    def add_range(self, db, args):
        if not RANGE_ID.fullmatch(args.id):
            raise Rejected("a range id is lowercase letters and digits joined by hyphens, such as king-benjamins-sermon")
        if db.execute("select 1 from verse_range where id = ?", (args.id,)).fetchone():
            raise Rejected(f"{args.id} is a range already. Remove it first to change it")
        name = args.name.strip()
        if not name:
            raise Rejected("the name is empty")
        try:
            passage = json.loads(args.passage)
        except json.JSONDecodeError as error:
            raise Rejected(f"the passage is not valid JSON: {error}")
        first, last = resolve(db, passage)
        _, book, chapter, _ = locate(db, first)
        if (first, last) == chapter_span(db, english_edition(db, book), book, chapter):
            raise Rejected(f"that passage is all of {reference(db, book, chapter)}, which has chapter summaries. A range crosses or splits chapters")
        same = db.execute("select id from verse_range where first_word_id = ? and last_word_id = ?", (first, last)).fetchone()
        if same:
            raise Rejected(f"{same[0]} covers the same passage")
        with db:
            db.execute("insert into verse_range (id, name, first_word_id, last_word_id) values (?, ?, ?, ?)", (args.id, name, first, last))
        print(f"added {args.id}: {name}, {json.dumps(passage_of(db, first, last), ensure_ascii=False)}")

    def list_ranges(self, db, args):
        rows = db.execute(
            "select r.id, r.name, r.first_word_id, r.last_word_id, count(s.id) from verse_range r left join summary s on s.range_id = r.id group by r.id order by r.first_word_id"
        ).fetchall()
        for range_id, name, first, last, count in rows:
            print(f"{range_id}\t{name}\t{json.dumps(passage_of(db, first, last), ensure_ascii=False)}\t{count} summaries")
        if not rows:
            print("no verse ranges")

    def remove_range(self, db, args):
        if not db.execute("select 1 from verse_range where id = ?", (args.id,)).fetchone():
            raise Rejected(f"no range {args.id!r}. List them with: {CLI} ranges")
        stored = [f"{self.name}/{kind}/range/{args.id}" for (kind,) in db.execute("select kind_id from summary where range_id = ? order by kind_id", (args.id,))]
        answered = [job.id for kind in kinds(db, "summary_kind") if any((job := Job(self, f"{kind}/range/{args.id}")).path.glob("*.json"))]
        if stored or answered:
            raise Rejected(f"{args.id} has summaries in {', '.join(stored or answered)}. Reset the session that wrote them first")
        with db:
            db.execute("delete from verse_range where id = ?", (args.id,))
        print(f"removed {args.id}")


def target(scope: str) -> tuple[str, str | None, int | None, str | None]:
    """A scope as (kind, book, chapter, range id): the book alone for a book job, the range id alone for a range job."""
    kind, rest = scope.split("/", 1)
    if rest.startswith("range/"):
        return kind, None, None, rest.removeprefix("range/")
    if "/" in rest:
        book, chapter = split_chapter(rest)
        return kind, book, chapter, None
    return kind, rest, None, None


def range_span(db: sqlite3.Connection, range_id: str) -> tuple[int, int]:
    return db.execute("select first_word_id, last_word_id from verse_range where id = ?", (range_id,)).fetchone()


def span_of(db: sqlite3.Connection, book: str | None, chapter: int | None, range_id: str | None) -> tuple[int, int]:
    if range_id is not None:
        return range_span(db, range_id)
    return chapter_span(db, english_edition(db, book), book, chapter)


def limits(chapter: int | None, range_id: str | None) -> tuple[int, int]:
    return BOOK_WORDS if chapter is None and range_id is None else CHAPTER_WORDS


def on_of(db: sqlite3.Connection, book: str | None, chapter: int | None, range_id: str | None) -> dict:
    if range_id is not None:
        return {"range": range_id}
    if chapter is not None:
        return {"chapter": reference(db, book, chapter)}
    return {"book": book_name(db, book)}


def names_target(db: sqlite3.Connection, on, book: str | None, chapter: int | None, range_id: str | None) -> bool:
    if not isinstance(on, dict) or len(on) != 1 or not isinstance(next(iter(on.values())), str):
        return False
    (field, value), = on.items()
    if range_id is not None:
        return field == "range" and value.strip() == range_id
    if chapter is not None:
        try:
            return field == "chapter" and parse_reference(db, value) == (book, chapter, None)
        except Rejected:
            return False
    return field == "book" and cache(db).lookup.get(book_key(value)) == book


def text_of(problems: Problems, text, chapter: int | None, range_id: str | None) -> str | None:
    if not isinstance(text, str):
        problems.add("text must be a string")
        return None
    text = re.sub(r"[ \t]+", " ", text.strip())
    low, high = limits(chapter, range_id)
    words = len(text.split())
    if "\n" in text or "\r" in text:
        problems.add("write the text as one paragraph, with no line breaks, lists, or headings")
    if not low <= words <= high:
        problems.add(f"the text has {words} words, but a {'book' if chapter is None and range_id is None else 'chapter or range'} summary has {low} to {high}")
    if text and not SENTENCE_END.search(text):
        problems.add("end the text with a full sentence")
    return text


def book_chapters(db: sqlite3.Connection, kind: str, kind_name: str, book: str) -> str:
    """Each chapter of a book with its own heading, where the text has one, and its summary of this kind."""
    edition = english_edition(db, book)
    lines = [f"## {book_name(db, book)}, chapter by chapter"]
    for number in chapter_numbers(db, edition, book):
        verses = dict(chapter_verses(db, edition, book, number))
        heading = f" Verse 0: {' '.join(verses[0].split())}" if 0 in verses else ""
        row = db.execute("select text from summary where kind_id = ? and book_id = ? and chapter = ?", (kind, book, number)).fetchone()
        lines += ["", f"{reference(db, book, number)} ({len(verses) - (0 in verses)} verses).{heading}", f"{kind_name}: {row[0] if row else 'nothing of this kind.'}"]
    return "\n".join(lines)


def original_words(db: sqlite3.Connection, first: int, last: int) -> str:
    """Each Hebrew or Greek headword behind the KJV words first through last, with its gloss and the words it stands behind."""
    rows = db.execute(
        "select k.id, k.chapter, k.verse, k.text, h.id, h.strongs, h.text, h.gloss from word k "
        "join word_match m on m.word_id = k.id join word o on o.id = m.other_word_id "
        "join word_headword wh on wh.word_id = o.id join headword h on h.id = wh.headword_id "
        "where k.id between ?1 and ?2 and o.edition_id in ('wlc', 'sblgnt') "
        "union all "
        "select k.id, k.chapter, k.verse, k.text, h.id, h.strongs, h.text, h.gloss from word k "
        "join word_match m on m.other_word_id = k.id join word o on o.id = m.word_id "
        "join word_headword wh on wh.word_id = o.id join headword h on h.id = wh.headword_id "
        "where k.id between ?1 and ?2 and o.edition_id in ('wlc', 'sblgnt') "
        "order by 1",
        (first, last),
    )
    headwords: dict[int, tuple[str, list[str], list[str]]] = {}
    for _, chapter, verse, english, headword, strongs, text, gloss in rows:
        label = " ".join(part for part in (strongs, text, f'"{gloss}"' if gloss else None) if part)
        _, renderings, verses = headwords.setdefault(headword, (label, [], []))
        if english not in renderings:
            renderings.append(english)
        if f"{chapter}:{verse}" not in verses:
            verses.append(f"{chapter}:{verse}")
    lines = ["## Hebrew and Greek words behind this text", "", "Each headword with its Strong's number and gloss, the KJV words it stands behind, and the verses."]
    for label, renderings, verses in headwords.values():
        more = f" and {len(verses) - VERSES_LISTED} more" if len(verses) > VERSES_LISTED else ""
        lines.append(f"{label}: {', '.join(renderings)} ({', '.join(verses[:VERSES_LISTED])}{more})")
    return "\n".join(lines) if headwords else "## Hebrew and Greek words behind this text\n\nNone of these words is matched to Hebrew or Greek."


LAYERS = [Summaries()]
