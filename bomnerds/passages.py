import re
import sqlite3
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from itertools import accumulate

from .rows import row_id
from .text import WORDS

SHAPES = """A passage takes one of these shapes:
{ "verse": "1 Nephi 3:7", "quote": "Nephi" }
{ "verse": "1 Nephi 3:7", "quote": "I", "in": "I will go" }
{ "verse": "1 Nephi 3:7" }
{ "from": "Alma 32:21", "to": "Alma 32:43" }
{ "from": "Mosiah 2:9", "to": "Mosiah 5:15", "starts": "My brethren", "ends": "Amen" }
{ "chapter": "Alma 32" }
"starts" and "ends" take "starts_in" and "ends_in" the way "quote" takes "in", when their words appear more than once in the verse.
The text printed before a chapter's first verse is its heading, written like "1 Nephi 3 heading"."""

HEADING = "heading"

KEYS = [
    {"verse", "quote"},
    {"verse", "quote", "in"},
    {"verse"},
    *({"from", "to"} | starts | ends for starts in (set(), {"starts"}, {"starts", "starts_in"}) for ends in (set(), {"ends"}, {"ends", "ends_in"})),
    {"chapter"},
]

ALIASES = {
    "d&c": "Doctrine and Covenants",
    "js-m": "Joseph Smith\u2014Matthew",
    "js-h": "Joseph Smith\u2014History",
    "psalm": "Psalms",
}

SHORT_NAMES = {"Doctrine and Covenants": "D&C"}

EXAMPLE = 'Write one like "1 Nephi 3:7" or "Alma 32".'
JOINERS = "'\u2019-"
CACHED_CONNECTIONS = 4
CACHED_CHAPTERS = 512


class Rejected(Exception):
    pass


def key(text: str) -> str:
    return "".join(letters(fold(text)))


