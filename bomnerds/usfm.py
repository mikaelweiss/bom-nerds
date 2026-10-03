"""Reads eBible's KJV USFM: verse text, the words its translators supplied, and the Strong's number on each word."""

import re

from .words import Book, split

BLOCK = re.compile(r"\\(id|h|toc\d|mt\d|c|p|q\d|b|d|s\d|v)(?=\s|$)")
INLINE = re.compile(r"(\\\+?[a-z]+\d?\*?)")
FOOTNOTE = re.compile(r"\\f .*?\\f\*", re.S)
STRONGS = re.compile(r'strong="([HG]\d+)"')
FORMATTING = {"nd", "wj", "tl"}

Char = tuple[str, bool, str | None]


def parse(source: str) -> Book:
    name = None
    chapter = None
    verse = None
    texts: dict[tuple[int, int], list[Char]] = {}
    pending: list[list[Char]] = []

    def flush_into_last_verse():
        # Text after a chapter's last verse, such as an epistle's closing note, ends that verse.
        if pending and verse is not None:
            texts[(chapter, verse)] = join([texts[(chapter, verse)], *pending])
            pending.clear()

    markers = list(BLOCK.finditer(source))
    for marker, following in zip(markers, markers[1:] + [None]):
        tag = marker.group(1)
        content = source[marker.end():following.start() if following else len(source)]
        if tag == "h":
            name = content.strip()
        elif tag.startswith("mt") or tag == "d" or tag.startswith("s"):
            pending.append(inline(content))
        elif tag == "c":
            flush_into_last_verse()
            chapter, verse = int(content.split()[0]), None
        elif tag == "v":
            number, _, rest = content.strip().partition(" ")
            verse = int(number)
            if pending:
                # Headings before verse 1 are verse 0. Headings before a later verse, like Psalm 119's ALEPH, open it.
                if verse == 1:
                    texts[(chapter, 0)] = join(pending)
                    texts[(chapter, verse)] = inline(rest)
                else:
                    texts[(chapter, verse)] = join([*pending, inline(rest)])
                pending.clear()
            else:
                texts[(chapter, verse)] = inline(rest)
        elif tag in ("p", "b") or tag.startswith("q"):
            if content.strip():
                if verse is None:
                    raise ValueError(f"{name} {chapter}: text before the first verse outside a heading")
                texts[(chapter, verse)] = join([texts[(chapter, verse)], inline(content)], " ")
    flush_into_last_verse()

    book = Book(name)
    for key, chars in texts.items():
        text = "".join(c for c, _, _ in chars)
        book.verses[key] = split(text, [s for _, s, _ in chars], [n for _, _, n in chars])
    return book


def join(parts: list[list[Char]], separator: str = "\n") -> list[Char]:
    joined = []
    for part in parts:
        if not part:
            continue
        if joined:
            joined.append((separator, False, None))
        joined.extend(part)
    return joined


def inline(content: str) -> list[Char]:
    """Strip inline markers, keeping each character's supplied flag and Strong's number, with whitespace collapsed."""
    chars: list[Char] = []
    supplied = 0
    word: list[Char] | None = None
    opened = False
    for token in INLINE.split(FOOTNOTE.sub("", content)):
        if not token.startswith("\\"):
            if opened:
                # One space after an opening marker belongs to the marker, not the text.
                token = token.removeprefix(" ")
            target = word if word is not None else chars
            target.extend((c, supplied > 0, None) for c in token)
            opened = False
            continue
        tag = token.lstrip("\\+").rstrip("*")
        closing = token.endswith("*")
        opened = not closing
        if tag == "w":
            if closing:
                text, _, attributes = "".join(c for c, _, _ in word).partition("|")
                found = STRONGS.search(attributes)
                strongs = found.group(1) if found else None
                chars.extend((c, s, strongs) for c, (_, s, _) in zip(text, word))
                word = None
            else:
                word = []
        elif tag == "add":
            supplied += -1 if closing else 1
        elif tag not in FORMATTING:
            raise ValueError(f"unknown USFM marker {token}")
    return collapse(chars)


def collapse(chars: list[Char]) -> list[Char]:
    collapsed: list[Char] = []
    for char in chars:
        if char[0].isspace():
            if collapsed and collapsed[-1][0] != " ":
                collapsed.append((" ", False, None))
        else:
            collapsed.append(char)
    while collapsed and collapsed[-1][0] == " ":
        collapsed.pop()
    return collapsed
