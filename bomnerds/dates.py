"""Dates the text states in a fixed formula, such as "in the first year of the reign of the judges"."""

import re
import sqlite3
from collections import defaultdict

UNITS = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
ORDINAL_UNITS = "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
ORDINAL_TENS = "twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth ninetieth".split()
NUMBERS = {
    **{w: n for n, w in enumerate(UNITS, 1)}, **{w: n for n, w in enumerate(ORDINAL_UNITS, 1)},
    **{w: 10 * n for n, w in enumerate(TENS, 2)}, **{w: 10 * n for n, w in enumerate(ORDINAL_TENS, 2)},
}
MULTIPLIERS = {"hundred": 100, "hundredth": 100, "thousand": 1000, "thousandth": 1000}
ORDINALS = set(ORDINAL_UNITS) | set(ORDINAL_TENS) | {"hundredth", "thousandth"}
MONTHS = "january february march april may june july august september october november december".split()

# Each formula is the words after the number, its counting system, and whether the number follows the formula instead.
FORMULAS = [
    ("year of the reign of the judges", "reign_of_judges", False),
    ("years from the time that lehi left jerusalem", "since_lehi", False),
    ("years from the time lehi left jerusalem", "since_lehi", False),
    ("year from the coming of christ", "since_sign", False),
    ("years from the coming of christ", "since_sign", False),
    ("years since the coming of our lord", "bc_ad", False),
    ("year of our lord", "bc_ad", True),
]

# A year the text counts toward is not the year the passage takes place in.
NOT_WHEN = {"until", "till", "unto"}


def clear(db: sqlite3.Connection):
    db.execute("delete from date where evidence_first_word_id is not null")


def run(db: sqlite3.Connection):
    verses = defaultdict(list)
    for id, book, chapter, verse, text in db.execute(
        "select id, book_id, chapter, verse, text from word where edition_id in ('bom-2013', 'dc-2013', 'pgp-2013') order by id"
    ):
        verses[(book, chapter, verse)].append((id, text.lower()))
    rows = []
    keys = list(verses)
    for index, key in enumerate(keys):
        for row in dates_in(verses[key]):
            if row[-1]:
                row = extend(row, [verses[k] for k in keys[index + 1:] if k[0] == key[0]], verses[key])
            if not any(covers(earlier, row) for earlier in rows):
                rows.append(row[:-1])
    db.executemany(
        "insert into date (first_word_id, last_word_id, system_id, from_year, from_month, from_day, to_year, to_month, to_day, evidence_first_word_id, evidence_last_word_id) "
        "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    print(f"dates: {len(rows)} dates stated in a fixed formula")


def dates_in(words: list[tuple[int, str]]) -> list[tuple]:
    texts = [t for _, t in words]
    verse = (words[0][0], words[-1][0])
    found = []
    for phrase, system, number_follows in FORMULAS:
        phrase = phrase.split()
        for start in range(len(texts) - len(phrase) + 1):
            if texts[start:start + len(phrase)] != phrase:
                continue
            end = start + len(phrase) - 1
            if number_follows:
                first, last = start, number_end(texts, end + 1)
                year = number(texts[end + 1:last + 1])
            else:
                first, last = number_start(texts, start - 1), end
                year = number(texts[first:start])
            if year is None or NOT_WHEN & set(texts[max(0, first - 2):first]):
                continue
            month, day, first, last = month_and_day(texts, first, last)
            in_that_year = phrase[0] == "year" and system != "bc_ad"
            found.append((*verse, system, year, month, day, year, month, day, words[first][0], words[last][0], in_that_year))
    for i, text in enumerate(texts[:-2]):
        written = re.fullmatch(r"(\d+)(?:st|nd|rd|th)?", texts[i + 1])
        if text in MONTHS and written and re.fullmatch(r"\d{4}", texts[i + 2]):
            month, day, year = MONTHS.index(text) + 1, int(written.group(1)), int(texts[i + 2])
            found.append((*verse, "bc_ad", year, month, day, year, month, day, words[i][0], words[i + 2][0], False))
    # A verse that states the same date twice holds one date.
    unique = {}
    for row in found:
        unique.setdefault(row[:9], row)
    return list(unique.values())


def extend(row: tuple, following: list[list[tuple[int, str]]], own: list[tuple[int, str]]) -> tuple:
    """A year covers the events after it, until the text names another year, says this one ended, or the book ends."""
    year = row[3]
    if (year, True) in years_named([t for _, t in own]):
        return row
    last = row[1]
    for words in following:
        named = years_named([t for _, t in words])
        if any(other != year for other, _ in named):
            break
        last = words[-1][0]
        if (year, True) in named:
            break
    return (row[0], last, *row[2:])


def years_named(texts: list[str]) -> set[tuple[int, bool]]:
    """Each "fifth year" a verse names, and whether the verse says that year ended: "thus ended the fifth year", "the fifth year had passed away"."""
    found = set()
    for index, text in enumerate(texts):
        if text != "year" or index == 0:
            continue
        first = number_start(texts, index - 1)
        words = texts[first:index]
        if not any(part in ORDINALS for word in words for part in word.split("-")):
            continue
        after = texts[index + 1:index + 5]
        ended = bool({"ended", "endeth"} & set(texts[max(0, first - 4):first])) or ("away" in after and bool({"passed", "pass"} & set(after)))
        found.add((number(words), ended))
    return found


def covers(earlier: tuple, row: tuple) -> bool:
    """A later mention of the same year inside a year already dated adds nothing."""
    return earlier[2:4] == row[2:4] and earlier[0] <= row[0] <= earlier[1]


def number_start(texts, index) -> int:
    start = index + 1
    while index >= 0 and (is_number_word(texts[index]) or (texts[index] == "and" and index > 0 and is_number_word(texts[index - 1]))):
        start = index
        index -= 1
    if start < len(texts) and texts[start] == "and":
        start += 1
    return start


def number_end(texts, index) -> int:
    end = index - 1
    while index < len(texts) and (is_number_word(texts[index]) or (texts[index] == "and" and index + 1 < len(texts) and is_number_word(texts[index + 1]))):
        end = index
        index += 1
    return end


def is_number_word(text: str) -> bool:
    return all(part in NUMBERS or part in MULTIPLIERS or part in ("an", "a") for part in text.split("-"))


def number(texts: list[str]) -> int | None:
    parts = [p for t in texts for p in t.split("-") if p != "and"]
    if not any(p in NUMBERS or p in MULTIPLIERS for p in parts):
        return None
    total = current = 0
    for part in parts:
        if part in ("an", "a"):
            current = max(current, 1)
        elif part in NUMBERS:
            current += NUMBERS[part]
        elif part in ("hundred", "hundredth"):
            current = max(current, 1) * 100
        else:
            total += max(current, 1) * 1000
            current = 0
    return total + current


def month_and_day(texts, first, last) -> tuple[int | None, int | None, int, int]:
    """Find "the sixth day of the month which is called April" or "the twenty-third day of December" anywhere in the verse."""
    for i in range(len(texts) - 2):
        if first <= i <= last or texts[i + 1] != "day" or texts[i + 2] != "of" or not number([texts[i]]):
            continue
        for j in range(i + 3, min(i + 10, len(texts))):
            if texts[j] in MONTHS:
                return MONTHS.index(texts[j]) + 1, number([texts[i]]), min(first, i), max(last, j)
    return None, None, first, last
