import argparse
import contextlib
import io
import json
import unittest

from bomnerds.agent import jobs
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.layers.entities import add_entity, groups, Catalog
from bomnerds.agent.prompt import prompt
from bomnerds.passages import Rejected
from tests.agent_fixtures import database, entity, job_folder

JUDGES = {(15, 14): "And when he came unto Lehi, the Philistines shouted against him."}
FIRST_NEPHI = {
    (1, 1): "I, Nephi, having been born of goodly parents, and my father Lehi went into the wilderness.",
    (1, 2): "And Sariah my mother praised the Holy One of Israel.",
}
SECOND_NEPHI = {(1, 1): "And Nephi went with his brethren into the land of Zarahemla, which is called Zarahemla."}

SARIAH = {"id": "sariah", "type": "person", "name": "Sariah", "other_names": [], "description": "Wife of Lehi."}
LEHI = {"id": "lehi-father-of-nephi", "type": "person", "name": "Lehi", "other_names": [], "description": "Father of Nephi.", "renames": {"lehi": "lehi-in-judah"}}


def tables(db):
    return {table: sorted(db.execute(f"select * from {table}")) for table in ("entity", "entity_name", "entity_book", "mention")}


class EntitiesTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bible", "Judges", JUDGES), ("bom", "1 Nephi", FIRST_NEPHI), ("bom", "2 Nephi", SECOND_NEPHI)])
        entity(self.db, "lehi", "city", "Lehi", "A place where Samson fought the Philistines.", books=("judges",))
        entity(self.db, "jesus-christ", "person", "Jesus Christ", "The Son of God.")
        self.folder = job_folder()
        self.path = self.folder.__enter__()
        self.addCleanup(self.folder.__exit__, None, None, None)
        self.layer = LAYERS["entities"]
        self.job = jobs.Job(self.layer, "1-nephi")

    def settle(self, job, answer):
        jobs.submit(self.db, job, "writer", answer)
        jobs.submit(self.db, job, "checker", answer)

    def test_a_pick_and_a_new_entity_round_trip(self):
        answer = [{"pick": "jesus-christ", "titles": ["the Holy One of Israel"]}, SARIAH, LEHI]
        tags = jobs.check(self.db, self.job, "writer", answer)
        self.assertEqual(self.layer.parse(self.db, "1-nephi", [self.layer.render(self.db, t) for t in tags]), tags)

    def test_jobs_follow_edition_order_and_wait_for_the_book_before(self):
        self.assertEqual(self.layer.scopes(self.db), ["1-nephi", "2-nephi"])
        self.assertIn("entities/1-nephi must settle first", jobs.Job(self.layer, "2-nephi").state(self.db))
        self.settle(self.job, [])
        self.assertEqual(jobs.Job(self.layer, "2-nephi").state(self.db), "needs writer")

    def test_context_lists_chapters_and_entities_named_in_the_book(self):
        text = prompt(self.db, self.job, "writer")
        self.assertIn('show "1 Nephi 1"', text)
        self.assertIn("lehi (city) Lehi.", text)
        self.assertNotIn("jesus-christ (person)", text)

    def test_an_id_is_the_bare_name_when_no_other_entity_shares_it(self):
        with self.assertRaisesRegex(Rejected, "no other entity is named \"Sariah\", so the id is sariah"):
            jobs.check(self.db, self.job, "writer", [{**SARIAH, "id": "sariah-wife-of-lehi"}])

    def test_a_shared_name_needs_a_qualifier_and_renames_the_bare_older_id(self):
        with self.assertRaisesRegex(Rejected, "lehi is already on the list"):
            jobs.check(self.db, self.job, "writer", [{**LEHI, "id": "lehi", "renames": {}}])
        with self.assertRaisesRegex(Rejected, 'add "renames": { "lehi": "lehi-..." }'):
            jobs.check(self.db, self.job, "writer", [{**LEHI, "renames": {}}])
        with self.assertRaisesRegex(Rejected, "must be lehi followed by what sets it apart"):
            jobs.check(self.db, self.job, "writer", [{**LEHI, "renames": {"lehi": "city-of-lehi"}}])

    def test_rejects_what_the_list_or_the_book_does_not_hold(self):
        cases = [
            ([{"pick": "laban"}], "'laban' is not on the entity list"),
            ([{**SARIAH, "name": "Sarai", "id": "sarai"}], '"Sarai" is not in 1 Nephi'),
            ([{**SARIAH, "type": "angel"}], "type 'angel' is not one of"),
            ([{"pick": "jesus-christ", "other_names": ["Jesus Christ"]}], "already a name of jesus-christ"),
            ([SARIAH, {"pick": "sariah"}], "sariah is in items 1, 2. List each entity once"),
            ([LEHI, {"pick": "lehi"}], "renamed to lehi-in-judah in this answer, so pick it by that id"),
            ([{"name": "Sariah"}], 'picks an entity with "pick" or adds one with "id"'),
            ([{**SARIAH, "description": "Wife\nof Lehi."}], "the description is one line"),
        ]
        for answer, message in cases:
            with self.subTest(message), self.assertRaisesRegex(Rejected, message):
                jobs.check(self.db, self.job, "writer", answer)

    def test_topics_and_events_need_not_be_named_in_the_text(self):
        answer = [{"id": "faith", "type": "topic", "name": "Faith", "other_names": [], "description": "Trust in Jesus Christ."}]
        self.assertEqual(len(jobs.check(self.db, self.job, "writer", answer)), 1)

    def test_store_renames_the_older_entity_and_saved_answers_follow(self):
        names = jobs.Job(LAYERS["names"], "judges/15")
        names.write("settled", [{"entity": "lehi", "passage": {"verse": "Judges 15:14", "quote": "Lehi"}}])
        self.settle(self.job, [{"pick": "lehi-in-judah"}, LEHI, {"pick": "jesus-christ", "titles": ["the Holy One of Israel"]}])
        self.assertEqual(sorted(id for (id,) in self.db.execute("select id from entity")), ["jesus-christ", "lehi-father-of-nephi", "lehi-in-judah"])
        self.assertEqual(names.settled()[0]["entity"], "lehi-in-judah")
        self.assertIn(("lehi-in-judah", "1-nephi"), list(self.db.execute("select * from entity_book")))
        self.assertIn(("jesus-christ", "the Holy One of Israel", 1), list(self.db.execute("select * from entity_name")))

    def test_reset_deletes_what_the_job_stored(self):
        before = tables(self.db)
        self.settle(self.job, [SARIAH, {"pick": "lehi", "titles": ["my father"]}])
        self.assertNotEqual(tables(self.db), before)
        jobs.reset(self.db, self.job)
        self.assertEqual(tables(self.db), before)

    def test_replay_stores_again_while_later_tags_point_at_its_entities(self):
        self.settle(self.job, [SARIAH])
        word = self.db.execute("select id from word where text = 'Sariah'").fetchone()[0]
        self.db.execute("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values ('sariah', 'names', ?, ?)", (word, word))
        jobs.replay(self.db, [self.layer])
        self.assertEqual(self.db.execute("select entity_id from mention").fetchall(), [("sariah",)])
        with self.assertRaisesRegex(Rejected, "Reset those jobs first"):
            jobs.reset(self.db, self.job)

    def test_add_entity_renames_the_older_id_and_prints_the_resets(self):
        reporting = jobs.Job(LAYERS["names"], "1-nephi/1")
        reporting.write("a", [])
        jobs.Job(LAYERS["names"], "judges/15").write("settled", [])
        args = argparse.Namespace(job=reporting.id, name="Lehi", type="person", description="Father of Nephi.", verse="1 Nephi 1:1", id="lehi-father-of-nephi", other_names=[], titles=[], rename=["lehi=lehi-in-judah"])
        with self.assertRaisesRegex(Rejected, "--rename OLD=NEW"):
            add_entity(self.db, argparse.Namespace(**{**vars(args), "rename": []}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            add_entity(self.db, args)
        self.assertTrue(self.db.execute("select 1 from entity where id = 'lehi-in-judah'").fetchone())
        self.assertIn("reset names/1-nephi/1", out.getvalue())
        self.assertIn("reset names/judges/15", out.getvalue())


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bible", "Judges", JUDGES), ("bom", "1 Nephi", FIRST_NEPHI), ("bom", "2 Nephi", SECOND_NEPHI)])
        entity(self.db, "lehi", "city", "Lehi", "A place where Samson fought the Philistines.", books=("judges",))
        entity(self.db, "lehi-father-of-nephi", "person", "Lehi", "Father of Nephi.", books=("1-nephi",))
        entity(self.db, "zarahemla", "land", "Zarahemla", "Land of the Nephites.", books=("2-nephi",))
        entity(self.db, "land-of-zarahemla", "land", "Land of Zarahemla", "Land where the Nephites lived.", other_names=("Zarahemla",), books=("1-nephi",))
        self.folder = job_folder()
        self.path = self.folder.__enter__()
        self.addCleanup(self.folder.__exit__, None, None, None)
        self.layer = LAYERS["merge"]
        self.job = jobs.Job(self.layer, "z")

    def settle_entities(self):
        jobs.Job(LAYERS["entities"], "1-nephi").write("settled", [{"id": "land-of-zarahemla", "type": "land", "name": "Land of Zarahemla", "other_names": ["Zarahemla"], "description": "Land where the Nephites lived."}])
        jobs.Job(LAYERS["entities"], "2-nephi").write("settled", [{"id": "zarahemla", "type": "land", "name": "Zarahemla", "other_names": [], "description": "Land of the Nephites."}])

    def test_waits_for_every_entities_job(self):
        self.assertIn("every entities job must settle first", self.job.state(self.db))
        self.settle_entities()
        self.assertEqual(self.job.state(self.db), "needs writer")

    def test_groups_join_entities_of_one_kind_that_share_a_name(self):
        found = groups(Catalog(self.db))
        self.assertEqual(found["l"], [["land-of-zarahemla", "zarahemla"]])
        self.assertNotIn(["lehi", "lehi-father-of-nephi"], found["l"])
        self.settle_entities()
        self.assertIn("zarahemla (land) Zarahemla.", prompt(self.db, jobs.Job(self.layer, "l"), "writer"))

    def test_rejects_merges_outside_a_group_or_of_a_bible_entity(self):
        self.settle_entities()
        job = jobs.Job(self.layer, "l")
        entity(self.db, "laban", "person", "Laban", "Keeper of the brass plates.", books=("1-nephi",))
        cases = [
            ([{"keep": "lehi-father-of-nephi", "merge": ["lehi"]}], "lehi is on the Bible list"),
            ([{"keep": "zarahemla", "merge": ["lehi-father-of-nephi"]}], "is a person and zarahemla a land"),
            ([{"keep": "lehi-father-of-nephi", "merge": ["laban"]}], "are not in one group"),
            ([{"keep": "zarahemla", "merge": ["zarahemla"]}], "leave the kept one out"),
            ([{"keep": "zarahemla", "merge": ["nowhere"]}], "nowhere is not on the entity list"),
        ]
        for answer, message in cases:
            with self.subTest(message), self.assertRaisesRegex(Rejected, message):
                jobs.check(self.db, job, "writer", answer)

    def test_a_merge_moves_every_tag_to_the_kept_entity(self):
        self.settle_entities()
        names = jobs.Job(LAYERS["names"], "2-nephi/1")
        names.write("settled", [{"entity": "zarahemla", "passage": {"verse": "2 Nephi 1:1", "quote": "Zarahemla", "in": "called Zarahemla"}}])
        word = self.db.execute("select max(id) from word where text = 'Zarahemla'").fetchone()[0]
        self.db.execute("insert into mention (entity_id, kind_id, first_word_id, last_word_id) values ('zarahemla', 'names', ?, ?)", (word, word))
        self.db.execute("insert into relationship (subject_id, kind_id, object_id) values ('zarahemla', 'kept_by', 'lehi-father-of-nephi')")
        job = jobs.Job(self.layer, "l")
        answer = [{"keep": "land-of-zarahemla", "merge": ["zarahemla"]}]
        jobs.submit(self.db, job, "writer", answer)
        jobs.submit(self.db, job, "checker", answer)
        self.assertIsNone(self.db.execute("select 1 from entity where id = 'zarahemla'").fetchone())
        self.assertEqual(self.db.execute("select entity_id from mention").fetchall(), [("land-of-zarahemla",)])
        self.assertEqual(self.db.execute("select subject_id from relationship").fetchall(), [("land-of-zarahemla",)])
        self.assertEqual(sorted(self.db.execute("select book_id from entity_book where entity_id = 'land-of-zarahemla'")), [("1-nephi",), ("2-nephi",)])
        self.assertEqual(names.settled()[0]["entity"], "land-of-zarahemla")
        self.assertEqual(jobs.Job(LAYERS["entities"], "2-nephi").settled(), [{"pick": "land-of-zarahemla"}])
        self.assertEqual(job.settled(), answer)
        self.assertEqual(LAYERS["entities"].parse(self.db, "2-nephi", jobs.Job(LAYERS["entities"], "2-nephi").settled()), LAYERS["entities"].parse(self.db, "2-nephi", [{"pick": "land-of-zarahemla"}]))

    def test_reset_keeps_the_merges_and_says_so(self):
        self.settle_entities()
        job = jobs.Job(self.layer, "l")
        answer = [{"keep": "land-of-zarahemla", "merge": ["zarahemla"]}]
        jobs.submit(self.db, job, "writer", answer)
        jobs.submit(self.db, job, "checker", answer)
        before = tables(self.db)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            jobs.reset(self.db, job)
        self.assertEqual(tables(self.db), before)
        self.assertIn("merges are never undone", err.getvalue())
        self.assertEqual(job.state(self.db), "needs writer")


if __name__ == "__main__":
    unittest.main()
