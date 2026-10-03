import unittest

from bomnerds import usfm
from bomnerds.words import rebuild, split

BOOK = r"""\id PSA Psalms
\h Psalms
\mt1 The Book of Psalms
\c 1
\d A \w Psalm|strong="H4210"\w* of \w David|strong="H1732"\w*.
\q1
\v 1 ¶ In the \w beginning|strong="H7225"\w* \add was\add* the \nd \+w LORD|strong="H3068"\+w*\nd*.\f + \fr 1.1 \ft a note\f*
\q1
\v 2 Thither, (\add is\add* it not?) to \w God|strong="G2316"\w*-\w ward|strong="G4314"\w*
\q1
continued here.
\s1 \tl א ALEPH.\tl*
\v 3 Last.
\s1 Written from Rome.
"""


class SplitTest(unittest.TestCase):
    def test_punctuation_goes_to_the_word_it_belongs_to(self):
        words = split("¶ Lehi's sons, (Laman and Sam) went--fast.")
        self.assertEqual(
            [(w.before, w.text, w.after) for w in words],
            [("¶ ", "Lehi's", " "), ("", "sons", ", "), ("(", "Laman", " "), ("", "and", " "), ("", "Sam", ") "), ("", "went", "--"), ("", "fast", ".")],
        )

    def test_rebuilds_exactly(self):
        text = "The Book of Mormon\nAn Account--Written; by Moroni, Jun.: Amen."
        self.assertEqual(rebuild(split(text)), text)


class UsfmTest(unittest.TestCase):
    def setUp(self):
        self.book = usfm.parse(BOOK)

    def text(self, chapter, verse):
        return rebuild(self.book.verses[(chapter, verse)])

    def test_titles_before_verse_one_are_verse_zero(self):
        self.assertEqual(self.text(1, 0), "The Book of Psalms\nA Psalm of David.")

    def test_markers_and_footnotes_leave_only_the_text(self):
        self.assertEqual(self.text(1, 1), "¶ In the beginning was the LORD.")
        self.assertEqual(self.text(1, 2), "Thither, (is it not?) to God-ward continued here.")

    def test_supplied_words_are_marked(self):
        self.assertEqual([w.text for w in self.book.verses[(1, 1)] if w.supplied], ["was"])

    def test_a_word_split_by_markers_keeps_every_strongs_number(self):
        self.assertEqual(self.book.verses[(1, 2)][-3].strongs, ("G2316", "G4314"))

    def test_a_heading_before_a_later_verse_opens_it(self):
        self.assertEqual(self.text(1, 3), "א ALEPH.\nLast.\nWritten from Rome.")


if __name__ == "__main__":
    unittest.main()
