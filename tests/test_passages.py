import sqlite3
import unicodedata
import unittest
from pathlib import Path

from bomnerds.passages import Rejected, chapter_span, chapter_verses, english_edition, locate, parse_reference, reference, render, resolve, verse_text
from bomnerds.words import split

ROOT = Path(__file__).resolve().parent.parent
DASH = chr(0x2014)

BOOKS = [
    ("bom", "1-nephi", "1 Nephi"),
    ("dc", "doctrine-and-covenants", "Doctrine and Covenants"),
    ("pgp", "joseph-smith-matthew", f"Joseph Smith{DASH}Matthew"),
    ("pgp", "joseph-smith-history", f"Joseph Smith{DASH}History"),
    ("bible", "genesis", "Genesis"),
    ("bible", "psalms", "Psalms"),
    ("bible", "isaiah", "Isaiah"),
]

VERSES = [
    ("bom-2013", "1-nephi", 3, 0, "Nephi and his brethren return to Jerusalem."),
    ("bom-2013", "1-nephi", 3, 7, "And it came to pass that I, Nephi, said unto my father: I will go, I will do the things which the Lord hath commanded, for I know that the Lord giveth no commandments unto the children of men."),
    ("bom-2013", "1-nephi", 3, 8, "And it came to pass that when my father had heard these words he was exceedingly glad."),
    ("bom-2013", "1-nephi", 4, 1, "Therefore let us go up again unto Jerusalem, and be faithful in keeping the commandments of the Lord."),
    ("bom-2013", "1-nephi", 4, 2, "Let us be strong like unto Moses, for the Lord's power is great. Amen."),
    ("dc-2013", "doctrine-and-covenants", 76, 22, "And now, after the many testimonies which have been given of him, this is the testimony, last of all, which we give of him: That he lives!"),
    ("pgp-2013", "joseph-smith-matthew", 1, 1, "For I say unto you, that ye shall not see me henceforth."),
    ("pgp-2013", "joseph-smith-history", 1, 17, "It no sooner appeared than I found myself delivered from the enemy which held me bound."),
    ("kjv", "genesis", 1, 1, "In the beginning God created the heaven and the earth."),
    ("kjv", "psalms", 23, 0, "A Psalm of David."),
    ("kjv", "psalms", 23, 1, "The LORD is my shepherd; I shall not want."),
    ("kjv", "psalms", 23, 2, "He maketh me to lie down in green pastures: he leadeth me beside the still waters."),
    ("kjv", "isaiah", 6, 3, "Holy, holy, holy, is the LORD of hosts."),
]

# Macula splits prefixes into words of their own, printed joined to the word they open.
GENESIS_HEBREW = [("", "בְּ", ""), ("", "רֵאשִׁ֖ית", " "), ("", "בָּרָ֣א", " "), ("", "אֱלֹהִ֑ים", " "), ("", "אֵ֥ת", " "), ("", "הַ", ""), ("", "שָּׁמַ֖יִם", "׃")]


