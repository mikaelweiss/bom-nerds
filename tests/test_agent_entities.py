import unittest
from unittest import mock

from bomnerds.agent import checks, jobs
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.layers import entities
from bomnerds.agent.layers.entities import groups, Catalog
from bomnerds.agent.prompt import job_text
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
        jobs.submit(self.db, job, answer)

    def test_a_pick_and_a_new_entity_round_trip(self):
        answer = [{"pick": "jesus-christ", "titles": ["the Holy One of Israel"]}, SARIAH, LEHI]
        tags = jobs.check(self.db, self.job, answer)
        self.assertEqual(self.layer.parse(self.db, "1-nephi", [self.layer.render(self.db, t) for t in tags]), tags)

    def test_context_shows_the_chapters_and_entities_named_in_the_book(self):
        text = job_text(self.db, self.job)
        self.assertIn("2 And Sariah my mother praised the Holy One of Israel.", text)
        self.assertIn("lehi (city) Lehi.", text)
        self.assertNotIn("jesus-christ (person)", text)

    def test_an_id_is_the_bare_name_when_no_other_entity_shares_it(self):
        with self.assertRaisesRegex(Rejected, "no other entity is named \"Sariah\", so the id is sariah"):
            jobs.check(self.db, self.job, [{**SARIAH, "id": "sariah-wife-of-lehi"}])

    def test_a_shared_name_needs_a_qualifier_and_renames_the_bare_older_id(self):
        with self.assertRaisesRegex(Rejected, "lehi is already on the list"):
            jobs.check(self.db, self.job, [{**LEHI, "id": "lehi", "renames": {}}])
        with self.assertRaisesRegex(Rejected, 'add "renames": { "lehi": "lehi-..." }'):
            jobs.check(self.db, self.job, [{**LEHI, "renames": {}}])
        with self.assertRaisesRegex(Rejected, "must be lehi followed by what sets it apart"):
            jobs.check(self.db, self.job, [{**LEHI, "renames": {"lehi": "city-of-lehi"}}])

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
                jobs.check(self.db, self.job, answer)

    def test_topics_and_events_need_not_be_named_in_the_text(self):
        answer = [{"id": "faith", "type": "topic", "name": "Faith", "other_names": [], "description": "Trust in Jesus Christ."}]
        self.assertEqual(len(jobs.check(self.db, self.job, answer)), 1)

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
        with self.assertRaisesRegex(Rejected, "Reset those first"):
            jobs.reset(self.db, self.job)

    def test_entities_for_all_of_scripture_name_their_books(self):
        scripture = jobs.Job(self.layer, "scripture")
        narrator = {"id": "bible-narrator", "type": "person", "name": "Bible narrator", "other_names": [], "description": "Narrator of the Bible."}
        with self.assertRaisesRegex(Rejected, 'takes "books"'):
            jobs.check(self.db, scripture, [narrator])
        with self.assertRaisesRegex(Rejected, "is not a book id"):
            jobs.check(self.db, scripture, [{**narrator, "books": ["genesis"]}])
        self.settle(scripture, [{**narrator, "books": ["judges"]}])
        self.assertIn(("bible-narrator", "judges"), list(self.db.execute("select * from entity_book")))
        with self.assertRaisesRegex(Rejected, '"books" belongs only to entities added for all of scripture'):
            jobs.check(self.db, self.job, [{**SARIAH, "books": []}])

    def test_long_books_split_into_parts_of_their_chapters(self):
        db = database([("bom", "Alma", {(1, 1): "One two three four five.", (2, 1): "Six seven eight nine ten.", (3, 1): "Eleven twelve."})])
        with mock.patch.object(entities, "PART_WORDS", 6):
            scopes = self.layer.scopes(db)
        self.assertEqual(scopes, ["scripture", "alma/1-2", "alma/3-3"])
        self.assertEqual([self.layer.label(db, s) for s in scopes], ["All of scripture", "Alma 1–2", "Alma 3"])
        self.assertEqual(self.layer.chapters(db, "alma/1-2"), [("alma", 1), ("alma", 2)])


class DuplicatesTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bible", "Judges", JUDGES), ("bom", "1 Nephi", FIRST_NEPHI), ("bom", "2 Nephi", SECOND_NEPHI)])
        entity(self.db, "lehi", "city", "Lehi", "A place where Samson fought the Philistines.", books=("judges",))
        entity(self.db, "lehi-father-of-nephi", "person", "Lehi", "Father of Nephi.", books=("1-nephi",))
        entity(self.db, "zarahemla", "land", "Zarahemla", "Land of the Nephites.", books=("2-nephi",))
        entity(self.db, "land-of-zarahemla", "land", "Land of Zarahemla", "Land where the Nephites lived.", other_names=("Zarahemla",), books=("1-nephi",))

    def test_groups_join_entities_of_one_kind_that_share_a_name(self):
        found = groups(Catalog(self.db))
        self.assertEqual(found["l"], [["land-of-zarahemla", "zarahemla"]])
        self.assertNotIn(["lehi", "lehi-father-of-nephi"], found["l"])

    def test_the_review_sees_them_as_a_finding(self):
        found = checks.findings(self.db, "entities", LAYERS["entities"].scopes(self.db))
        self.assertEqual([f.scope for f in found], ["1-nephi"])
        self.assertIn("land-of-zarahemla (land) Land of Zarahemla.", found[0].text)


if __name__ == "__main__":
    unittest.main()
