import io
import sqlite3
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from unittest import mock

from bomnerds.agent import jobs
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.prompt import job_text
from bomnerds.passages import Rejected
from tests.agent_fixtures import database, job_folder

GENESIS = {(5, 1): "This is the book of the generations of Adam.", (5, 3): "And Adam lived an hundred and thirty years, and begat a son, and called his name Seth:"}
MOSIAH = {
    (1, 0): "The Book of Mosiah",
    (1, 1): "And now there was no more contention in all the land of Zarahemla.",
    (2, 1): "And it came to pass that after Mosiah had done as his father had commanded him.",
    (2, 9): "My brethren, all ye that have assembled yourselves together.",
    (3, 1): "And again my brethren, I would call your attention.",
    (3, 2): "And the things which I shall tell you are made known unto me by an angel from God. Amen.",
}
SERMON = '{"from": "Mosiah 2:9", "to": "Mosiah 3:2"}'
FEW = "King Benjamin teaches that serving others is serving God. He calls his people to remember their debt to the Lord, who gives them breath and life each day."
PARAGRAPH = " ".join([FEW] * 3)


def summary(kind, on, text=FEW):
    return {"kind": kind, "on": on, "text": text}


class SummariesTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bible", "Genesis", GENESIS), ("bom", "Mosiah", MOSIAH)])
        self.addCleanup(self.db.close)
        self.layer = LAYERS["summaries"]
        self.names = LAYERS["names"]
        for patch in (job_folder(), mock.patch.dict(LAYERS, {"summaries": self.layer}, clear=True)):
            patch.__enter__()
            self.addCleanup(patch.__exit__, None, None, None)

    def add_range(self, id="king-benjamins-sermon", passage=SERMON):
        with redirect_stdout(io.StringIO()) as out:
            self.layer.add_range(self.db, Namespace(id=id, name="King Benjamin's sermon", passage=passage))
        return out.getvalue()

    def summaries(self):
        return list(self.db.execute("select kind_id, book_id, chapter, range_id, text from summary order by id"))

    def settle_chapters(self, kind, book, chapters):
        for chapter in chapters:
            job = jobs.Job(self.layer, f"{kind}/{book}/{chapter}")
            jobs.submit(self.db, job, [summary(kind, {"chapter": f"{book.title()} {chapter}"}, f"Chapter {chapter} " + FEW)])

    def test_jobs_exist_only_for_kinds_of_the_targets_work(self):
        self.add_range()
        scopes = self.layer.scopes(self.db)
        self.assertIn("original_words/genesis/5", scopes)
        self.assertNotIn("editors_comments/genesis/5", scopes)
        self.assertIn("editors_comments/mosiah/2", scopes)
        self.assertNotIn("culture/range/king-benjamins-sermon", scopes)
        self.assertIn("setting/range/king-benjamins-sermon", scopes)
        self.assertLess(scopes.index("setting/range/king-benjamins-sermon"), scopes.index("doctrine/genesis"))
        self.assertEqual(scopes[-1], "editors_comments/mosiah")

    def test_answers_round_trip_through_render(self):
        self.add_range()
        for scope, on, text in (
            ("doctrine/mosiah/2", {"chapter": "Mosiah 2"}, FEW),
            ("setting/range/king-benjamins-sermon", {"range": "king-benjamins-sermon"}, FEW),
            ("people/mosiah", {"book": "Mosiah"}, PARAGRAPH),
        ):
            tags = self.layer.parse(self.db, scope, [summary(scope.split("/")[0], on, "  " + text + " ")])
            self.assertEqual(self.layer.render(self.db, tags[0]), summary(scope.split("/")[0], on, text))
            self.assertEqual(self.layer.parse(self.db, scope, [self.layer.render(self.db, tags[0])]), tags)
            self.assertEqual(self.layer.fixed(self.db, scope) + self.layer.given(self.db, scope), [])

    def test_rejects_a_kind_or_target_other_than_the_jobs(self):
        with self.assertRaisesRegex(Rejected, 'kind must be "doctrine"'):
            self.layer.parse(self.db, "doctrine/mosiah/2", [summary("principles", {"chapter": "Mosiah 2"})])
        with self.assertRaisesRegex(Rejected, '"on" must be {"chapter": "Mosiah 2"}'):
            self.layer.parse(self.db, "doctrine/mosiah/2", [summary("doctrine", {"chapter": "Mosiah 3"})])
        with self.assertRaisesRegex(Rejected, '"on" must be {"book": "Mosiah"}'):
            self.layer.parse(self.db, "doctrine/mosiah", [summary("doctrine", {"chapter": "Mosiah 2"}, PARAGRAPH)])
        with self.assertRaisesRegex(Rejected, "missing text"):
            self.layer.parse(self.db, "doctrine/mosiah/2", [{"kind": "doctrine", "on": {"chapter": "Mosiah 2"}}])

    def test_rejects_more_than_one_summary(self):
        answer = [summary("doctrine", {"chapter": "Mosiah 2"})] * 2
        with self.assertRaisesRegex(Rejected, "one summary"):
            self.layer.parse(self.db, "doctrine/mosiah/2", answer)

    def test_rejects_text_that_is_not_a_few_full_sentences(self):
        for text, problem in (
            ("God is good.", "has 3 words"),
            (" ".join([FEW] * 5), "has 140 words"),
            (FEW.replace(". ", ".\n"), "line breaks"),
            (FEW.rstrip("."), "full sentence"),
        ):
            with self.assertRaisesRegex(Rejected, problem):
                self.layer.parse(self.db, "doctrine/mosiah/2", [summary("doctrine", {"chapter": "Mosiah 2"}, text)])
        with self.assertRaisesRegex(Rejected, "book summary has 50 to 250"):
            self.layer.parse(self.db, "doctrine/mosiah", [summary("doctrine", {"book": "Mosiah"})])

    def test_an_empty_answer_settles_with_no_summary(self):
        job = jobs.Job(self.layer, "prophecies/genesis/5")
        jobs.submit(self.db, job, [])
        self.assertIsNotNone(job.settled())
        self.assertEqual(self.summaries(), [])

    def test_a_stored_summary_is_stored_once(self):
        job = jobs.Job(self.layer, "doctrine/mosiah/2")
        jobs.submit(self.db, job, [summary("doctrine", {"chapter": "Mosiah 2"}, "Checked. " + FEW)])
        with self.assertRaisesRegex(Rejected, "already stored"):
            jobs.submit(self.db, job, [summary("doctrine", {"chapter": "Mosiah 2"})])
        self.assertEqual(self.summaries(), [("doctrine", "mosiah", 2, None, "Checked. " + FEW)])

    def test_store_then_unstore_leaves_the_table_as_it_was(self):
        self.add_range()
        tags = self.layer.parse(self.db, "setting/range/king-benjamins-sermon", [summary("setting", {"range": "king-benjamins-sermon"})])
        self.layer.store(self.db, "setting/range/king-benjamins-sermon", tags)
        self.assertEqual(len(self.summaries()), 1)
        self.layer.unstore(self.db, "setting/range/king-benjamins-sermon", tags)
        self.layer.unstore(self.db, "setting/range/king-benjamins-sermon", tags)
        self.assertEqual(self.summaries(), [])

    def test_the_database_refuses_a_kind_from_another_work(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("insert into summary (kind_id, book_id, chapter, text) values ('editors_comments', 'genesis', 5, 'x')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("insert into summary (kind_id, book_id, range_id, text) values ('doctrine', 'mosiah', null, 'x'), ('doctrine', 'mosiah', null, 'y')")

    def test_context_names_the_kind_target_and_range(self):
        self.add_range()
        context = job_text(self.db, jobs.Job(self.layer, "setting/range/king-benjamins-sermon"))
        self.assertIn("Kind: Setting. When, where, and why it happened or was written.", context)
        self.assertIn('{"from": "Mosiah 2:9", "to": "Mosiah 3:2"}', context)
        self.assertIn("# Mosiah 3", context)
        self.assertIn("0 The Book of Mosiah", job_text(self.db, jobs.Job(self.layer, "doctrine/mosiah/1")))

    def test_original_words_context_lists_the_hebrew_behind_the_chapter(self):
        self.db.execute("insert into edition_book (edition_id, book_id, position) values ('wlc', 'genesis', 1)")
        self.db.execute("insert into word (id, edition_id, book_id, chapter, verse, position, text) values (1000, 'wlc', 'genesis', 5, 1, 1, 'תּוֹלְדֹת')")
        self.db.execute("insert into headword (id, language, text, strongs, gloss) values (1, 'hbo', 'תּוֹלֵדָה', 'H8435', 'generations')")
        self.db.execute("insert into word_headword (word_id, headword_id, part_of_speech) values (1000, 1, 'noun')")
        kjv = self.db.execute("select id from word where text = 'generations'").fetchone()[0]
        self.db.execute("insert into word_match (word_id, other_word_id) values (?, 1000)", (kjv,))
        context = job_text(self.db, jobs.Job(self.layer, "original_words/genesis/5"))
        self.assertIn('H8435 תּוֹלֵדָה "generations": generations (5:1)', context)

    def test_range_commands_add_list_and_remove(self):
        self.assertIn('added king-benjamins-sermon: King Benjamin\'s sermon, {"from": "Mosiah 2:9", "to": "Mosiah 3:2"}', self.add_range())
        with redirect_stdout(io.StringIO()) as out:
            self.layer.list_ranges(self.db, Namespace())
        self.assertIn("king-benjamins-sermon\tKing Benjamin's sermon", out.getvalue())
        with redirect_stdout(io.StringIO()):
            self.layer.remove_range(self.db, Namespace(id="king-benjamins-sermon"))
        self.assertEqual(self.db.execute("select count(*) from verse_range").fetchone()[0], 0)

    def test_range_add_rejects_bad_ids_repeats_and_whole_chapters(self):
        for id, passage, problem in (
            ("King Benjamin", SERMON, "lowercase"),
            ("one-chapter", '{"chapter": "Mosiah 2"}', "all of Mosiah 2"),
            ("not-json", "{from", "not valid JSON"),
        ):
            with self.assertRaisesRegex(Rejected, problem):
                self.add_range(id, passage)
        self.add_range()
        with self.assertRaisesRegex(Rejected, "is a range already"):
            self.add_range()
        with self.assertRaisesRegex(Rejected, "covers the same passage"):
            self.add_range("the-sermon")

    def test_range_remove_refuses_a_range_with_summaries_or_answers(self):
        self.add_range()
        job = jobs.Job(self.layer, "setting/range/king-benjamins-sermon")
        jobs.submit(self.db, job, [summary("setting", {"range": "king-benjamins-sermon"})])
        with self.assertRaisesRegex(Rejected, "has summaries in summaries/setting/range/king-benjamins-sermon"):
            self.layer.remove_range(self.db, Namespace(id="king-benjamins-sermon"))


if __name__ == "__main__":
    unittest.main()
