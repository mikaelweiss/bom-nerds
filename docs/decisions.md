# Dataset spec

What this dataset holds, how it is built, and what each word in it means. Tagging starts once this spec is signed off.

## Goal

Every book of scripture, tagged and linked across all four works, so other projects can build visualizations and study helps on top of it. The dataset is built once, almost entirely by AI, and is too large for people to review. Every choice here aims to give the AI as few chances to make a mistake as possible.

This repository builds the dataset only. The API that serves it and the sites that visualize it are separate projects, so how fast the data is to serve plays no part in these choices.

Kept out on purpose:

- Numbers anyone can compute from the data, such as word counts.
- Who or what wrote each fact, how confident it was, and whether a person checked it.
- User accounts, practice data, and anything about serving the data.

## Glossary

Terms used throughout the spec. A term only one layer uses is defined in that layer's section.

### The text

| Word | Meaning |
|---|---|
| Work | One of the four: the Bible, the Book of Mormon, the Doctrine and Covenants, the Pearl of Great Price. |
| Edition | One printing of a work's text. The Bible also has a Hebrew edition (Old Testament) and a Greek edition (New Testament). |
| Book | Genesis, 1 Nephi, Moses. The Doctrine and Covenants is one book whose chapters are its sections. The Book of Mormon's title page and the witnesses' testimonies are books of their own. |
| Chapter | A numbered chapter, or a section of the Doctrine and Covenants. |
| Verse | A numbered verse. Text printed before verse 1 of a chapter, such as a book's title and heading, a chapter heading, or a Psalm title, is verse 0. |
| Word | One word, with the punctuation and spacing around it stored beside it. Each word has a permanent number that only the database uses. |

### Passages

| Word | Meaning |
|---|---|
| Passage | A run of consecutive words in one edition, like a highlighted stretch of text. |
| Quote | The exact words an agent copies from a verse to point at a passage. The CLI turns the quote into a passage, and only the passage is stored. |

### Tags

| Word | Meaning |
|---|---|
| Tag | One fact about one or more passages, like a note beside a highlight: "these words refer to Nephi." Mentions, speeches, relationships, dates, passage links, word matches, meanings, clauses, and literary structures are all tags, each defined in its layer's section. |
| Layer | One part of the dataset, built and stored on its own: the text, the entity list, or every tag of one kind. In the database, a layer is a table and a tag is a row in it. |
| Entity | A person, group, place, event, object, office, or topic that tags point to. One entity is the same everywhere it appears, in every work. |

### Doing the work

| Word | Meaning |
|---|---|
| Job | One agent answering one kind of question for one chapter. |

## How it is built

The dataset is one SQLite database. It is exported as a SQL dump and as JSON. People correct mistakes through a web interface that writes to the same database.

Agents never touch the database. They work through a CLI that:

- prints a chapter, along with every tag earlier layers placed on it
- searches the entity list
- checks an agent's answer and stores it

Scripts do everything they can. AI does the rest. Each fact has one answer, and a correction replaces it.

Jobs within one build step don't depend on each other, so they run massively in parallel.

### Keeping the AI from making mistakes

1. **The AI copies, never counts.** It points at words by verse and quote. The CLI finds the words and assigns word numbers. The AI never sees a word number.
2. **The AI chooses, never invents.** Entity search shows matching entries with their descriptions, with entities already found in that book first, and the AI picks one. Every kind comes from a short fixed list.
3. **One question per job.** Each job asks one thing, such as "who is speaking" or "who does each name refer to." The CLI enforces the shape of the answer.
4. **Every job runs twice.** Two agents answer the same job without seeing each other's work, and the CLI holds both answers. Where they agree, the answer is stored. Where they differ, a decider sees both and settles it. Only settled answers enter the database.
5. **The CLI rejects bad answers on the spot**, with a message the agent can act on, when:
   - a quote isn't in its verse, or appears there more than once (the agent quotes more words)
   - a passage runs backward
   - an entity isn't on the list
   - a kind isn't on its layer's list
   - a part sits outside the thing it belongs to, such as a clause outside its sentence
   - two speeches overlap without one sitting inside the other
   - the same fact appears twice
