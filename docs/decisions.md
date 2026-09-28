# Dataset decisions

The schema lives in [`db/schema.sql`](../db/schema.sql) and its types in [`db/seed.sql`](../db/seed.sql). This file records why they look the way they do.

## Purpose

This database is the **gather** step: a large, carefully tagged set of facts about the scriptures. It stores facts about the text and where each fact came from. It stores nothing about how the facts will be used.

Kept out on purpose:

- Derived numbers such as clue strength, word counts, name ambiguity, and difficulty.
- User accounts, editor roles, trust rules, and edit history.
- Practice data (guesses, progress). That lives in a separate database.
- Download packaging.

The data is tagged once and rarely changed afterward, except to fix errors. Doing more work up front is preferred over storing less.

## Scope

- Works: the Bible, the Book of Mormon, the Doctrine and Covenants, and the Pearl of Great Price.
- The Joseph Smith Translation, as the 1867 Inspired Version, is an edition of the Bible.
- The Apocrypha is out of scope.
- The Bible gets a Hebrew and Greek layer, aligned to the English words.
- Multiple editions of each work, including future revisions.

## Licensing

- The dataset is CC BY 4.0. The code is Apache 2.0. CC BY is the freest license we can offer, because some of our sources require credit.
- Every source must be public domain, CC0, or CC BY. We avoid share-alike, GPL, noncommercial, and unlicensed data, because each one would restrict or undermine the CC BY promise.
- We never scrape churchofjesuschrist.org. Its terms of use forbid it, even for public-domain text.
- We never copy the Church's study helps: footnotes, chapter summaries, section headings, the Topical Guide, the Bible Dictionary, the Guide to the Scriptures, the index, or the maps. Individual facts are free to use, but a copyrighted compilation's selection is not. We build our own topics and cross-references.
- Datasets we skip, and what we do instead:
  - BYU's OpenScripture edition comparison has no license. We compute edition differences ourselves.
  - CrossWire's KJV has a contradictory license. We use eBible's public-domain KJV instead.
  - Theographic is share-alike.
  - The Joseph Smith Papers transcripts are all rights reserved.
  - Skousen's critical text is copyrighted.
  - Modern Bible translations (NIV, ESV, NRSV, NASB, NLT, NET) are restricted.
  - We send no permission requests.

### Sources

| Need | Source | License |
|---|---|---|
| Current LDS text | bcbooks/scriptures-json | Public domain |
| KJV with Strong's numbers | eBible eng-kjv2006 | Public domain |
| Hebrew and Greek words, lemmas, morphology, syntax | Clear Bible Macula, without its `domain` and `ln` columns | CC BY 4.0 |
| Bible proper names per verse, versification maps | STEPBible TIPNR and TVTMS | CC BY 4.0 |
| Bible cross-references and places | OpenBible.info | CC BY 4.0 |
| 1830, 1840, 1879, 1920 Book of Mormon | archive.org scans and text | Public domain |
| 1837 Book of Mormon | archive.org page images, which we OCR | Public domain |
| 1867 Inspired Version | archive.org scan, which we OCR and clean | Public domain |

## Storage

- Postgres holds the data. A dump is stored in git.
- The database enforces integrity on write: foreign keys, checks, and span triggers. AI runs write millions of rows, so bad rows must be rejected at insert time.

## Identity

- Data rows use auto-numbered integer keys. Readable IDs break when data shifts, and UUIDs solve a distributed-ID problem this project does not have.
- Readable values such as book, chapter, verse, names, and slugs are ordinary columns.
- Type tables use readable text keys (`child_of`, `verse`). They hold hand-defined labels, not gathered data, so they stay stable and make queries readable.

## Text and editions

