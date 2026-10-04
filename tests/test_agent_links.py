import unittest
from unittest import mock

from bomnerds.agent import jobs
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.layers.links import Links
from bomnerds.agent.prompt import job_text
from bomnerds.passages import Rejected
from tests.agent_fixtures import database, job_folder

ISAIAH = {
    (2, 2): "And it shall come to pass in the last days, that the mountain of the LORD'S house shall be established.",
    (2, 3): "And many people shall go and say, Come ye, and let us go up to the mountain of the LORD.",
    (7, 14): "Behold, a virgin shall conceive, and bear a son, and shall call his name Immanuel.",
    (7, 15): "Butter and honey shall he eat.",
}
MATTHEW = {(1, 22): "Now all this was done, that it might be fulfilled.", (1, 23): "Behold, a virgin shall be with child, and shall bring forth a son."}
NEPHI = {(12, 1): "The word that Isaiah the son of Amoz saw.", (12, 2): "And it shall come to pass in the last days, that the mountain of the Lord's house shall be established."}
ALMA = {(36, 1): "My son, give ear to my words.", (36, 2): "I do know that whosoever shall put their trust in God."}

FULFILLS = {"kind": "fulfills", "from": {"verse": "Matthew 1:23"}, "to": {"verse": "Isaiah 7:14"}}
ALLUDES = {"kind": "alludes_to", "from": {"verse": "2 Nephi 12:1"}, "to": {"verse": "Isaiah 7:14"}}
CROSS = {"kind": "cross_reference", "from": {"verse": "2 Nephi 12:2"}, "to": {"verse": "Isaiah 2:2"}}
REVERSE = {"kind": "cross_reference", "from": {"verse": "Isaiah 2:2"}, "to": {"verse": "2 Nephi 12:2"}}


class LinksTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bible", "Isaiah", ISAIAH), ("bible", "Matthew", MATTHEW), ("bom", "2 Nephi", NEPHI), ("bom", "Alma", ALMA)])
        self.layer = Links()
        layers = mock.patch.dict(LAYERS, {"links": self.layer}, clear=True)
        layers.start()
        self.addCleanup(layers.stop)
        self.folder = job_folder()
        self.folder.__enter__()
        self.addCleanup(self.folder.__exit__, None, None, None)
        self.job = jobs.Job(self.layer, "2-nephi/12")

    def parse(self, *answer, scope="2-nephi/12"):
        return self.layer.parse(self.db, scope, list(answer))

    def rejects(self, pattern, *answer, scope="2-nephi/12"):
        with self.assertRaisesRegex(Rejected, pattern):
            self.parse(*answer, scope=scope)

    def span(self, book, chapter, verse):
        return self.db.execute("select min(id), max(id) from word where book_id = ? and chapter = ? and verse = ?", (book, chapter, verse)).fetchone()

    def link(self, kind, a, b):
        self.db.execute(
            "insert into passage_link (kind_id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id) values (?, ?, ?, ?, ?)", (kind, *self.span(*a), *self.span(*b))
        )

    def links(self):
        return list(self.db.execute("select kind_id, from_first_word_id, to_first_word_id from passage_link order by id"))

    def test_one_way_links_round_trip_through_render(self):
        tags = self.parse(ALLUDES, {"kind": "alludes_to", "from": {"verse": "2 Nephi 12:2"}, "to": {"verse": "Isaiah 2:2"}})
        self.assertEqual([self.layer.render(self.db, t) for t in tags][0], ALLUDES)
        self.assertEqual(self.layer.parse(self.db, "2-nephi/12", [self.layer.render(self.db, t) for t in tags]), tags)
        self.assertEqual(self.parse(FULFILLS, scope="matthew/1")[0][0], "fulfills")

    def test_a_two_way_link_is_stored_from_the_passage_that_comes_first(self):
        tag = self.parse(CROSS)[0]
        self.assertLess(tag[1:3], tag[3:5])
        rendered = self.layer.render(self.db, tag)
        self.assertEqual(rendered["from"], {"verse": "Isaiah 2:2"})
        self.assertEqual(self.layer.parse(self.db, "2-nephi/12", [rendered]), [tag])
        self.layer.store(self.db, "2-nephi/12", [tag])

    def test_both_directions_of_a_cross_reference_are_one_tag(self):
        self.assertEqual(self.parse(CROSS), self.parse(REVERSE))
        self.rejects("twice", CROSS, REVERSE)

    def test_a_cross_reference_joins_two_works(self):
        self.rejects("both passages are in the Bible", {"kind": "cross_reference", "from": {"verse": "Matthew 1:23"}, "to": {"verse": "Isaiah 7:14"}}, scope="matthew/1")
        self.rejects("both passages are in the Book of Mormon", {"kind": "cross_reference", "from": {"verse": "2 Nephi 12:1"}, "to": {"verse": "Alma 36:1"}})

    def test_rejects_a_kind_the_script_writes(self):
        self.rejects("kind 'quotes' is not one of: alludes_to, fulfills, cross_reference", {**ALLUDES, "kind": "quotes"})

    def test_from_sits_in_the_chapter_for_a_one_way_link(self):
        self.rejects("item 1: \"from\" must sit inside 2 Nephi 12", {"kind": "alludes_to", "from": {"verse": "Alma 36:1"}, "to": {"verse": "2 Nephi 12:1"}})

    def test_one_end_of_a_cross_reference_sits_in_the_chapter(self):
        self.rejects("an end must sit inside 2 Nephi 12", {"kind": "cross_reference", "from": {"verse": "Isaiah 2:3"}, "to": {"verse": "Matthew 1:23"}})

    def test_rejects_a_link_to_itself(self):
        self.rejects("overlap", {"kind": "alludes_to", "from": {"verse": "2 Nephi 12:1"}, "to": {"chapter": "2 Nephi 12"}})

    def test_rejects_every_problem_and_names_the_end_that_is_wrong(self):
        with self.assertRaises(Rejected) as caught:
            self.parse({"kind": "alludes_to", "from": {"verse": "2 Nephi 12:1", "quote": "Zion"}, "to": {"verse": "Isaiah 9:9"}}, {"kind": "alludes_to", "from": {"verse": "2 Nephi 12:1"}})
        message = str(caught.exception)
        self.assertIn("item 1 from:", message)
        self.assertIn("item 1 to:", message)
        self.assertIn("item 2: missing to", message)

    def test_rejects_unknown_fields_and_a_fact_twice(self):
        self.rejects("unknown field note", {**ALLUDES, "note": "x"})
        self.rejects("twice", ALLUDES, ALLUDES)

    def test_store_then_unstore_leaves_the_table_as_it_was(self):
        tags = self.parse(ALLUDES, CROSS)
        self.layer.store(self.db, "2-nephi/12", tags)
        self.assertEqual(len(self.links()), 2)
        self.layer.store(self.db, "2-nephi/12", tags)
        self.assertEqual(len(self.links()), 2)
        self.layer.unstore(self.db, "2-nephi/12", tags)
        self.assertEqual(self.links(), [])
        self.layer.unstore(self.db, "2-nephi/12", tags)

    def test_given_holds_the_links_to_read_but_not_the_bible_cross_references(self):
        self.link("quotes", ("2-nephi", 12, 2), ("isaiah", 2, 2))
        self.link("cross_reference", ("isaiah", 2, 2), ("isaiah", 7, 14))
        self.link("cross_reference", ("isaiah", 2, 3), ("isaiah", 7, 14))
        given = self.layer.given(self.db, "2-nephi/12")
        self.assertEqual([t[0] for t in given], ["quotes"])
        self.assertEqual([t[0] for t in self.layer.given(self.db, "isaiah/2")], ["quotes"])
        self.assertEqual(self.layer.given(self.db, "alma/36"), [])

    def test_a_link_another_job_stored_is_already_tagged(self):
        self.layer.store(self.db, "isaiah/2", self.parse(CROSS))
        with self.assertRaisesRegex(Rejected, "already tagged"):
            jobs.check(self.db, self.job, [REVERSE])

    def test_shown_counts_the_bible_cross_references_instead_of_listing_them(self):
        self.link("quotes", ("2-nephi", 12, 2), ("isaiah", 2, 2))
        self.link("cross_reference", ("isaiah", 2, 2), ("isaiah", 7, 14))
        self.link("cross_reference", ("isaiah", 2, 3), ("isaiah", 7, 14))
        shown = self.layer.shown(self.db, "kjv", "isaiah", 2)
        self.assertEqual(shown[0]["kind"], "quotes")
        self.assertEqual(shown[1], {"kind": "cross_reference", "count": 2})
        self.assertEqual(len(shown), 2)
        self.assertEqual(self.layer.shown(self.db, "kjv", "matthew", 1), [])

    def test_the_prompt_lists_given_links_and_the_count(self):
        self.link("quotes", ("2-nephi", 12, 2), ("isaiah", 2, 2))
        self.link("cross_reference", ("isaiah", 2, 2), ("isaiah", 7, 14))
        text = job_text(self.db, jobs.Job(self.layer, "isaiah/2"))
        self.assertIn('"kind": "quotes"', text)
        self.assertIn("## Cross-references the script stored", text)
        self.assertNotIn("## Cross-references the script stored", job_text(self.db, self.job))

    def test_a_stored_answer_replays_and_resets(self):
        jobs.submit(self.db, self.job, [ALLUDES, REVERSE])
        self.assertIsNotNone(self.job.settled())
        self.assertEqual(len(self.links()), 2)
        self.db.execute("delete from passage_link")
        jobs.replay(self.db, [self.layer])
        self.assertEqual(len(self.links()), 2)
        jobs.reset(self.db, self.job)
        self.assertEqual(self.links(), [])


if __name__ == "__main__":
    unittest.main()