6. **Checks across each finished layer** flag answers that can't be true, such as someone who is their own ancestor, a place north of itself, or a speaker who isn't a person or group. A flagged chapter reruns.

### Pointing at text

Agents write verse references the way people do: `1 Nephi 3:7`, `D&C 76:22`. A passage takes one of these shapes:

```json
{ "verse": "1 Nephi 3:7", "quote": "Nephi" }
{ "verse": "1 Nephi 3:7" }
{ "from": "Alma 32:21", "to": "Alma 32:43" }
{ "from": "Mosiah 2:9", "to": "Mosiah 5:15", "starts": "My brethren", "ends": "Amen" }
{ "chapter": "Alma 32" }
```

In order: words inside one verse, a whole verse, whole verses, a passage that starts and ends partway through verses, and a whole chapter.

## Layers

Every layer points only at words and at the entity list. Any layer can be rebuilt or dropped without touching the others. Each example below is an answer as an agent writes it.

### Text

Works, editions, books, chapters, verses, and words. Each word keeps its exact text plus the punctuation and spacing before and after it, so every verse rebuilds exactly as printed. The KJV keeps its paragraph marks (¶), and words its translators supplied, printed in italics, are marked.

The Doctrine and Covenants covers sections 1 to 138. Both Official Declarations are left out. Official Declaration 2 (1978) is under copyright. Official Declaration 1 (1890) is public domain but missing from our source.

Built by script from bcbooks/scriptures-json for the Book of Mormon, Doctrine and Covenants, and Pearl of Great Price, and from eBible's KJV for the Bible. Both are already digital, so nothing needs OCR.

### Hebrew and Greek

The Hebrew Old Testament (Westminster Leningrad Codex) and Greek New Testament (SBL Greek New Testament) as their own editions. Each word has its headword, Strong's number, and grammar code (tense, person, number, and so on). Each Hebrew or Greek word is matched to the KJV words that translate it.

Built by script. The words come from Clear Bible's Macula. The matching uses the Strong's number eBible puts on each KJV word, and STEPBible's verse maps where Hebrew and English number verses differently.

Only the KJV's content words carry Strong's numbers, so small words like "the" and "of" stay unmatched. The KJV New Testament was also translated from a different Greek text, so some Greek and KJV words have no match.

### Dictionary

Each English word's headword (its dictionary form: "go" for "went") its part of speech, and the meaning it carries in its verse (one sense of a headword: "bear" the animal, or "bear" to carry). Hebrew and Greek words get meanings too. Their headwords come from the Hebrew and Greek layer.

Built by script for English headwords and parts of speech, and for Hebrew and Greek meanings wherever Macula's own word senses cover them. For the rest, AI writes the meanings of each headword, one job per headword. Then AI picks each word's meaning from that list, one job per chapter.

```json
{ "passage": { "verse": "1 Nephi 3:7", "quote": "said" }, "meaning": "say.1" }
```

### Entities

The list of every entity. Each has an ID, a type, a name, other names and titles, a one-line description, and the books it appears in.

An ID is the entity's name. When other entities anywhere in scripture share that name, the ID adds what sets this one apart: `nephi-son-of-lehi`, `nephi-son-of-helaman`.

```json
{ "id": "nephi-son-of-lehi", "type": "person", "name": "Nephi", "other_names": [], "description": "Son of Lehi. Wrote 1 and 2 Nephi." }
```

Types: person, group, place (city, land, water, mountain, wilderness), event, object (record), office, topic.

Built by script for Bible people and places, from STEPBible and OpenBible. For the other works, AI lists what each book contains, one job per book, and a merge job combines duplicates across books. Topics are our own, built by AI, not copied from the Topical Guide.

An agent in any other layer that finds an entity missing from the list reports it. The entity is added, and that chapter reruns.

### Mentions

Every passage that names or points to an entity, including titles and pronouns. Two kinds:

