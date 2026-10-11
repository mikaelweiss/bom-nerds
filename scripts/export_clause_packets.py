"""Write annotation packets for sentences whose words are not all inside a clause.

    python scripts/export_clause_packets.py scripture.db OUT_DIR [SLICE_BYTES]

A word outside every clause is a gap unless it sits in a run of connectives ("and", "but", "behold" in English,
conjunctions and particles in Hebrew and Greek), which stay outside clauses by convention.
Each packet holds the gap sentences of one chapter: every word with its id, gap runs in brackets, and the clauses already there.
Hebrew and Greek packets add an English gloss per word and the matched KJV verse with its clauses as a hint.
OUT_DIR gets index.tsv, one row per packet, and slices.tsv, the packets cut in book order into slices of about SLICE_BYTES (default 90000).
Packets from an earlier run are replaced, so rerunning after decisions are applied leaves only the sentences still with gaps.
"""

import bisect
import os
import sqlite3
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from project_to_originals import Projector  # noqa: E402

HEBREW, GREEK = 2, 3
CODES = {1: "kjv", 2: "wlc", 3: "sbl", 4: "bom", 5: "dc", 6: "pgp"}
ROLE_CODES = {"Subject": "S", "Verb": "V", "Object": "O", "Indirect object": "IO", "Complement": "C", "Adverbial": "A"}
ENGLISH_CONNECTIVES = {
    "and", "but", "or", "nor", "neither", "for", "yet", "yea", "nay", "now", "then", "therefore", "wherefore",
    "behold", "lo", "o", "oh", "amen", "selah", "even", "so", "also", "that", "because", "moreover",
    "nevertheless", "notwithstanding", "howbeit", "verily", "alleluia", "hallelujah",
}
ORIGINAL_CONNECTIVES = {HEBREW: {"Conjunction", "Particle", "Adverb", "Preposition"}, GREEK: {"Conjunction", "Particle"}}
CONNECTIVE_STRONGS = {"H0657"}
PUNCTUATION = ".,;:!?'\"()[]"


class Text:
    """Every word of the database, its clauses, and which words no clause covers."""

    def __init__(self, db):
        self.db = db
        pos = dict(db.execute("select id, name from part_of_speech"))
        self.words = {}
        self.at = {}
        self.connective_headword = set()
        for word, seq, text, after, part, edition, heading, verse, strongs in db.execute(
            "select w.id, w.sequence, w.text, w.after, w.part_of_speech_id, c.edition_id, v.number is null, w.verse_id, h.strongs "
            "from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id "
            "left join headword h on h.id = w.headword_id"
        ):
            self.words[word] = (seq, text, after, pos.get(part), edition, heading, verse)
            if strongs in CONNECTIVE_STRONGS:
                self.connective_headword.add(word)
            self.at[seq] = word
        self.verse_number = dict(db.execute("select id, coalesce(number, 'heading') from verse"))
        self.sentences = {s: (a, b) for s, a, b in db.execute("select id, first_word_id, last_word_id from sentence")}
        self.starts = sorted((self.seq(a), s) for s, (a, _) in self.sentences.items())
        self.covered = set()
        for a, b in db.execute("select first_word_id, last_word_id from clause"):
            self.covered.update(range(self.seq(a), self.seq(b) + 1))

    def seq(self, word):
        return self.words[word][0]

    def sentence_of(self, word):
        i = bisect.bisect_right(self.starts, (self.seq(word), float("inf"))) - 1
        return self.starts[i][1]

    def span(self, first, last):
        return [self.at[s] for s in range(self.seq(first), self.seq(last) + 1)]

    def connective(self, word):
        _, text, _, part, edition, _, _ = self.words[word]
        if edition in ORIGINAL_CONNECTIVES:
            return part in ORIGINAL_CONNECTIVES[edition] or word in self.connective_headword
        return text.strip(PUNCTUATION).lower() in ENGLISH_CONNECTIVES

    def gaps(self, sentence, covered=None):
        """Runs of uncovered verse words in a sentence that hold at least one word other than a connective."""
        covered = self.covered if covered is None else covered
        runs, run = [], []
        for word in self.span(*self.sentences[sentence]) + [None]:
            if word is not None and self.words[word][5]:
                continue
            if word is not None and self.seq(word) not in covered:
                run.append(word)
            elif run:
                runs.append(run)
                run = []
        return [r for r in runs if not all(self.connective(w) for w in r)]