- A **work** is the abstract book. An **edition** is one printing of it. A future revision is a new edition row.
- Each edition owns its words and its own divisions. The 1830 Book of Mormon has no verses and different chapters, and Bible numbering differs between traditions.
- Each work has one reference edition: 2013 LDS for Restoration scripture and the KJV for the Bible. Study data attaches to reference-edition words.
- `word_alignment` links words across editions. It covers edition variants, Hebrew and Greek translation, and parallel passages. An edition's text never depends on another edition.
- Text that exists only in a non-reference edition, such as JST additions, is tagged on that edition's own words.
- The smallest unit is the word. Speakers, quotations, and names often begin mid-verse, and word study needs word-level data.
- A span is a first and last word within one edition. Every tag that covers text uses spans.
- Words keep their punctuation, italics (words the KJV translators supplied), small caps, paragraph marks, and page breaks. Every edition rebuilds exactly as printed.
- A text unit is a segment with a kind, because not all scripture text is a verse. The kinds are verse, title, subtitle, heading, superscription, subscription, acrostic label, testimony, preface, note, figure explanation, and paragraph.

## Facts

- Every fact records its `source` (a dataset, an AI run, or a contributor). That source drives the credits page and lets us undo a single bad AI run.
- AI facts carry a confidence score from 0 to 1, so review starts with the least certain.
- Every fact has a `review_status`: unreviewed, verified, or flagged. Unreviewed AI facts are allowed.
- Each fact has one answer. The project owner's view is the answer. Disagreements come in as reports and are not stored as competing claims.
- Segments carry a review status too, because OCR text needs checking.

## Entities

- One entity per real person, place, or thing across all volumes. Isaiah and Moses are each one entity everywhere they appear.
- Entity types form a tree, and adding a type is one row. A record (the brass plates, the small plates) is a kind of object.
- Entities have alternate names and titles ("the Holy One of Israel").
- Mentions link words to entities. A mention either **refers** to the entity, naming it or pointing to it with a name, pronoun, or title, or is **about** it, concerning it without naming it, as with topics.
- Pronouns and titles are tagged.
- Topics are our own entities, built with AI and review, not copied from the Topical Guide.
- Relations between entities cite the words that support them. They can be dated, because offices and control of places change over time.

## Speech and grammar

- Speech nests: Mormon narrates, quoting Alma, who quotes Zenos. Each speech has one speaker and any number of addressees.
- Speaker and addressee live only on the speech, so they are never stored twice.
- Sentences and clauses are stored. Clause parts record who did what to whom (subject, verb, object, and the rest).
- Each word has a lemma (its dictionary form) and a sense (which meaning it carries).

## Literary structure

Chiasmus, parallelism, lists, and acrostics are stored as structures with ordered parts. Parts can nest and can pair with each other (A with A').

## Links between passages

- The link types are quotes, parallel, same event, alludes, fulfills, and cross-reference.
- Book of Mormon passages that closely follow the Bible get a passage link plus word alignment, so every small change is visible. These are found by computer comparison, not listed by hand.

## Time

- A date stores every count of time the text gives: years since Lehi left Jerusalem, the reign of the judges, years since the sign of Christ's birth, and a converted BC/AD range. The count is fact, and the conversion is interpretation, so both are kept instead of computed later.
- Counting systems are rows, so Bible regnal years and D&C calendar dates need no schema change.
- Dates are ranges and can attach to an entity, a relation, or a passage.

## Geography

Book of Mormon geography comes only from the text: relations such as north of, higher than, near, borders, and journey to. No real-world map is stored.

## Extension

- Core tables stay fixed. New kinds of data arrive as new type rows (entity types, relation types, link types, calendars).
- A dataset that needs its own fields, such as conference talks, gets its own tables that point into the core. The core never points out to them.
- Conference talk text is Church copyrighted, so only citations and links to talks would be stored.

## Known gaps to build

- **1837 Book of Mormon:** needs OCR. The 1879 text needs heavy cleanup.
- **1867 Inspired Version:** needs OCR cleanup and a computed comparison against the KJV.
- **KJV to Hebrew alignment:** join the KJV Strong's tags to Macula words.
- **KJV to Greek alignment:** the KJV's Greek tags point at a different Greek text (the Textus Receptus), so they need mapping onto SBLGNT.
- **Restoration scripture study data:** no open data exists for Book of Mormon, D&C, or Pearl of Great Price people, places, speakers, dates, or topics. AI tagging plus review builds it.