- `names`: the words name or point to the entity: "Nephi", "he", "the Holy One of Israel".
- `about`: the passage is about the entity without naming it. Topics attach this way.

```json
{ "entity": "nephi-son-of-lehi", "kind": "names", "passage": { "verse": "1 Nephi 3:7", "quote": "Nephi" } }
```

Built in two steps:

1. Names and titles. Script for Bible names: each KJV name carries a Strong's number, and STEPBible's name list says which person or place that name means in each verse. AI for the rest.
2. Pronouns, after Speakers. Script for "I", "me", "my", and "mine", which point to the speaker, and for "thou", "thee", and "thy" when a speech has one listener. AI for the rest, with the names around each pronoun already tagged.

### Speakers

A speech is a passage that one speaker says or writes to listeners, in one mode. Speeches nest: Mormon narrates, quoting Alma, who quotes Zenos. A speech sitting inside another speech's passage is quoted by it, so nesting needs no extra field.

Modes: narration, spoken, written, prayer, song.

Every speaker is an entity. An unnamed speaker gets an entity of its own, such as "the Bible narrator".

```json
{ "speaker": "king-benjamin", "listeners": ["people-of-king-benjamin"], "mode": "spoken",
  "passage": { "from": "Mosiah 2:9", "to": "Mosiah 5:15", "starts": "My brethren", "ends": "Amen" } }
```

Built by AI. Speeches run across chapters, so a book's chapters run in order, and each job sees which speeches are still open from the chapter before. Books run in parallel.

### Relationships

Facts connecting two entities. Each cites the passages that support it and can be dated (see Dates).

Kinds: child of, spouse of, sibling of, descendant of, member of, leader of, holds office, part of, took part in, took place at, located in, north of, east of, higher than, near, borders, journey to, named after, kept by, written by, abridged from.

Each kind has a reverse reading for display: "child of" reads back as "parent of", "north of" as "south of". Two-way kinds (spouse of, sibling of, near, borders) are stored once. "Journey to" records the days of travel when the text gives them.

```json
{ "subject": "nephi-son-of-lehi", "kind": "child_of", "object": "lehi-father-of-nephi",
  "evidence": [{ "verse": "1 Nephi 1:4", "quote": "my father, Lehi" }] }
```

Built by AI, one job per chapter. The same subject, kind, and object found in several chapters is one relationship with more evidence.

### Dates

A date is a year range in one counting system (a way the text counts years), with month and day when the text gives them. A date attaches to a passage (when it takes place), an event, or a relationship (when it was true), and cites the words that state it.

Counting systems: years since Lehi left Jerusalem, years of the reign of the judges, years since the sign of Christ's birth, and BC/AD.

The text's own count is a fact. The BC/AD year is our estimate. Both are stored, as separate rows on the same target. BC/AD years count 1 BC as 0 and 2 BC as -1, so ranges subtract cleanly.

```json
{ "on": { "chapter": "Alma 1" }, "system": "reign_of_judges", "from": 1, "to": 1,
  "evidence": { "verse": "Alma 1:1", "quote": "in the first year of the reign of the judges" } }
```

Built by AI.

### Passage links

Kinds: quotes, parallel, same event, alludes to, fulfills, cross-reference. A link runs from one passage to another. Two-way kinds (parallel, same event, cross-reference) are stored once.

```json
{ "kind": "quotes", "from": { "chapter": "2 Nephi 12" }, "to": { "chapter": "Isaiah 2" } }
```

Built by:

- Script: text comparison finds Book of Mormon and Doctrine and Covenants passages that closely follow the Bible, such as Isaiah in 2 Nephi and the Sermon on the Mount in 3 Nephi. These also get word matches, so every small difference shows.
- Script: OpenBible's Bible cross-references.
- AI: allusions, fulfillments, and cross-references between works, one job per chapter.

### Word matches

Two words that correspond: across editions, between Hebrew or Greek and the KJV, and inside parallel passages. Whether the pair is the same word, a changed word, or a translation shows from the words themselves. A word with no match has no counterpart there.