def database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.executescript((ROOT / "db/schema.sql").read_text())
    db.executescript((ROOT / "db/seed.sql").read_text())
    editions = {"bom": "bom-2013", "dc": "dc-2013", "pgp": "pgp-2013", "bible": "kjv"}
    for position, (work, book, name) in enumerate(BOOKS, 1):
        db.execute("insert into book (id, work_id, name) values (?, ?, ?)", (book, work, name))
        db.execute("insert into edition_book values (?, ?, ?)", (editions[work], book, position))
    db.execute("insert into edition_book values ('wlc', 'genesis', 1)")
    rows = [
        (edition, book, chapter, verse, position, w.before, w.text, w.after)
        for edition, book, chapter, verse, text in VERSES
        for position, w in enumerate(split(text), 1)
    ]
    rows += [("wlc", "genesis", 1, 1, position, *word) for position, word in enumerate(GENESIS_HEBREW, 1)]
    db.executemany("insert into word (edition_id, book_id, chapter, verse, position, before, text, after) values (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return db


class PassageTest(unittest.TestCase):
    def setUp(self):
        self.db = database()

    def ids(self, book, chapter, verse, edition=None):
        edition = edition or english_edition(self.db, book)
        return [row[0] for row in self.db.execute(
            "select id from word where edition_id = ? and book_id = ? and chapter = ? and verse = ? order by position", (edition, book, chapter, verse)
        )]

    def words(self, first, last):
        return " ".join(row[0] for row in self.db.execute("select text from word where id between ? and ? order by id", (first, last)))

    def rejects(self, passage, *phrases, edition=None):
        with self.assertRaises(Rejected) as caught:
            resolve(self.db, passage, edition)
        for phrase in phrases:
            self.assertIn(phrase, str(caught.exception))


class ReferenceTest(PassageTest):
    def test_reads_book_chapter_and_verse(self):
        self.assertEqual(parse_reference(self.db, "1 Nephi 3:7"), ("1-nephi", 3, 7))
        self.assertEqual(parse_reference(self.db, "  1   nephi  4 "), ("1-nephi", 4, None))

    def test_accepts_the_short_names_people_write(self):
        self.assertEqual(parse_reference(self.db, "D&C 76:22")[0], "doctrine-and-covenants")
        for name in (f"JS{DASH}M", "JS-M", "js-m", "Joseph Smith-Matthew", f"Joseph Smith{DASH}Matthew"):
            self.assertEqual(parse_reference(self.db, f"{name} 1:1")[0], "joseph-smith-matthew")
        self.assertEqual(parse_reference(self.db, "JS-H 1:17")[0], "joseph-smith-history")
        self.assertEqual(parse_reference(self.db, "Psalm 23:1")[0], "psalms")

    def test_writes_references_with_display_names(self):
        self.assertEqual(reference(self.db, "doctrine-and-covenants", 76, 22), "D&C 76:22")
        self.assertEqual(reference(self.db, "1-nephi", 3), "1 Nephi 3")
        self.assertEqual(parse_reference(self.db, reference(self.db, "joseph-smith-matthew", 1, 1)), ("joseph-smith-matthew", 1, 1))

    def test_rejects_an_unknown_book_by_name(self):
        with self.assertRaisesRegex(Rejected, '"Hezekiah"'):
            parse_reference(self.db, "Hezekiah 3:7")

    def test_rejects_a_chapter_or_verse_the_edition_lacks(self):
        with self.assertRaisesRegex(Rejected, "chapters 3 to 4"):
            parse_reference(self.db, "1 Nephi 5:1")
        with self.assertRaisesRegex(Rejected, "verses 0 to 8"):
            parse_reference(self.db, "1 Nephi 3:9")

    def test_rejects_a_reference_without_a_chapter(self):
        with self.assertRaisesRegex(Rejected, "needs a chapter"):
            parse_reference(self.db, "1 Nephi")

    def test_finds_the_english_edition_of_a_book(self):
        self.assertEqual(english_edition(self.db, "genesis"), "kjv")
        self.assertEqual(english_edition(self.db, "joseph-smith-history"), "pgp-2013")


class ResolveTest(PassageTest):
    def test_quote(self):
        self.assertEqual(resolve(self.db, {"verse": "1 Nephi 3:7", "quote": "Nephi"}), (self.ids("1-nephi", 3, 7)[7],) * 2)

    def test_quote_in_longer_words(self):
        self.assertEqual(resolve(self.db, {"verse": "1 Nephi 3:7", "quote": "I", "in": "I will go"}), (self.ids("1-nephi", 3, 7)[12],) * 2)

    def test_verse(self):
        ids = self.ids("1-nephi", 3, 8)
        self.assertEqual(resolve(self.db, {"verse": "1 Nephi 3:8"}), (ids[0], ids[-1]))

    def test_whole_verses_across_chapters(self):
        self.assertEqual(resolve(self.db, {"from": "1 Nephi 3:8", "to": "1 Nephi 4:1"}), (self.ids("1-nephi", 3, 8)[0], self.ids("1-nephi", 4, 1)[-1]))

    def test_starts_and_ends_partway_through_verses(self):
        first, last = resolve(self.db, {"from": "1 Nephi 3:7", "to": "1 Nephi 4:2", "starts": "I will go", "ends": "power is great"})
        self.assertEqual(self.words(first, first + 2), "I will go")
        self.assertEqual(self.words(last - 1, last), "is great")

    def test_starts_and_ends_on_repeated_words(self):
        v1, v2 = self.ids("psalms", 23, 1), self.ids("psalms", 23, 2)
        passage = {"from": "Psalms 23:1", "to": "Psalms 23:2", "starts": "I", "ends": "he", "ends_in": "pastures: he leadeth"}
        self.assertEqual(resolve(self.db, passage), (v1[5], v2[9]))
        with self.assertRaisesRegex(Rejected, "ends_in"):
            resolve(self.db, {"from": "Psalms 23:1", "to": "Psalms 23:2", "ends": "he"})

    def test_chapter_includes_verse_zero(self):
        self.assertEqual(resolve(self.db, {"chapter": "1 Nephi 3"}), (self.ids("1-nephi", 3, 0)[0], self.ids("1-nephi", 3, 8)[-1]))

    def test_quote_ignores_case_punctuation_spacing_and_apostrophe_style(self):
        first, last = resolve(self.db, {"verse": "1 Nephi 4:2", "quote": "MOSES for  the LORD’S"})
        self.assertEqual(self.words(first, last), "Moses for the Lord's")

    def test_hebrew_quote_joins_prefixes_and_ignores_normalization(self):
        quote = unicodedata.normalize("NFD", "בְּרֵאשִׁ֖ית בָּרָ֣א")
        ids = self.ids("genesis", 1, 1, "wlc")
        self.assertEqual(resolve(self.db, {"verse": "Genesis 1:1", "quote": quote}, "wlc"), (ids[0], ids[2]))

    def test_rejects_a_quote_not_in_its_verse_and_shows_the_verse(self):
        self.rejects({"verse": "1 Nephi 3:8", "quote": "Laman"}, '"Laman" is not in 1 Nephi 3:8', "exceedingly glad.")

    def test_rejects_a_repeated_quote_without_in(self):
        self.rejects({"verse": "1 Nephi 3:7", "quote": "I"}, "appears 4 times", 'Add "in"')

    def test_rejects_in_that_is_not_unique(self):
        self.rejects({"verse": "1 Nephi 3:7", "quote": "Lord", "in": "the Lord"}, '"in" "the Lord" appears twice')

    def test_rejects_in_that_does_not_hold_the_quote_once(self):
        self.rejects({"verse": "1 Nephi 3:7", "quote": "Nephi", "in": "I will go"}, "no times")
        self.rejects({"verse": "Isaiah 6:3", "quote": "holy", "in": "holy, holy, is"}, "twice")

    def test_rejects_starts_or_ends_that_is_not_once_in_its_verse(self):
        self.rejects({"from": "1 Nephi 3:7", "to": "1 Nephi 3:8", "starts": "the Lord"}, '"starts" "the Lord" appears twice')
        self.rejects({"from": "1 Nephi 3:7", "to": "1 Nephi 3:8", "ends": "Jerusalem"}, '"ends" "Jerusalem" is not in 1 Nephi 3:8')

    def test_rejects_a_passage_that_runs_backward(self):
        self.rejects({"from": "1 Nephi 4:1", "to": "1 Nephi 3:8"}, "runs backward")
        self.rejects({"from": "1 Nephi 3:7", "to": "1 Nephi 3:7", "starts": "I will go", "ends": "said unto"}, "runs backward")

    def test_rejects_a_passage_across_books(self):
        self.rejects({"from": "Genesis 1:1", "to": "Psalms 23:1"}, "one book")

    def test_rejects_shapes_it_does_not_know(self):
        shape = '{ "chapter": "Alma 32" }'
        self.rejects({"verse": "1 Nephi 3:7", "quote": "Nephi", "note": "x"}, '"note"', shape)
        self.rejects({"verse": "1 Nephi 3:7", "from": "1 Nephi 3:7"}, shape)
        self.rejects({"from": "1 Nephi 3:7"}, shape)
        self.rejects({"verse": "1 Nephi 3:7", "in": "I will go"}, shape)
        self.rejects({}, "no keys", shape)

    def test_rejects_a_reference_of_the_wrong_size(self):
        self.rejects({"verse": "1 Nephi 3"}, '"verse" takes a verse')
        self.rejects({"chapter": "1 Nephi 3:7"}, '"chapter" takes a chapter alone')

    def test_rejects_a_book_outside_the_edition(self):
        self.rejects({"verse": "1 Nephi 3:7"}, "not in the wlc edition", edition="wlc")


class RenderTest(PassageTest):
    def assert_renders(self, first, last, passage):
        self.assertEqual(render(self.db, first, last), passage)
        self.assertEqual(resolve(self.db, passage), (first, last))

    def test_picks_the_shortest_shape(self):
        v7, v8 = self.ids("1-nephi", 3, 7), self.ids("1-nephi", 3, 8)
        self.assert_renders(*chapter_span(self.db, "bom-2013", "1-nephi", 3), {"chapter": "1 Nephi 3"})
        self.assert_renders(v8[0], v8[-1], {"verse": "1 Nephi 3:8"})
        self.assert_renders(v7[0], v8[-1], {"from": "1 Nephi 3:7", "to": "1 Nephi 3:8"})
        self.assert_renders(v7[6], v7[7], {"verse": "1 Nephi 3:7", "quote": "I, Nephi"})
        self.assert_renders(v7[12], v7[12], {"verse": "1 Nephi 3:7", "quote": "I", "in": "father: I will"})
        self.assert_renders(v7[12], v8[2], {"from": "1 Nephi 3:7", "to": "1 Nephi 3:8", "starts": "I will go", "ends": "came"})
        self.assert_renders(v7[0], v8[2], {"from": "1 Nephi 3:7", "to": "1 Nephi 3:8", "ends": "came"})

    def test_an_edge_on_repeated_words_takes_a_window(self):
        v1, v2 = self.ids("psalms", 23, 1), self.ids("psalms", 23, 2)
        self.assert_renders(v1[1], v2[0], {"from": "Psalms 23:1", "to": "Psalms 23:2", "starts": "LORD", "ends": "He", "ends_in": "He maketh"})

    def test_round_trips_every_span_in_every_book(self):
        books = self.db.execute("select edition_id, book_id, min(id), max(id) from word where book_id != 'isaiah' group by edition_id, book_id").fetchall()
        for edition, book, low, high in books:
            for first in range(low, high + 1):
                for last in range(first, high + 1):
                    with self.subTest(edition=edition, first=first, last=last):
                        self.assertEqual(resolve(self.db, render(self.db, first, last), edition), (first, last))

    def test_raises_when_no_shape_points_at_the_words(self):
        middle_holy = self.ids("isaiah", 6, 3)[1]
        with self.assertRaises(ValueError):
            render(self.db, middle_holy, middle_holy)

    def test_raises_across_books(self):
        with self.assertRaises(ValueError):
            render(self.db, self.ids("genesis", 1, 1)[0], self.ids("psalms", 23, 1)[0])


class TextTest(PassageTest):
    def test_verse_text_is_exactly_as_printed(self):
        self.assertEqual(verse_text(self.db, "kjv", "psalms", 23, 1), "The LORD is my shepherd; I shall not want.")

    def test_chapter_verses_include_verse_zero(self):
        self.assertEqual([n for n, _ in chapter_verses(self.db, "kjv", "psalms", 23)], [0, 1, 2])

    def test_locates_a_word(self):
        self.assertEqual(locate(self.db, self.ids("1-nephi", 4, 2)[3]), ("bom-2013", "1-nephi", 4, 2))


if __name__ == "__main__":
    unittest.main()
