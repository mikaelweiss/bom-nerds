import unittest

from bomnerds.agent import jobs
from bomnerds.agent.layers import LAYERS
from bomnerds.agent.prompt import job_text
from bomnerds.agent.show import show
from bomnerds.passages import Rejected
from bomnerds.sentences import split
from tests.agent_fixtures import database, job_folder

SCOPE = "1-nephi/3"
VERSES = {
    (3, 1): "And I said: I will go.",
    (3, 2): "The Lord hath commanded me. And they went and they returned.",
}


def at(verse, quote=None, within=None):
    passage = {"verse": f"1 Nephi 3:{verse}"}
    if quote:
        passage["quote"] = quote
    if within:
        passage["in"] = within
    return passage


def part(role, verse, quote, within=None):
    return {"role": role, "passage": at(verse, quote, within)}


def clause(verse, quote, parts, clauses=None):
    found = {"passage": at(verse, quote), "parts": parts}
    if clauses:
        found["clauses"] = clauses
    return found


def go():
    return clause(1, "I will go", [part("subject", 1, "I", "I will"), part("verb", 1, "will go")])


def said(inner=None):
    return clause(1, "I said: I will go", [part("subject", 1, "I", "I said"), part("verb", 1, "said"), part("object", 1, "I will go")], [inner or go()])


def answer(first=None):
    return [
        {"sentence": at(1), "clauses": [first or said()]},
        {"sentence": at(2, "The Lord hath commanded me"), "clauses": [clause(2, "The Lord hath commanded me", [part("subject", 2, "The Lord"), part("verb", 2, "hath commanded"), part("object", 2, "me")])]},
        {"sentence": at(2, "And they went and they returned"), "clauses": [
            clause(2, "they went", [part("subject", 2, "they", "they went"), part("verb", 2, "went")]),
            clause(2, "they returned", [part("subject", 2, "they", "they returned"), part("verb", 2, "returned")]),
        ]},
    ]


