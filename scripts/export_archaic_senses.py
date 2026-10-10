"""Write annotation packets for the archaic word senses pass over untagged English content words.

    python scripts/export_archaic_senses.py selection scripture.db OUT_DIR [CHARACTERS_PER_SLICE]
    python scripts/export_archaic_senses.py occurrences scripture.db DECISIONS_DIR OUT_DIR [OCCURRENCES_PER_FILE]

selection lists every English headword with two or more senses and untagged noun, verb, adjective, or adverb words,
most frequent first, split into slice_NN.txt files sized for one annotator.
occurrences reads the headwords marked archaic in DECISIONS_DIR/selection_*.jsonl and writes one packet per headword,
split into parts when large, listing in context every untagged occurrence that no senses_*.jsonl line skips.
KJV words show the Hebrew or Greek words they match as a hint. index.tsv lists each packet file with its occurrence count.
"""

import glob
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict

EDITIONS = {1: "KJV", 4: "BoM", 5: "D&C", 6: "PGP"}
KJV = 1
SNIPPET_RADIUS = 8
WINDOW_RADIUS = 30
DEFINITION_LENGTH = 240

UNRESOLVED = (
    "select w.id, w.headword_id, w.part_of_speech_id, w.verse_id from word w join headword h on h.id = w.headword_id "
    "where h.language_id = 1 and w.meaning_id is null and w.part_of_speech_id in (1, 4, 5, 6) "
    "and w.headword_id in (select headword_id from meaning group by headword_id having count(*) >= 2)"
)


def connect(path):
    db = sqlite3.connect(path)
    db.execute("pragma busy_timeout = 60000")
    return db


def unresolved_words(db, headwords=None):
    rows = db.execute(UNRESOLVED + " order by w.sequence").fetchall()
    return [row for row in rows if headwords is None or row[1] in headwords]


class Verses:
    def __init__(self, db):
        self.db = db
        self.cache = {}
        self.parts_of_speech = dict(db.execute("select id, name from part_of_speech"))

    def words(self, verse):
        if verse not in self.cache:
            self.cache[verse] = self.db.execute(
                "select id, before, text, after from word where verse_id = ? order by position", (verse,)
            ).fetchall()
        return self.cache[verse]

    def reference(self, verse):
        edition, book, chapter, number = self.db.execute(
            "select c.edition_id, b.name, c.number, v.number from verse v join chapter c on c.id = v.chapter_id "
            "join book b on b.id = c.book_id where v.id = ?",
            (verse,),
        ).fetchone()
        place = f"{book} {chapter}:{number}" if number is not None else f"{book} {chapter} heading"
        return EDITIONS.get(edition, str(edition)), place

    def marked(self, verse, word, radius):
        words = self.words(verse)
        at = next(i for i, row in enumerate(words) if row[0] == word)
        first, last = max(0, at - radius), min(len(words), at + radius + 1)
        text = "".join(
            f"{before}[[{text}]]{after}" if i == at else f"{before}{text}{after}"
            for i, (_, before, text, after) in enumerate(words[first:last], first)
        ).strip()
        return ("... " if first else "") + text + (" ..." if last < len(words) else "")


def senses(db, headword):
    return db.execute(
        "select id, number, gloss, definition from meaning where headword_id = ? order by number", (headword,)
    ).fetchall()


def short(text, length):
    text = " ".join((text or "").split())
    return text if len(text) <= length else text[: length - 3].rstrip() + "..."