def clauses_in(db, sentence):
    """Clauses of a sentence, outermost first: (id, parent, first, last, [(role code, first, last)])."""
    rows = db.execute(
        "select c.id, c.parent_id, c.first_word_id, c.last_word_id from clause c join word a on a.id = c.first_word_id "
        "join word b on b.id = c.last_word_id where c.sentence_id = ? order by a.sequence, b.sequence desc",
        (sentence,),
    ).fetchall()
    parts = defaultdict(list)
    for clause, role, a, b in db.execute(
        "select p.clause_id, r.name, p.first_word_id, p.last_word_id from clause_part p join clause_role r on r.id = p.clause_role_id "
        "join word w on w.id = p.first_word_id where p.clause_id in (select id from clause where sentence_id = ?) order by w.sequence",
        (sentence,),
    ):
        parts[clause].append((ROLE_CODES[role], a, b))
    return [(c, p, a, b, parts[c]) for c, p, a, b in rows]


def place(db, word):
    book, chapter, verse = db.execute(
        "select b.name, c.number, v.number from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id "
        "join book b on b.id = c.book_id where w.id = ?",
        (word,),
    ).fetchone()
    return book, chapter, verse


def brief(text, first, last, limit=6):
    words = [text.words[w][1] for w in text.span(first, last)]
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[: limit // 2]) + " ... " + " ".join(words[-(limit // 2):])


def clause_lines(text, clauses, indent="  "):
    depth = {}
    lines = []
    for clause, parent, a, b, parts in clauses:
        depth[clause] = depth[parent] + 1 if parent in depth else 0
        shown = " ".join(f"{role}:{x}" + (f"-{y}" if y != x else "") + f' "{brief(text, x, y, 4)}"' for role, x, y in parts)
        lines.append(f"{indent}{'  ' * depth[clause]}c{clause} {a}-{b} \"{brief(text, a, b)}\" {shown or '(no parts)'}")
    return lines


def word_line(text, words, runs, glosses=None):
    starts = {run[0] for run in runs}
    ends = {run[-1] for run in runs}
    out = []
    verse = None
    for word in words:
        _, shown, after, _, _, _, verse_id = text.words[word]
        if verse_id != verse:
            out.append(f"|v{text.verse_number[verse_id]}|")
            verse = verse_id
        token = f"{word}:{shown}{after.strip()}"
        if glosses is not None:
            token += "(" + (glosses.get(word) or "?").replace("[", "").replace("]", "") + ")"
        out.append(("[" if word in starts else "") + token + ("]" if word in ends else ""))
    return " ".join(out)


def glosses_for(db, words):
    marks = ",".join("?" * len(words))
    return dict(db.execute(
        f"select w.id, coalesce(m.gloss, h.gloss) from word w left join meaning m on m.id = w.meaning_id "
        f"left join headword h on h.id = w.headword_id where w.id in ({marks})",
        words,
    ))


def kjv_hint(db, text, projector, words):
    """The KJV sentences matched to these original words, with their clauses."""
    found = set()
    for word in words:
        span = projector.project_back(word, word)
        if span:
            found.add(text.sentence_of(span[0]))
    lines = []
    for sentence in sorted(found, key=lambda s: text.seq(text.sentences[s][0])):
        first, last = text.sentences[sentence]
        book, chapter, verse = place(db, first)
        lines.append(f"  KJV {book} {chapter}:{verse} s{sentence}: " + " ".join(text.words[w][1] for w in text.span(first, last)))
        lines.extend(clause_lines(text, clauses_in(db, sentence), "    "))
    return lines


def packet_entry(db, text, projector, sentence, runs):
    first, last = text.sentences[sentence]
    words = text.span(first, last)
    book, chapter, verse = place(db, first)
    _, end_chapter, end_verse = place(db, last)
    where = f"{book} {chapter}:{verse}" + (f"-{end_chapter}:{end_verse}" if (end_chapter, end_verse) != (chapter, verse) else "")
    edition = text.words[first][4]
    gap = sum(len(r) for r in runs)
    lines = [f"## s{sentence} {where} gap={gap}"]
    glosses = glosses_for(db, words) if edition in (HEBREW, GREEK) else None
    lines.append(word_line(text, words, runs, glosses))
    clauses = clauses_in(db, sentence)
    lines.append("clauses:" if clauses else "clauses: none")
    lines.extend(clause_lines(text, clauses))
    if edition in (HEBREW, GREEK):
        lines.append("KJV hint:")
        lines.extend(kjv_hint(db, text, projector, words) or ["  none"])
    return "\n".join(lines) + "\n", gap


def slug(name):
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def main(path, out, slice_bytes=90000):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    text = Text(db)
    projector = Projector(db)
    chapters = defaultdict(list)
    for sentence, (first, _) in sorted(text.sentences.items(), key=lambda item: text.seq(item[1][0])):
        runs = text.gaps(sentence)
        if runs:
            edition, book, chapter, position = db.execute(
                "select c.edition_id, b.name, c.number, eb.position from word w join verse v on v.id = w.verse_id "
                "join chapter c on c.id = v.chapter_id join book b on b.id = c.book_id "
                "join edition_book eb on eb.edition_id = c.edition_id and eb.book_id = c.book_id where w.id = ?",
                (first,),
            ).fetchone()
            chapters[(edition, position, book, chapter)].append((sentence, runs))
    os.makedirs(out, exist_ok=True)
    for stale in os.listdir(out):
        if stale.endswith(".txt"):
            os.remove(os.path.join(out, stale))
    index = []
    for (edition, position, book, chapter), sentences in sorted(chapters.items()):
        name = f"{CODES[edition]}-{position:02d}-{slug(book)}-{chapter:03d}.txt"
        body = [f"# {CODES[edition]} {book} {chapter}\n"]
        gap = words = 0
        for sentence, runs in sentences:
            entry, n = packet_entry(db, text, projector, sentence, runs)
            body.append(entry)
            gap += n
            words += len(text.span(*text.sentences[sentence]))
        content = "\n".join(body)
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(content)
        index.append((name, CODES[edition], book, chapter, len(sentences), gap, words, len(content.encode("utf-8"))))
    with open(os.path.join(out, "index.tsv"), "w", encoding="utf-8") as f:
        f.write("packet\tedition\tbook\tchapter\tsentences\tgap_words\twords\tbytes\n")
        for row in index:
            f.write("\t".join(map(str, row)) + "\n")
    slices, current, size = [], [], 0
    for row in index:
        if current and (size + row[7] > slice_bytes or current[-1][1] != row[1]):
            slices.append(current)
            current, size = [], 0
        current.append(row)
        size += row[7]
    if current:
        slices.append(current)
    with open(os.path.join(out, "slices.tsv"), "w", encoding="utf-8") as f:
        f.write("slice\tpackets\tsentences\tbytes\tpacket_names\n")
        numbers = Counter()
        for rows in slices:
            numbers[rows[0][1]] += 1
            name = f"{rows[0][1]}-{numbers[rows[0][1]]:03d}"
            f.write(f"{name}\t{len(rows)}\t{sum(r[4] for r in rows)}\t{sum(r[7] for r in rows)}\t{','.join(r[0] for r in rows)}\n")
    total = sum(r[7] for r in index)
    print(f"{len(index)} packets, {sum(r[4] for r in index)} sentences, {sum(r[5] for r in index)} gap words, {total} bytes, {len(slices)} slices")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], *(int(a) for a in sys.argv[3:]))