Built by script.

### Grammar

Sentences, their clauses, and each clause's parts. A clause is a group of words built around one verb, and clauses can hold clauses. Parts: subject, verb, object, indirect object, complement, adverbial.

```json
{ "sentence": { "verse": "1 Nephi 3:7" },
  "clauses": [
    { "passage": { "verse": "1 Nephi 3:7", "quote": "I, Nephi, said unto my father" }, "parts": [
      { "role": "subject", "passage": { "verse": "1 Nephi 3:7", "quote": "I, Nephi" } },
      { "role": "verb", "passage": { "verse": "1 Nephi 3:7", "quote": "said" } },
      { "role": "indirect_object", "passage": { "verse": "1 Nephi 3:7", "quote": "unto my father" } }
    ] }
  ] }
```

Built by script for Hebrew and Greek, from Macula. AI for English.

### Literary structures

Chiasmus, parallelism, lists, and acrostics. Each structure has ordered parts. Parts can hold parts, and a chiasm part names its partner (A' pairs with A).

```json
{ "kind": "chiasm", "passage": { "from": "Alma 36:1", "to": "Alma 36:30" }, "parts": [
  { "label": "A", "passage": { "verse": "Alma 36:1" } },
  { "label": "A'", "passage": { "verse": "Alma 36:30" }, "pairs_with": "A" }
] }
```

Built by AI.

## Editions

Every edition is equal. A tag lives on the words it was made on, and word matches carry it to every other edition. A script matches a new edition's words to the editions already there, and the new edition is tagged only where its text has no match, such as Joseph Smith Translation additions.

Editions come from digital text only. We do no OCR.

## Build order

Each step gives the next ones context and constraints, so later questions become choices among things already tagged. Mistakes spread the same way, so the early steps get the most care.

1. Text.
2. Hebrew and Greek, word matches, and English headwords. All scripts.
3. The entity list.
4. Mentions of names and titles.
5. Speakers.
6. Mentions of pronouns.
7. Relationships, dates, passage links, meanings, grammar, and literary structures, in parallel.

Before the full run, every layer runs on one pilot chapter, and its output is reviewed.

## Licensing

- The dataset is CC BY 4.0. The code is Apache 2.0. CC BY is the freest license we can offer, because some sources require credit.
- Every source must be public domain, CC0, or CC BY. We avoid share-alike, GPL, noncommercial, and unlicensed data, because each would restrict the CC BY promise.
- One credits file lists every source and the attribution it requires.
- We never scrape churchofjesuschrist.org. Its terms of use forbid it, even for public-domain text.
- We never copy the Church's study helps: footnotes, chapter summaries, section headings, the Topical Guide, the Bible Dictionary, the Guide to the Scriptures, the index, or the maps. Individual facts are free to use, but a copyrighted compilation's selection is not.

### Sources

| Need | Source | License |
|---|---|---|
| Book of Mormon, Doctrine and Covenants, Pearl of Great Price text | bcbooks/scriptures-json | Public domain |
| KJV text with Strong's numbers | eBible eng-kjv2006 | Public domain outside the UK, where the Crown holds printing rights |
| Hebrew and Greek words, headwords, grammar, word senses | Clear Bible Macula, without the United Bible Societies columns (`domain`, `ln`, `sdbh`, `lexdomain`, `coredomain`, `contextualdomain`), which are used with permission rather than CC BY | CC BY 4.0 |
| Bible names per verse, verse-numbering maps | STEPBible TIPNR and TVTMS | CC BY 4.0 |
| Bible cross-references and places | OpenBible.info | CC BY 4.0 |

Sources we skip:

- BYU's OpenScripture edition comparison has no license. We compute edition differences ourselves.
- CrossWire's KJV has a contradictory license.
- Theographic is share-alike.
- The Joseph Smith Papers transcripts are all rights reserved.
- Skousen's critical text is copyrighted.
- Modern Bible translations (NIV, ESV, NRSV, NASB, NLT, NET) are restricted.
- We send no permission requests.