def selection_block(db, verses, headword, occurrences):
    text = db.execute("select text from headword where id = ?", (headword,)).fetchone()[0]
    parts = Counter(verses.parts_of_speech[part] for _, part, _ in occurrences)
    editions = Counter(verses.reference(verse)[0] for _, _, verse in occurrences)
    lines = [
        f"## {headword} {text} | {len(occurrences)} untagged | "
        + ", ".join(f"{p} {n}" for p, n in parts.most_common())
        + " | "
        + ", ".join(f"{e} {n}" for e, n in editions.most_common())
    ]
    lines.extend(f"  {n}. {short(gloss, 70)}" for _, n, gloss, _ in senses(db, headword))
    for word, _, verse in dict.fromkeys((occurrences[0], occurrences[len(occurrences) // 2])):
        lines.append(f"  e.g. {verses.marked(verse, word, SNIPPET_RADIUS)} ({verses.reference(verse)[1]})")
    return "\n".join(lines) + "\n"


def export_selection(db, out, budget):
    words = unresolved_words(db)
    by_headword = defaultdict(list)
    for word, headword, part, verse in words:
        by_headword[headword].append((word, part, verse))
    verses = Verses(db)
    slices = [[]]
    size = 0
    for headword in sorted(by_headword, key=lambda h: (-len(by_headword[h]), h)):
        block = selection_block(db, verses, headword, by_headword[headword])
        if slices[-1] and size + len(block) > budget:
            slices.append([])
            size = 0
        slices[-1].append(block)
        size += len(block)
    os.makedirs(out, exist_ok=True)
    for stale in glob.glob(os.path.join(out, "slice_*.txt")):
        os.remove(stale)
    for number, blocks in enumerate(slices, 1):
        with open(os.path.join(out, f"slice_{number:02d}.txt"), "w", encoding="utf-8") as f:
            f.write(f"# Selection slice {number:02d}: {len(blocks)} headwords\n\n" + "\n".join(blocks))
    print(f"{len(by_headword)} headwords, {len(words)} words, {len(slices)} slices of up to {budget} characters")


def selected_headwords(directory):
    chosen = set()
    for path in sorted(glob.glob(os.path.join(directory, "selection_*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                decision = json.loads(line)
                if decision.get("archaic"):
                    chosen.add(decision["headword_id"])
    return chosen


def skipped_words(directory):
    skipped = set()
    for path in glob.glob(os.path.join(directory, "senses_*.jsonl")):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                decision = json.loads(line)
                if "skip" in decision:
                    skipped.add(decision["word_id"])
    return skipped


def original_hints(db, word):
    rows = db.execute(
        "select h.text, h.strongs, h.gloss, m.gloss from (select other_word_id id from word_match where word_id = ? "
        "union select word_id from word_match where other_word_id = ?) x join word o on o.id = x.id "
        "join headword h on h.id = o.headword_id left join meaning m on m.id = o.meaning_id where h.language_id <> 1 "
        "order by o.id",
        (word, word),
    ).fetchall()
    hints = []
    for text, strongs, gloss, meaning in dict.fromkeys(rows):
        hint = f"{text} {strongs or ''} '{gloss or ''}'".replace("  ", " ")
        hints.append(hint + (f" sense '{meaning}'" if meaning else ""))
    return "; ".join(hints)


def packet_header(db, headword, text, total, part, parts):
    tagged = Counter(
        dict(db.execute("select meaning_id, count(*) from word where headword_id = ? group by meaning_id", (headword,)))
    )
    lines = [f"HEADWORD {headword} {text}", f"Part {part} of {parts}. {total} untagged occurrences in all parts.", "Senses:"]
    for meaning, _, gloss, definition in senses(db, headword):
        detail = short(definition, DEFINITION_LENGTH)
        described = detail if detail.startswith(gloss) else f"{gloss}. {detail}" if detail else gloss
        already = f" [already tagged {tagged[meaning]}x]" if tagged[meaning] else ""
        lines.append(f"  {meaning}: {described}{already}")
    return lines


def export_occurrences(db, directory, out, per_file):
    chosen = selected_headwords(directory)
    skipped = skipped_words(directory)
    by_headword = defaultdict(list)
    for word, headword, part, verse in unresolved_words(db, chosen):
        if word not in skipped:
            by_headword[headword].append((word, part, verse))
    verses = Verses(db)
    os.makedirs(out, exist_ok=True)
    for stale in glob.glob(os.path.join(out, "*.txt")):
        os.remove(stale)
    index = ["file\theadword_id\theadword\toccurrences"]
    for headword in sorted(by_headword, key=lambda h: (-len(by_headword[h]), h)):
        text = db.execute("select text from headword where id = ?", (headword,)).fetchone()[0]
        occurrences = by_headword[headword]
        count = -(-len(occurrences) // per_file)
        chunks = [occurrences[i * len(occurrences) // count : (i + 1) * len(occurrences) // count] for i in range(count)]
        for part, chunk in enumerate(chunks, 1):
            lines = packet_header(db, headword, text, len(occurrences), part, len(chunks)) + ["", "Occurrences:"]
            for word, pos, verse in chunk:
                edition, place = verses.reference(verse)
                lines.append(f"w{word} | {edition} {place} | {verses.parts_of_speech[pos]}")
                if edition == EDITIONS[KJV]:
                    hint = original_hints(db, word)
                    if hint:
                        lines.append(f"  original: {hint}")
                lines.append(f"  {verses.marked(verse, word, WINDOW_RADIUS)}")
            name = f"{headword}_{text.replace(' ', '-').replace('/', '-')}_{part}.txt"
            with open(os.path.join(out, name), "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            index.append(f"{name}\t{headword}\t{text}\t{len(chunk)}")
    with open(os.path.join(out, "index.tsv"), "w", encoding="utf-8") as f:
        f.write("\n".join(index) + "\n")
    total = sum(len(o) for o in by_headword.values())
    print(f"{len(chosen)} headwords selected, {len(by_headword)} with untagged words, {total} words, {len(index) - 1} files")


def main(args):
    if args[0] == "selection":
        export_selection(connect(args[1]), args[2], int(args[3]) if len(args) > 3 else 80000)
    elif args[0] == "occurrences":
        export_occurrences(connect(args[1]), args[2], args[3], int(args[4]) if len(args) > 4 else 300)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