def fold(text: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", text).casefold())


def letters(folded: str) -> list[str]:
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
    sequences: list[int]
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
        return self.find_key(self.stream[self.starts[first]:self.ends[last]]) == [(first, last)]

    def printed(self, first: int, last: int) -> str:
        run = self.words[first:last + 1]
        joined = "".join(b + t + a for b, t, a in run)
        return re.sub(r"\s+", " ", joined[len(run[0][0]):len(joined) - len(run[-1][2])])


@dataclass
class Chapter:

    verses: dict[int | str, Verse]

    @property
    def first(self) -> int:
        return next(iter(self.verses.values())).ids[0]

    @property
    def last(self) -> int:
        return next(reversed(self.verses.values())).ids[-1]


@dataclass
class Cache:
    names: dict[int, str]
    lookup: dict[str, int]
    editions: dict[int, set[int]]
    english: dict[int, int]
    edition_names: dict[int, str]
    chapter_numbers: dict[tuple[int, int], list[int]] = field(default_factory=dict)
    chapters: OrderedDict = field(default_factory=OrderedDict)


connections: OrderedDict = OrderedDict()


def cache(db: sqlite3.Connection) -> Cache:
    if db in connections:
        connections.move_to_end(db)
        return connections[db]
    names = dict(db.execute("select id, name from book"))
    lookup = {book_key(name): book for book, name in names.items()}
    lookup.update({alias: lookup[book_key(name)] for alias, name in ALIASES.items() if book_key(name) in lookup})
    editions = {}
    for edition, book in db.execute("select edition_id, book_id from edition_book"):
        editions.setdefault(book, set()).add(edition)
    english = dict(db.execute(
        "select eb.book_id, e.id from edition_book eb join edition e on e.id = eb.edition_id where e.language_id = ?", (row_id(db, "language", "en", "iso_code"),)
    ))
    edition_names = dict(db.execute("select id, name from edition"))
    connections[db] = Cache(names, lookup, editions, english, edition_names)
    while len(connections) > CACHED_CONNECTIONS:
        connections.popitem(last=False)
    return connections[db]


def book_key(name: str) -> str:
    name = re.sub("\\s*[-\u2013\u2014]\\s*", "-", name.strip().casefold())
    name = re.sub(r"\s*&\s*", "&", name)
    return re.sub(r"\s+", " ", name)


def book_name(db, book_id: int) -> str:
    name = cache(db).names[book_id]
    return SHORT_NAMES.get(name, name)


def english_edition(db, book_id: int) -> int:
    return cache(db).english[book_id]


def reference(db, book_id: int, chapter: int, verse: int | str | None = None) -> str:
    name = book_name(db, book_id)
    if verse is None:
        return f"{name} {chapter}"
    return f"{name} {chapter} {HEADING}" if verse == HEADING else f"{name} {chapter}:{verse}"


def parse_reference(db, text: str) -> tuple[int, int, int | str | None]:
    book, chapter, verse = parse(db, text)
    check(db, english_edition(db, book), book, chapter, verse)
    return book, chapter, verse


def parse(db, text: str) -> tuple[int, int, int | str | None]:
    if not isinstance(text, str):
        raise Rejected(f"{text!r} is not a reference. {EXAMPLE}")
    books = cache(db).lookup
    match = re.fullmatch(r"\s*(.+)\s+(\d+)(?:\s*:\s*(\d+)|\s+((?i:heading)))?\s*", text)
    if match and book_key(match.group(1)) in books:
        name, chapter, verse, heading = match.groups()
        return books[book_key(name)], int(chapter), HEADING if heading else None if verse is None else int(verse)
    if book_key(text) in books:
        raise Rejected(f'"{text.strip()}" needs a chapter, like "{reference(db, books[book_key(text)], 1)}".')
    if match:
        raise Rejected(f'Unknown book "{match.group(1).strip()}" in "{text}". Use a book name as printed, like "1 Nephi", "D&C", or "Psalms".')
    raise Rejected(f'"{text}" is not a reference. {EXAMPLE}')


def check(db, edition: int, book_id: int, chapter: int, verse: int | str | None):
    numbers = chapter_numbers(db, edition, book_id)
    if chapter not in numbers:
        raise Rejected(f"{reference(db, book_id, chapter)} does not exist. {book_name(db, book_id)} has chapters {numbers[0]} to {numbers[-1]}.")
    verses = load(db, edition, book_id, chapter).verses
    if verse is not None and verse not in verses:
        numbered = [v for v in verses if v != HEADING]
        raise Rejected(f"{reference(db, book_id, chapter, verse)} does not exist. {reference(db, book_id, chapter)} has verses {min(numbered)} to {max(numbered)}.")


def chapter_numbers(db, edition: int, book_id: int) -> list[int]:
    numbers = cache(db).chapter_numbers
    if (edition, book_id) not in numbers:
        numbers[(edition, book_id)] = [row[0] for row in db.execute(
            "select number from chapter where edition_id = ? and book_id = ? order by number", (edition, book_id)
        )]
    return numbers[(edition, book_id)]


def load(db, edition: int, book_id: int, chapter: int) -> Chapter:
    chapters = cache(db).chapters
    wanted = (edition, book_id, chapter)
    if wanted in chapters:
        chapters.move_to_end(wanted)
        return chapters[wanted]
    grouped = {}
    for verse, word_id, sequence, before, text, after in db.execute(
        f"select v.number, w.id, w.sequence, w.before, w.text, w.after from {WORDS} where c.edition_id = ? and c.book_id = ? and c.number = ? order by w.sequence",
        (edition, book_id, chapter),
    ):
        ids, sequences, words = grouped.setdefault(HEADING if verse is None else verse, ([], [], []))
        ids.append(word_id)
        sequences.append(sequence)
        words.append((before, text, after))
    chapters[wanted] = Chapter({v: Verse(reference(db, book_id, chapter, v), *found) for v, found in grouped.items()})
    while len(chapters) > CACHED_CHAPTERS:
        chapters.popitem(last=False)
    return chapters[wanted]


def verse_of(db, edition: int, book_id: int, chapter: int, verse: int | str) -> Verse:
    check(db, edition, book_id, chapter, verse)
    return load(db, edition, book_id, chapter).verses[verse]


def verse_text(db, edition: int, book_id: int, chapter: int, verse: int | str) -> str:
    return verse_of(db, edition, book_id, chapter, verse).text


def chapter_verses(db, edition: int, book_id: int, chapter: int) -> list[tuple[int | str, str]]:
    check(db, edition, book_id, chapter, None)
    return [(number, verse.text) for number, verse in load(db, edition, book_id, chapter).verses.items()]


def chapter_span(db, edition: int, book_id: int, chapter: int) -> tuple[int, int]:
    check(db, edition, book_id, chapter, None)
    found = load(db, edition, book_id, chapter)
    return found.first, found.last


def locate(db, word_id: int) -> tuple[int, int, int, int | str]:
    row = db.execute(f"select c.edition_id, c.book_id, c.number, v.number from {WORDS} where w.id = ?", (word_id,)).fetchone()
    if row is None:
        raise ValueError(f"no word {word_id}")
    edition, book, chapter, verse = row
    return edition, book, chapter, HEADING if verse is None else verse


def resolve(db, passage: dict, edition: int | None = None) -> tuple[int, int]:
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
    if start.sequences[first] > end.sequences[last]:
        if start.reference == end.reference:
            raise Rejected(f'The passage runs backward: "ends" "{passage["ends"]}" comes before "starts" "{passage["starts"]}" in {start.reference}.')
        raise Rejected(f'The passage runs backward: "to" {end.reference} comes before "from" {start.reference}.')
    return start.ids[first], end.ids[last]


def edition_for(db, book_id: int, edition: int | None) -> int:
    if edition is None:
        return english_edition(db, book_id)
    if edition not in cache(db).editions.get(book_id, ()):
        raise Rejected(f"{book_name(db, book_id)} is not in the {cache(db).edition_names[edition]}.")
    return edition


def verse_at(db, text: str, k: str, edition: int | None, same_book: int | None = None) -> Verse:
    book, chapter, verse = parse(db, text)
    if verse is None:
        raise Rejected(f'"{k}" takes a verse, like "{reference(db, book, chapter, 1)}", not "{text}".')
    if same_book is not None and book != same_book:
        raise Rejected(f'"from" and "to" must be in one book, but {book_name(db, same_book)} and {book_name(db, book)} differ. Split the passage where the book ends.')
    return verse_of(db, edition_for(db, book, edition), book, chapter, verse)


def pick(verse: Verse, passage: dict, k: str, within: str) -> tuple[int, int]:
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
    edition, book, chapter, verse = locate(db, first)
    last_edition, last_book, last_chapter, last_verse = locate(db, last)
    if (edition, book) != (last_edition, last_book):
        raise ValueError(f"words {first} and {last} are not in one book of one edition")
    start = load(db, edition, book, chapter).verses[verse]
    end = load(db, edition, book, last_chapter).verses[last_verse]
    i, j = start.ids.index(first), end.ids.index(last)
    if start.sequences[i] > end.sequences[j]:
        raise ValueError(f"word {first} comes after word {last}")
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
    for first, last in runs:
        if verse.unique(first, last):
            return {k: verse.printed(first, last)}
    for first, last in runs:
        inside = quoted(verse, first, last)
        if inside:
            return {k: inside["quote"], within: inside["in"]}
    raise ValueError(f"word {word} cannot be pointed at in {verse.reference}")


def quoted(verse: Verse, first: int, last: int) -> dict | None:
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
