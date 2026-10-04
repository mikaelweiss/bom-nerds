import unittest

from bomnerds.agent import jobs
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.show import show
from bomnerds.passages import Rejected
from tests.agent_fixtures import database, job_folder

SCOPE = "alma/36"
VERSES = {
    (36, 1): "My son, give ear to my words.",
    (36, 2): "Remember the captivity of our fathers, and their bondage.",
    (36, 3): "I would that ye should do as I have done.",
    (37, 1): "And now, my son, give ear to my words.",
    (37, 2): "Keep these records.",
}


def part(label, verse, quote=None, pairs_with=None, parts=None, chapter=36):
    passage = {"verse": f"Alma {chapter}:{verse}"}
    if quote:
        passage["quote"] = quote
    found = {"label": label, "passage": passage}
    if pairs_with:
        found["pairs_with"] = pairs_with
    if parts:
        found["parts"] = parts
    return found


def chiasm(*changes):
    structure = {"kind": "chiasm", "passage": {"from": "Alma 36:1", "to": "Alma 37:1"}, "parts": [
        part("A", 1),
        part("B", 2, parts=[part("B.1", 2, "Remember the captivity of our fathers"), part("B.2", 2, "their bondage")]),
        part("C", 3),
        part("A'", 1, pairs_with="A", chapter=37),
    ]}
    for change in changes:
        change(structure)
    return structure


def listing():
    return {"kind": "list", "passage": {"verse": "Alma 36:2"}, "parts": [part("1", 2, "the captivity of our fathers"), part("2", 2, "their bondage")]}


class StructuresTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bom", "Alma", VERSES)])
        self.addCleanup(self.db.close)
        self.folder = job_folder()
        self.folder.__enter__()
        self.addCleanup(self.folder.__exit__, None, None, None)
        self.layer = LAYERS["structures"]
        self.job = jobs.Job(self.layer, SCOPE)
        for layer in LAYERS.values():
            if layer.step < self.layer.step and layer.scope == "chapter":
                jobs.Job(layer, SCOPE).write("settled", [])

    def rejects(self, value, message):
        with self.assertRaisesRegex(Rejected, message):
            self.layer.parse(self.db, SCOPE, value)

    def rows(self):
        return (
            list(self.db.execute("select kind_id, first_word_id, last_word_id from structure order by id")),
            list(self.db.execute("select position, label, parent_id is not null, pairs_with_id is not null from structure_part order by position")),
        )

    def test_a_valid_answer_round_trips(self):
        tags = self.layer.parse(self.db, SCOPE, [chiasm(), listing()])
        self.assertEqual(len(tags), 2)
        self.assertEqual(self.layer.parse(self.db, SCOPE, [self.layer.render(self.db, t) for t in tags]), tags)
        self.assertEqual(self.layer.render(self.db, tags[0]), chiasm())

    def test_the_later_part_of_a_pair_names_the_earlier(self):
        def flip(structure):
            del structure["parts"][3]["pairs_with"]
            structure["parts"][0]["pairs_with"] = "A'"

        self.assertEqual(self.layer.parse(self.db, SCOPE, [chiasm(flip)]), self.layer.parse(self.db, SCOPE, [chiasm()]))

    def test_rejects_a_kind_not_on_the_list(self):
        self.rejects([dict(listing(), kind="poem")], "kind 'poem' is not one of")

    def test_rejects_a_structure_starting_in_another_chapter(self):
        self.rejects([dict(listing(), passage={"verse": "Alma 37:1"}, parts=[part("1", 1, "my son", chapter=37), part("2", 1, "my words", chapter=37)])], "must start in Alma 36")

    def test_rejects_a_part_outside_its_structure_or_parent(self):
        self.rejects([dict(listing(), parts=[part("1", 2), part("2", 3)])], "item 1, part 2: the part must sit inside its structure")
        self.rejects([chiasm(lambda s: s["parts"][1]["parts"].append(part("B.3", 3)))], "item 1, part 2.3: the part must sit inside its parent part")

    def test_rejects_overlapping_parts(self):
        self.rejects([dict(listing(), parts=[part("1", 2), part("2", 2, "their bondage")])], "parts 1 and 2 share words")

    def test_rejects_fewer_than_two_parts(self):
        self.rejects([dict(listing(), parts=[part("1", 2)])], "two or more")

    def test_rejects_a_label_used_twice(self):
        self.rejects([chiasm(lambda s: s["parts"][2].update(label="B.1"))], "'B.1' is used 2 times")

    def test_rejects_pairs_with_naming_no_label_in_the_structure(self):
        self.rejects([chiasm(lambda s: s["parts"][3].update(pairs_with="Z"))], "not a label in this structure")

    def test_rejects_a_part_pairing_twice(self):
        self.rejects([chiasm(lambda s: s["parts"][2].update(pairs_with="A"))], "pairs with A' and C|pairs with C and A'")

    def test_rejects_pairs_outside_a_chiasm(self):
        self.rejects([dict(listing(), parts=[part("1", 2, "the captivity of our fathers"), part("2", 2, "their bondage", pairs_with="1")])], "only chiasm parts pair")

    def test_rejects_a_chiasm_without_pairs(self):
        self.rejects([chiasm(lambda s: s["parts"][3].pop("pairs_with"))], "pairs each part")

    def test_store_numbers_parts_in_reading_order_and_unstore_removes_them(self):
        tags = self.layer.parse(self.db, SCOPE, [chiasm()])
        with self.db:
            self.layer.store(self.db, SCOPE, tags)
        self.assertEqual(self.rows()[1], [(1, "A", 0, 0), (2, "B", 0, 0), (3, "B.1", 1, 0), (4, "B.2", 1, 0), (5, "C", 0, 0), (6, "A'", 0, 1)])
        self.assertIn('"pairs_with": "A"', show(self.db, "alma", 37))
        with self.db:
            self.layer.unstore(self.db, SCOPE, tags)
        self.assertEqual(self.rows(), ([], []))

    def test_runs_that_agree_settle_and_reset_deletes(self):
        jobs.submit(self.db, self.job, [listing(), chiasm()])
        self.assertIsNotNone(self.job.settled())
        self.assertEqual(len(self.rows()[0]), 2)
        jobs.reset(self.db, self.job)
        self.assertEqual(self.rows(), ([], []))

if __name__ == "__main__":
    unittest.main()
