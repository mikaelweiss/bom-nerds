"""Turns the verse references and quotes agents write into word id ranges, and word id ranges back into them."""

import re
import sqlite3
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from itertools import accumulate

SHAPES = """A passage takes one of these shapes:
{ "verse": "1 Nephi 3:7", "quote": "Nephi" }
{ "verse": "1 Nephi 3:7", "quote": "I", "in": "I will go" }
{ "verse": "1 Nephi 3:7" }
{ "from": "Alma 32:21", "to": "Alma 32:43" }
{ "from": "Mosiah 2:9", "to": "Mosiah 5:15", "starts": "My brethren", "ends": "Amen" }
{ "chapter": "Alma 32" }
"starts" and "ends" take "starts_in" and "ends_in" the way "quote" takes "in", when their words appear more than once in the verse."""

KEYS = [
    {"verse", "quote"},
    {"verse", "quote", "in"},
    {"verse"},
    *({"from", "to"} | starts | ends for starts in (set(), {"starts"}, {"starts", "starts_in"}) for ends in (set(), {"ends"}, {"ends", "ends_in"})),
    {"chapter"},
]

ALIASES = {
    "d&c": "doctrine-and-covenants",
    "js-m": "joseph-smith-matthew",
    "js-h": "joseph-smith-history",
    "psalm": "psalms",
}

SHORT_NAMES = {"doctrine-and-covenants": "D&C"}

EXAMPLE = 'Write one like "1 Nephi 3:7" or "Alma 32".'
JOINERS = "'\u2019-"
CACHED_CONNECTIONS = 4
CACHED_CHAPTERS = 512


class Rejected(Exception):
    """An answer the agent must fix. str(error) is a message the agent can act on."""


def key(text: str) -> str:
    """The letters, marks, and digits of `text`, folded for comparison, keeping apostrophes and hyphens inside a word."""
    return "".join(letters(fold(text)))


