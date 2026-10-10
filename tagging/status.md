# Tagging status

Every chapter of the Bible, Book of Mormon, Doctrine and Covenants, and Pearl of Great Price is tagged.

- Bible: open datasets imported (see CREDITS.md), then every chapter tagged by Opus with the `chapter-tagger` agent.
- Book of Mormon, Doctrine and Covenants, and Pearl of Great Price: every chapter tagged by Opus with the `chapter-tagger` agent.
- Every chapter of all four books reviewed once by Opus, which checked the current tags and corrected them.
- Duplicate entities are merged, including imported entities the taggers duplicated. Every entity has a mention, relationship, or speech.
- Other names hold only proper names and titles. Descriptions are mentions.

Tagging a chapter again replaces its mentions, speeches, journeys, dates, and relationship evidence. To retag, run the `chapter-tagger` agent on the chapter, then merge any duplicate entities it creates with `tagging/merge.py`.
