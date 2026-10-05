import sqlite3
import unittest
from pathlib import Path

from bomnerds.rows import row_id
from bomnerds.text import KJV, WLC, insert_text, number_words
from bomnerds.words import split

ROOT = Path(__file__).resolve().parent.parent


class SchemaTest(unittest.TestCase):

    def setUp(self):
        db = self.db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("pragma foreign_keys = on")
        db.executescript((ROOT / "db/schema.sql").read_text())
        db.executescript((ROOT / "db/seed.sql").read_text())
        bible = row_id(db, "work", "Bible")
        self.genesis = db.execute("insert into book (work_id, name) values (?, 'Genesis')", (bible,)).lastrowid
        for name, text in ((WLC, "בְּרֵאשִׁית בָּרָא אֱלֹהִים"), (KJV, "In the beginning God created the heaven and the earth.")):
            edition = row_id(db, "edition", name)
            db.execute("insert into edition_book (edition_id, book_id, work_id, position) values (?, ?, ?, 1)", (edition, self.genesis, bible))
            insert_text(db, edition, self.genesis, {(1, None): split("The First Book of Moses"), (1, 1): split(text)})
        self.kjv = [row[0] for row in db.execute(
            "select w.id from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id where c.edition_id = ? order by w.sequence",
            (row_id(db, "edition", KJV),),
        )]
        self.wlc = [row[0] for row in db.execute(
            "select w.id from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id where c.edition_id = ? order by w.sequence",
            (row_id(db, "edition", WLC),),
        )]

    def rejects(self, sql, *values):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(sql, values)

    def test_a_chapter_has_one_heading(self):
        chapter = self.db.execute("select id from chapter limit 1").fetchone()[0]
        self.rejects("insert into verse (chapter_id, number) values (?, null)", chapter)

    def test_a_book_belongs_to_its_editions_work(self):
        book = self.db.execute("insert into book (work_id, name) values (?, '1 Nephi')", (row_id(self.db, "work", "Book of Mormon"),)).lastrowid
        self.rejects("insert into edition_book (edition_id, book_id, work_id, position) values (?, ?, ?, 2)", row_id(self.db, "edition", KJV), book, row_id(self.db, "work", "Bible"))

    def test_a_passage_runs_forward_within_one_edition(self):
        self.db.execute("insert into sentence (first_word_id, last_word_id) values (?, ?)", (self.kjv[0], self.kjv[-1]))
        self.rejects("insert into sentence (first_word_id, last_word_id) values (?, ?)", self.kjv[3], self.kjv[2])
        self.rejects("insert into sentence (first_word_id, last_word_id) values (?, ?)", self.kjv[0], self.wlc[-1])
        sentence = self.db.execute("select id from sentence").fetchone()[0]
        self.rejects("update sentence set last_word_id = ? where id = ?", self.wlc[-1], sentence)

    def test_words_are_numbered_in_edition_order(self):
        def last_sequences():
            return dict(self.db.execute(
                "select c.edition_id, max(w.sequence) from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id group by c.edition_id"
            ))

        kjv, wlc = row_id(self.db, "edition", KJV), row_id(self.db, "edition", WLC)
        self.assertGreater(last_sequences()[kjv], last_sequences()[wlc])
        number_words(self.db)
        self.assertLess(last_sequences()[kjv], last_sequences()[wlc])
        self.assertEqual([row[0] for row in self.db.execute(
            "select w.id from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id where c.edition_id = ? order by w.sequence", (kjv,)
        )], self.kjv)

    def test_grammar_belongs_to_a_word_of_its_language(self):
        self.db.execute("insert into hebrew_word (word_id) values (?)", (self.wlc[1],))
        self.rejects("insert into hebrew_word (word_id) values (?)", self.kjv[1])
        self.rejects("insert into greek_word (word_id) values (?)", self.wlc[2])

    def test_a_meaning_belongs_to_the_words_headword(self):
        hebrew = row_id(self.db, "language", "hbo", "iso_code")
        first = self.db.execute("insert into headword (language_id, text) values (?, 'ראשית')", (hebrew,)).lastrowid
        other = self.db.execute("insert into headword (language_id, text) values (?, 'ברא')", (hebrew,)).lastrowid
        meaning = self.db.execute("insert into meaning (headword_id, number, gloss) values (?, 1, 'beginning')", (first,)).lastrowid
        self.db.execute("update word set headword_id = ?, meaning_id = ? where id = ?", (first, meaning, self.wlc[0]))
        self.rejects("update word set headword_id = ?, meaning_id = ? where id = ?", other, meaning, self.wlc[1])
        self.rejects("update word set headword_id = null, meaning_id = ? where id = ?", meaning, self.wlc[2])

    def test_an_entitys_main_name_lives_only_on_the_entity(self):
        person = row_id(self.db, "entity_type", "Person")
        abraham = self.db.execute("insert into entity (entity_type_id, name, description) values (?, 'Abraham', 'Father of the faithful.')", (person,)).lastrowid
        self.db.execute("insert into entity_name (entity_id, name) values (?, 'Abram')", (abraham,))
        self.rejects("insert into entity_name (entity_id, name) values (?, 'Abraham')", abraham)
        self.rejects("update entity set name = 'Abram' where id = ?", abraham)

    def test_entities_may_share_a_name_and_description_but_not_a_tipnr_identifier(self):
        person = row_id(self.db, "entity_type", "Person")
        insert = "insert into entity (entity_type_id, name, description, tipnr) values (?, 'Baana', 'One of Solomon''s twelve district governors.', ?)"
        self.db.execute(insert, (person, "H1195G"))
        self.db.execute(insert, (person, "H1195H"))
        self.rejects(insert, person, "H1195H")

    def test_a_date_needs_evidence_unless_its_system_allows_an_estimate(self):
        columns = "insert into date (first_word_id, last_word_id, counting_system_id, from_year, to_year) values (?, ?, ?, 1, 1)"
        self.rejects(columns, self.kjv[0], self.kjv[-1], row_id(self.db, "counting_system", "Years of the reign of the judges"))
        self.db.execute(columns, (self.kjv[0], self.kjv[-1], row_id(self.db, "counting_system", "BC/AD")))

    def test_a_two_way_link_runs_from_the_passage_that_comes_first(self):
        cross_reference = row_id(self.db, "link_kind", "Cross-reference")
        insert = "insert into passage_link (link_kind_id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id) values (?, ?, ?, ?, ?)"
        self.rejects(insert, cross_reference, self.kjv[5], self.kjv[6], self.kjv[0], self.kjv[1])
        self.db.execute(insert, (cross_reference, self.kjv[0], self.kjv[1], self.kjv[5], self.kjv[6]))

    def test_a_summary_kind_applies_only_to_its_works(self):
        chapter = self.db.execute("select id from chapter limit 1").fetchone()[0]
        insert = "insert into summary (summary_kind_id, chapter_id, text) values (?, ?, 'Creation.')"
        self.rejects(insert, row_id(self.db, "summary_kind", "Editors' comments"), chapter)
        self.db.execute(insert, (row_id(self.db, "summary_kind", "Culture"), chapter))


if __name__ == "__main__":
    unittest.main()