def fold(text: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", text).casefold())


def letters(folded: str) -> list[str]:
    """What each character of folded text counts as in a match: itself, or nothing for punctuation and spacing."""
    kept = []
    for i, char in enumerate(folded):
        if is_letter(char):
            kept.append(char)
        elif char in JOINERS and 0 < i < len(folded) - 1 and is_letter(folded[i - 1]) and is_letter(folded[i + 1]):
            kept.append("-" if char == "-" else "'")
        else:
            kept.append("")
    return kept


def is_letter(char: str) -> bool:
    return char == "_" or unicodedata.category(char)[0] in "LMN"


@dataclass
class Verse:
    reference: str
    ids: list[int]
    words: list[tuple[str, str, str]]

    def __post_init__(self):
        pieces = [fold(piece) for word in self.words for piece in word]
        kept = letters("".join(pieces))
        self.stream = "".join(kept)
        offsets = list(accumulate(map(len, kept), initial=0))
        self.starts, self.ends = [], []
        self.first_at, self.last_at = {}, {}
        position = 0
        for i in range(len(self.words)):
            before, text, after = pieces[3 * i:3 * i + 3]
            position += len(before)
            self.starts.append(offsets[position])
            position += len(text)
            self.ends.append(offsets[position])
            position += len(after)
            if self.starts[i] < self.ends[i]:
                self.first_at.setdefault(self.starts[i], i)
                self.last_at[self.ends[i]] = i

    @property
    def text(self) -> str:
        return "".join(b + t + a for b, t, a in self.words)

    def find(self, words: str) -> list[tuple[int, int]]:
        """Every run of whole words whose letters are exactly those of `words`, as (first, last) indexes."""
        return self.find_key(key(words))

    def find_key(self, wanted: str) -> list[tuple[int, int]]:
        found = []
        start = self.stream.find(wanted) if wanted else -1
        while start >= 0:
            end = start + len(wanted)
            if start in self.first_at and end in self.last_at:
                found.append((self.first_at[start], self.last_at[end]))
            start = self.stream.find(wanted, start + 1)
        return found

    def unique(self, first: int, last: int) -> bool:
        """Whether words first through last match nowhere else in the verse."""
        return self.find_key(self.stream[self.starts[first]:self.ends[last]]) == [(first, last)]

    def printed(self, first: int, last: int) -> str:
        """Words first through last as printed, without the punctuation outside them."""
        run = self.words[first:last + 1]
        joined = "".join(b + t + a for b, t, a in run)
        return re.sub(r"\s+", " ", joined[len(run[0][0]):len(joined) - len(run[-1][2])])


@dataclass
class Chapter:
    verses: dict[int, Verse]

    @property
    def first(self) -> int:
        return next(iter(self.verses.values())).ids[0]

    @property
    def last(self) -> int:
        return next(reversed(self.verses.values())).ids[-1]


@dataclass
class Cache:
    names: dict[str, str]
    lookup: dict[str, str]
    editions: dict[str, set[str]]
    english: dict[str, str]
    chapter_numbers: dict[tuple[str, str], list[int]] = field(default_factory=dict)
    chapters: OrderedDict = field(default_factory=OrderedDict)


connections: OrderedDict = OrderedDict()


def cache(db: sqlite3.Connection) -> Cache:
    if db in connections:
        connections.move_to_end(db)
        return connections[db]
    names = dict(db.execute("select id, name from book"))
    lookup = {book_key(name): book for book, name in names.items()}
    lookup.update({alias: book for alias, book in ALIASES.items() if book in names})
    editions = {}
    for edition, book in db.execute("select edition_id, book_id from edition_book"):
        editions.setdefault(book, set()).add(edition)
    english = dict(db.execute("select eb.book_id, e.id from edition_book eb join edition e on e.id = eb.edition_id where e.language = 'en'"))
    connections[db] = Cache(names, lookup, editions, english)
    while len(connections) > CACHED_CONNECTIONS:
        connections.popitem(last=False)
    return connections[db]


def book_key(name: str) -> str:
    name = re.sub("\\s*[-\u2013\u2014]\\s*", "-", name.strip().casefold())
    name = re.sub(r"\s*&\s*", "&", name)
    return re.sub(r"\s+", " ", name)


def book_name(db, book_id: str) -> str:
    return SHORT_NAMES.get(book_id) or cache(db).names[book_id]


def english_edition(db, book_id: str) -> str:
    """The English edition of the book's work."""
    return cache(db).english[book_id]


def reference(db, book_id: str, chapter: int, verse: int | None = None) -> str:
    """The reference as people write it, like "1 Nephi 3:7" or "D&C 76"."""
    name = book_name(db, book_id)
    return f"{name} {chapter}" if verse is None else f"{name} {chapter}:{verse}"


def parse_reference(db, text: str) -> tuple[str, int, int | None]:
    """Read "1 Nephi 3:7" as ("1-nephi", 3, 7) and "Alma 32" as ("alma", 32, None), checked against the English edition."""
    book, chapter, verse = parse(db, text)
    check(db, english_edition(db, book), book, chapter, verse)
    return book, chapter, verse


def parse(db, text: str) -> tuple[str, int, int | None]:
    """Read a reference without checking that its chapter and verse exist."""
    if not isinstance(text, str):
        raise Rejected(f"{text!r} is not a reference. {EXAMPLE}")
    books = cache(db).lookup
    match = re.fullmatch(r"\s*(.+)\s+(\d+)(?:\s*:\s*(\d+))?\s*", text)
    if match and book_key(match.group(1)) in books:
        name, chapter, verse = match.groups()
        return books[book_key(name)], int(chapter), None if verse is None else int(verse)
    if book_key(text) in books:
        raise Rejected(f'"{text.strip()}" needs a chapter, like "{reference(db, books[book_key(text)], 1)}".')
    if match:
        raise Rejected(f'Unknown book "{match.group(1).strip()}" in "{text}". Use a book name as printed, like "1 Nephi", "D&C", or "Psalms".')
    raise Rejected(f'"{text}" is not a reference. {EXAMPLE}')


def check(db, edition: str, book_id: str, chapter: int, verse: int | None):
    """Reject a chapter or verse the edition does not have."""
    numbers = chapter_numbers(db, edition, book_id)
    if chapter not in numbers:
        raise Rejected(f"{reference(db, book_id, chapter)} does not exist. {book_name(db, book_id)} has chapters {numbers[0]} to {numbers[-1]}.")
    verses = load(db, edition, book_id, chapter).verses
    if verse is not None and verse not in verses:
        raise Rejected(f"{reference(db, book_id, chapter, verse)} does not exist. {reference(db, book_id, chapter)} has verses {min(verses)} to {max(verses)}.")


def chapter_numbers(db, edition: str, book_id: str) -> list[int]:
    numbers = cache(db).chapter_numbers
    if (edition, book_id) not in numbers:
        found = []
        chapter = -1
        while row := db.execute(
            "select chapter from word where edition_id = ? and book_id = ? and chapter > ? order by chapter limit 1", (edition, book_id, chapter)
        ).fetchone():
            chapter = row[0]
            found.append(chapter)
        numbers[(edition, book_id)] = found
    return numbers[(edition, book_id)]


def load(db, edition: str, book_id: str, chapter: int) -> Chapter:
    chapters = cache(db).chapters
    wanted = (edition, book_id, chapter)
    if wanted in chapters:
        chapters.move_to_end(wanted)
        return chapters[wanted]
    grouped = {}
    for verse, word_id, before, text, after in db.execute(
        "select verse, id, before, text, after from word where edition_id = ? and book_id = ? and chapter = ? order by verse, position",
        (edition, book_id, chapter),
    ):
        ids, words = grouped.setdefault(verse, ([], []))
        ids.append(word_id)
        words.append((before, text, after))
    chapters[wanted] = Chapter({v: Verse(reference(db, book_id, chapter, v), ids, words) for v, (ids, words) in grouped.items()})
    while len(chapters) > CACHED_CHAPTERS:
        chapters.popitem(last=False)
    return chapters[wanted]


def verse_of(db, edition: str, book_id: str, chapter: int, verse: int) -> Verse:
    check(db, edition, book_id, chapter, verse)
    return load(db, edition, book_id, chapter).verses[verse]


def verse_text(db, edition: str, book_id: str, chapter: int, verse: int) -> str:
    """The verse exactly as printed."""
    return verse_of(db, edition, book_id, chapter, verse).text


def chapter_verses(db, edition: str, book_id: str, chapter: int) -> list[tuple[int, str]]:
    """Every verse of a chapter as (verse number, text), verse 0 included when present."""
    check(db, edition, book_id, chapter, None)
    return [(number, verse.text) for number, verse in load(db, edition, book_id, chapter).verses.items()]


def chapter_span(db, edition: str, book_id: str, chapter: int) -> tuple[int, int]:
    """The first and last word id of a chapter."""
    check(db, edition, book_id, chapter, None)
    found = load(db, edition, book_id, chapter)
    return found.first, found.last


def locate(db, word_id: int) -> tuple[str, str, int, int]:
    """The (edition, book id, chapter, verse) a word sits in."""
    row = db.execute("select edition_id, book_id, chapter, verse from word where id = ?", (word_id,)).fetchone()
    if row is None:
        raise ValueError(f"no word {word_id}")
    return row


def resolve(db, passage: dict, edition: str | None = None) -> tuple[int, int]:
    """The first and last word id of a passage, in the English edition of its book unless `edition` names another."""
    if not isinstance(passage, dict) or set(passage) not in KEYS:
        keys = ", ".join(f'"{k}"' for k in passage) if isinstance(passage, dict) else ""
        raise Rejected(f"A passage with {keys or 'no keys'} is not one of the shapes. {SHAPES}")
    for k, value in passage.items():
        if not isinstance(value, str) or not value.strip():
            raise Rejected(f'"{k}" must be text. {SHAPES}')

    if "chapter" in passage:
        book, chapter, verse = parse(db, passage["chapter"])
        if verse is not None:
            raise Rejected(f'"chapter" takes a chapter alone, like "{reference(db, book, chapter)}", not "{passage["chapter"]}". For one verse use "verse".')
        return chapter_span(db, edition_for(db, book, edition), book, chapter)

    if "verse" in passage:
        verse = verse_at(db, passage["verse"], "verse", edition)
        if "quote" not in passage:
            return verse.ids[0], verse.ids[-1]
        first, last = pick(verse, passage, "quote", "in")
        return verse.ids[first], verse.ids[last]

    start = verse_at(db, passage["from"], "from", edition)
    end = verse_at(db, passage["to"], "to", edition, parse(db, passage["from"])[0])
    first = pick(start, passage, "starts", "starts_in")[0] if "starts" in passage else 0
    last = pick(end, passage, "ends", "ends_in")[1] if "ends" in passage else len(end.ids) - 1
    if start.ids[first] > end.ids[last]:
        if start.reference == end.reference:
            raise Rejected(f'The passage runs backward: "ends" "{passage["ends"]}" comes before "starts" "{passage["starts"]}" in {start.reference}.')
        raise Rejected(f'The passage runs backward: "to" {end.reference} comes before "from" {start.reference}.')
    return start.ids[first], end.ids[last]


def edition_for(db, book_id: str, edition: str | None) -> str:
    if edition is None:
        return english_edition(db, book_id)
    if edition not in cache(db).editions.get(book_id, ()):
        raise Rejected(f"{book_name(db, book_id)} is not in the {edition} edition.")
    return edition


def verse_at(db, text: str, k: str, edition: str | None, same_book: str | None = None) -> Verse:
    book, chapter, verse = parse(db, text)
    if verse is None:
        raise Rejected(f'"{k}" takes a verse, like "{reference(db, book, chapter, 1)}", not "{text}".')
    if same_book is not None and book != same_book:
        raise Rejected(f'"from" and "to" must be in one book, but {book_name(db, same_book)} and {book_name(db, book)} differ. Split the passage where the book ends.')
    return verse_of(db, edition_for(db, book, edition), book, chapter, verse)


def pick(verse: Verse, passage: dict, k: str, within: str) -> tuple[int, int]:
    """The run of words `passage[k]` names in the verse, narrowed by `passage[within]` when it repeats."""
    if within not in passage:
        return only(verse, passage[k], k, f'Add "{within}" with longer words around the ones you mean.')
    low, high = only(verse, passage[within], within, f'Make "{within}" longer so it appears once.')
    inside = [(f, l) for f, l in verse.find(passage[k]) if low <= f and l <= high]
    if len(inside) != 1:
        raise Rejected(
            f'"{within}" "{passage[within]}" holds "{k}" "{passage[k]}" {times(len(inside))}, but must hold it once. '
            f"{verse.reference} reads:\n{verse.text}"
        )
    return inside[0]


def only(verse: Verse, words: str, k: str, fix: str) -> tuple[int, int]:
    """The one run of the verse's words that matches, or a rejection the agent can act on."""
    if not key(words):
        raise Rejected(f'"{k}" "{words}" has no words in it. Copy words from {verse.reference}, which reads:\n{verse.text}')
    found = verse.find(words)
    if not found:
        raise Rejected(f'"{k}" "{words}" is not in {verse.reference}. Copy words from the verse, which reads:\n{verse.text}')
    if len(found) > 1:
        raise Rejected(f'"{k}" "{words}" appears {times(len(found))} in {verse.reference}. {fix} The verse reads:\n{verse.text}')
    return found[0]


def times(n: int) -> str:
    return {0: "no times", 1: "once", 2: "twice"}.get(n, f"{n} times")


def render(db, first: int, last: int) -> dict:
    """The shortest passage that resolves back to exactly words first through last."""
    if first > last:
        raise ValueError(f"word {first} comes after word {last}")
    edition, book, chapter, verse = locate(db, first)
    last_edition, last_book, last_chapter, last_verse = locate(db, last)
    if (edition, book) != (last_edition, last_book):
        raise ValueError(f"words {first} and {last} are not in one book of one edition")
    start = load(db, edition, book, chapter).verses[verse]
    end = load(db, edition, book, last_chapter).verses[last_verse]
    i, j = start.ids.index(first), end.ids.index(last)
    whole_start, whole_end = i == 0, j == len(end.ids) - 1
    one_verse = (chapter, verse) == (last_chapter, last_verse)

    if chapter == last_chapter and (first, last) == chapter_span(db, edition, book, chapter):
        return {"chapter": reference(db, book, chapter)}
    if whole_start and whole_end:
        return {"verse": start.reference} if one_verse else {"from": start.reference, "to": end.reference}
    if one_verse:
        inside = quoted(start, i, j)
        if inside:
            return inside
    passage = {"from": start.reference, "to": end.reference}
    if not whole_start:
        passage |= edge(start, [(i, k) for k in range(i, len(start.ids))], "starts", "starts_in", first)
    if not whole_end:
        passage |= edge(end, [(k, j) for k in range(j, -1, -1)], "ends", "ends_in", last)
    return passage


def edge(verse: Verse, runs: list[tuple[int, int]], k: str, within: str, word: int) -> dict:
    """The shortest run that pins the passage's edge: unique alone, or else with a window that makes it unique."""
    for first, last in runs:
        if verse.unique(first, last):
            return {k: verse.printed(first, last)}
    for first, last in runs:
        inside = quoted(verse, first, last)
        if inside:
            return {k: inside["quote"], within: inside["in"]}
    raise ValueError(f"word {word} cannot be pointed at in {verse.reference}")


def quoted(verse: Verse, first: int, last: int) -> dict | None:
    """Words first through last as a quote, with "in" when the quote alone appears more than once."""
    quote = verse.printed(first, last)
    if verse.unique(first, last):
        return {"verse": verse.reference, "quote": quote}
    for low, high in windows(first, last, len(verse.ids)):
        if verse.unique(low, high):
            inside = [(f, l) for f, l in verse.find(quote) if low <= f and l <= high]
            if inside == [(first, last)]:
                return {"verse": verse.reference, "quote": quote, "in": verse.printed(low, high)}
    return None


def windows(first: int, last: int, length: int):
    """Runs of words around first through last: grown one word at a time on alternating sides, then every other run, shortest first."""
    grown = []
    low, high = first, last
    grow_right = True
    while low > 0 or high < length - 1:
        if grow_right and high < length - 1 or low == 0:
            high += 1
        else:
            low -= 1
        grow_right = not grow_right
        grown.append((low, high))
    yield from grown
    for size in range(last - first + 2, length + 1):
        for low in range(max(0, last - size + 1), min(first, length - size) + 1):
            if (low, low + size - 1) not in grown:
                yield low, low + size - 1
