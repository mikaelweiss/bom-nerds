import re
from dataclasses import dataclass, field

WORD = re.compile(r"\w+(?:['’-]\w+)*")


@dataclass
class Word:
    text: str
    before: str = ""
    after: str = ""
    supplied: bool = False
    strongs: tuple[str, ...] = ()


@dataclass
class Book:

    name: str
    verses: dict[tuple[int, int | None], list[Word]] = field(default_factory=dict)


def reading_order(key: tuple[int, int | None]) -> tuple[int, bool, int]:
    chapter, verse = key
    return chapter, verse is not None, verse or 0


def split(text: str, supplied: list[bool] | None = None, strongs: list[str | None] | None = None) -> list[Word]:
    matches = list(WORD.finditer(text))
    if not matches:
        raise ValueError(f"no words in {text!r}")
    words = []
    for match in matches:
        start, end = match.span()
        words.append(Word(
            text=match.group(),
            supplied=bool(supplied) and any(supplied[start:end]),
            strongs=tuple(dict.fromkeys(s for s in strongs[start:end] if s)) if strongs else (),
        ))
    words[0].before = text[:matches[0].start()]
    words[-1].after = text[matches[-1].end():]
    for previous, word, gap_start, gap_end in zip(words, words[1:], (m.end() for m in matches), (m.start() for m in matches[1:])):
        gap = text[gap_start:gap_end]
        closing = re.match(r"\S*\s*", gap).end()
        previous.after = gap[:closing]
        word.before = gap[closing:]
    return words


def rebuild(words: list[Word]) -> str:
    return "".join(w.before + w.text + w.after for w in words)
