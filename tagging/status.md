# Tagging status

Every chapter of the Bible, Book of Mormon, Doctrine and Covenants, and Pearl of Great Price is tagged.

- Bible: open datasets imported (see CREDITS.md), then every chapter tagged by Opus with the `chapter-tagger` agent.
- Book of Mormon, Doctrine and Covenants, and Pearl of Great Price: every chapter tagged by Opus with the `chapter-tagger` agent.
- Duplicate entities created by parallel taggers are merged.
- Other names hold only proper names and titles. Descriptions are mentions.

Tagging a chapter again replaces its mentions, speeches, journeys, dates, and relationship evidence. To retag, run the `chapter-tagger` agent on the chapter, then merge any duplicate entities it creates.