class GrammarTest(unittest.TestCase):
    def setUp(self):
        self.db = database([("bom", "1 Nephi", VERSES)])
        self.addCleanup(self.db.close)
        words = list(self.db.execute("select id, edition_id, book_id, chapter, verse, text, after from word order by id"))
        self.db.executemany("insert into sentence (first_word_id, last_word_id) values (?, ?)", split(words))
        self.agree("I will go", "verb", "will go")
        self.agree("they went", "subject", "they")
        self.folder = job_folder()
        self.folder.__enter__()
        self.addCleanup(self.folder.__exit__, None, None, None)
        self.layer = LAYERS["grammar"]
        self.job = jobs.Job(self.layer, SCOPE)
        for layer in LAYERS.values():
            if layer.step < self.layer.step and layer.scope == "chapter":
                jobs.Job(layer, SCOPE).write("settled", [])

    def span(self, words):
        """First and last word id of the first run of these words."""
        texts = [w.strip(".:,") for w in words.split()]
        rows = list(self.db.execute("select id, text from word order by id"))
        for i in range(len(rows)):
            if [t for _, t in rows[i:i + len(texts)]] == texts:
                return rows[i][0], rows[i + len(texts) - 1][0]
        raise ValueError(words)

    def agree(self, words, role, part_words):
        first, last = self.span(words)
        sentence = self.db.execute("select id from sentence where first_word_id <= ? and last_word_id >= ?", (first, last)).fetchone()[0]
        clause_id = self.db.execute("insert into clause (sentence_id, first_word_id, last_word_id) values (?, ?, ?)", (sentence, first, last)).lastrowid
        self.db.execute("insert into clause_part (clause_id, role_id, first_word_id, last_word_id) values (?, ?, ?, ?)", (clause_id, role, *self.span(part_words)))

    def rows(self):
        clauses = set(self.db.execute("select c.sentence_id, p.first_word_id, p.last_word_id, c.first_word_id, c.last_word_id from clause c left join clause p on p.id = c.parent_id"))
        parts = set(self.db.execute("select c.first_word_id, c.last_word_id, role_id, p.first_word_id, p.last_word_id from clause_part p join clause c on c.id = p.clause_id"))
        return clauses, parts

    def rejects(self, value, message):
        with self.assertRaisesRegex(Rejected, message):
            self.layer.parse(self.db, SCOPE, value)

    def test_a_valid_answer_round_trips(self):
        tags = self.layer.parse(self.db, SCOPE, answer())
        self.assertEqual(len(tags), 3)
        self.assertEqual(self.layer.parse(self.db, SCOPE, [self.layer.render(self.db, t) for t in tags]), tags)

    def test_clause_order_in_the_answer_does_not_matter(self):
        flipped = answer()
        flipped[2]["clauses"].reverse()
        flipped.reverse()
        self.assertEqual(set(self.layer.parse(self.db, SCOPE, flipped)), set(self.layer.parse(self.db, SCOPE, answer())))

    def test_rejects_a_clause_outside_its_sentence(self):
        broken = answer()
        broken[1]["clauses"].append(clause(2, "they went", [part("verb", 2, "went")]))
        self.rejects(broken, "item 2, clause 2: the clause must sit inside its sentence")

    def test_rejects_a_part_outside_its_clause(self):
        broken = answer(said(clause(1, "I will go", [part("verb", 1, "will go"), part("subject", 1, "I", "I said")])))
        self.rejects(broken, "item 1, clause 1.1, part 2: the part must sit inside its clause")

    def test_rejects_a_nested_clause_outside_its_parent(self):
        broken = answer()
        broken[2]["clauses"][0]["clauses"] = [clause(2, "they returned", [part("verb", 2, "returned")])]
        self.rejects(broken, "item 3, clause 1.1: the clause must sit inside its parent clause")

    def test_rejects_overlapping_sibling_clauses(self):
        broken = answer()
        broken[0]["clauses"].append(go())
        self.rejects(broken, "item 1: the clauses .* share words")

    def test_rejects_overlapping_parts(self):
        broken = answer(said(clause(1, "I will go", [part("subject", 1, "I will"), part("verb", 1, "will go")])))
        self.rejects(broken, "parts .* share words")

    def test_rejects_two_verbs_in_one_clause(self):
        broken = answer()
        broken[2]["clauses"] = [clause(2, "they went and they returned", [part("verb", 2, "went"), part("verb", 2, "returned")])]
        self.rejects(broken, "2 verb parts")

    def test_rejects_a_missing_sentence(self):
        self.rejects(answer()[:2], "the sentence .*And they went and they returned.* is missing")

    def test_rejects_a_passage_that_is_not_a_sentence(self):
        broken = answer()
        broken.append({"sentence": at(2, "they returned"), "clauses": []})
        self.rejects(broken, "item 4: this is not a whole sentence")

    def test_rejects_a_sentence_answered_twice(self):
        self.rejects(answer() + answer()[1:2], "item 4: this sentence is item 2 too")

    def test_rejects_a_missing_fixed_clause_or_part(self):
        self.rejects(answer(said(clause(1, "I will go", [part("subject", 1, "I", "I will")]))), "the fixed verb .*will go.* is missing")
        broken = answer()
        broken[2]["clauses"] = broken[2]["clauses"][1:]
        self.rejects(broken, "the fixed clause .*they went.* is missing")

    def test_context_shows_every_sentence_with_its_fixed_parts(self):
        context = job_text(self.db, jobs.Job(self.layer, SCOPE))
        fixed = context.split("## Sentences and their fixed clauses")[1]
        self.assertEqual(fixed.count('{"sentence"'), 3)
        self.assertIn('"role": "verb", "passage": {"verse": "1 Nephi 3:1", "quote": "will go"}', fixed)
        self.assertNotIn("Already tagged", job_text(self.db, self.job))

    def test_store_then_unstore_leaves_the_tables_as_they_were(self):
        before = self.rows()
        tags = self.layer.parse(self.db, SCOPE, answer())
        with self.db:
            self.layer.store(self.db, SCOPE, tags)
        self.assertEqual(len(self.rows()[0]), 5)
        parent = self.db.execute("select p.first_word_id from clause c join clause p on p.id = c.parent_id where c.first_word_id = ?", (self.span("I will go")[0],)).fetchone()
        self.assertEqual(parent, (self.span("I said")[0],))
        with self.db:
            self.layer.unstore(self.db, SCOPE, tags)
        self.assertEqual(self.rows(), before)

    def test_runs_that_agree_settle_and_reset_restores_the_fixed_parts(self):
        before = self.rows()
        jobs.submit(self.db, self.job, answer())
        self.assertIsNotNone(self.job.settled())
        self.assertIn('"quote": "hath commanded"', show(self.db, "1-nephi", 3))
        jobs.replay(self.db, [self.layer])
        self.assertEqual(len(self.rows()[1]), 12)
        jobs.reset(self.db, self.job)
        self.assertEqual(self.rows(), before)

if __name__ == "__main__":
    unittest.main()
