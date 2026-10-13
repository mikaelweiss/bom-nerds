# Standard Works Corpus API, v1

Read-only SQL over the [Standard Works Corpus](https://github.com/mikaelweiss/standard-works-corpus): the Bible, Book of Mormon, Doctrine and Covenants, and Pearl of Great Price, word by word, with the people, places, speeches, journeys, dates, and links in them. The data improves with each release, and this API always serves the latest one.

## Querying

```
GET {{origin}}/v1/sql?q=<SQLite query>
```

```js
const sql = "select name, latitude, longitude from entity where latitude is not null";
const response = await fetch("{{origin}}/v1/sql?q=" + encodeURIComponent(sql));
const { rows } = await response.json();
```

Any page on any site can call it. A response looks like this:

```json
{
  "release": "data-2026-10-11-143950",
  "columns": ["name", "latitude", "longitude"],
  "rows": [{ "name": "Jerusalem", "latitude": 31.776679, "longitude": 35.234156 }],
  "truncated": false
}
```

- The query is SQLite and may only read. One statement, `select`, `with`, or `values`.
- Each row is an object keyed by column name, so give duplicate columns distinct names with `as`.
- At most 10,000 rows come back. `truncated` is true when there were more. Page with `limit` and `offset`.
- A query may run for 5 seconds.
- Each client may run 60 queries a minute. Repeating a query someone already ran is free, because responses are cached until the next release.
- Errors come back as `{"error": "..."}`: 400 for a bad query, 429 when over the limit, 503 when the server is busy.

v1 never removes or renames a table or column listed here. New tables and columns may appear. Ids are not promised to stay the same between releases, so find rows by name or reference rather than by a hard-coded id.

## How the data fits together

### Text

- `work`: Bible, Book of Mormon, Doctrine and Covenants, Pearl of Great Price.
- `edition`: one text of a work. The Bible has three: King James Version (1769) in English, Westminster Leningrad Codex in Hebrew and Aramaic, and SBL Greek New Testament. The others have one each, named "Book of Mormon (2013)", "Doctrine and Covenants (2013)", and "Pearl of Great Price (2013)".
- `language`: English, Biblical Hebrew, Biblical Aramaic, Koine Greek.
- `book`: a book of a work, such as "1 Nephi" or "Psalms". The Doctrine and Covenants is one book whose chapters are its sections. `edition_book.position` orders an edition's books.
- `chapter`: `edition_id`, `book_id`, `number`.
- `verse`: `chapter_id`, `number`. A null `number` is the chapter heading, such as a psalm's title.
- `word`: every word of every edition.
  - `verse_id` and `position` (1-based within the verse).
  - `sequence`: the reading order across the whole corpus. Use it to walk from one word to another.
  - `text`, with `before` and `after` holding the spaces and punctuation around it. `before || text || after`, joined in order, rebuilds the text exactly.
  - `supplied` is 1 for words the translators added (the KJV's italics).
  - `part_of_speech_id`, `headword_id` (the dictionary form), `meaning_id` (the sense used here).

### Word ranges

Most tables point at a span of text with `first_word_id` and `last_word_id` (some prefix them, like `from_first_word_id`). The span is every word whose `sequence` lies between the two words' sequences. Never compare word ids to each other: only `sequence` is in reading order.

```sql
select group_concat(w.before || w.text || w.after, '' order by w.sequence) as text
from word w
where w.sequence between (select sequence from word where id = :first_word_id)
                     and (select sequence from word where id = :last_word_id)
```

A span's reference comes from its first and last words: `word.verse_id` to `verse`, then `chapter`, then `book`.

### Original languages

- `headword`: a dictionary entry with `language_id`, `text`, `strongs` (such as "H7225" or "G3056"), and `gloss`. English words have headwords too.
- `meaning`: a numbered sense of a headword, with `gloss` and `definition`.
- `word_match`: aligns words. `word_id` is a KJV word and `other_word_id` is the Hebrew, Aramaic, or Greek word it translates, or the matching word where the Book of Mormon, Doctrine and Covenants, or Pearl of Great Price quote the Bible.
- `hebrew_word` and `greek_word`: grammar for each original word, keyed by `word_id`. Each grammatical feature points at a small lookup table: `word_type`, `stem`, `verb_form`, `tense`, `voice`, `mood`, `person` (a number), `gender`, `grammatical_number`, `grammatical_case`, `state`, `degree`.

### People, places, and things

- `entity`: a person, group, place, event, object, office, or topic. `name`, `description`, and for places `latitude` and `longitude`. `tipnr` is the entity's id in STEPBible's TIPNR proper-name data, for joining outside data. Many share a name (there are four people named Lehi), so tell them apart by `description`.
- `entity_type`: Person, Group, Place (with children City, Land, Water, Mountain, Wilderness), Event, Object (with child Record), Office, Topic. `parent_id` gives the parent.
- `entity_name`: other names and titles an entity goes by. `is_title` marks titles like "son of Mormon".
- `mention`: where the text points at an entity, as a word range. Kind "Refers to" is a word or phrase naming the entity, pronouns included. Kind "About" is a passage about the entity.
- `relationship`: `subject_id`, `relationship_kind_id`, `object_id`, read as "subject kind object" ("Nephi child of Lehi"). `relationship_kind` has `name`, `reverse_name` ("parent of"), and `two_way` (1 when it reads the same both ways, like "sibling of", stored once). Kinds cover family, membership, leadership, office, part of, took part in, took place at, location, direction, naming, record keeping, and authorship.
- `relationship_evidence`: the word ranges that state a relationship.

### Speech

- `speech`: a word range that someone speaks, writes, prays, or sings, or plain narration. `speech_mode` names which. `through_id` is the prophet the words come through, when the speaker is the Lord.
- `speech_speaker` and `speech_listener`: who speaks and who is addressed.

### Places and travel

- `setting`: the place (`place_id`) where a word range takes place, even when the text does not name it.
- `journey`: `traveler_id` went from `from_id` (null when unknown) to `to_id`, taking `days` when the text says, told in a word range.

### Time

- `date`: a date for a word range, an entity (most often an event), or a relationship. `from_year`, `from_month`, `from_day` to `to_year`, `to_month`, `to_day`.
- `counting_system`: what the year counts. "BC/AD" years are negative for BC. The Book of Mormon's own calendars count years since Lehi left Jerusalem, of the reign of the judges, and since the sign of Christ's birth. When `needs_evidence` is 1, the date carries `evidence_first_word_id` and `evidence_last_word_id`.

### Links between passages

- `passage_link`: links a `from_` word range to a `to_` word range. `link_kind` is Quotes, Parallel, Same event, Alludes to, Fulfills, or Cross-reference. A `two_way` kind is stored once and holds both ways.

### Structure

- `sentence`, then `clause` (nested through `parent_id`), then `clause_part` with a `clause_role`: Subject, Verb, Object, Indirect object, Complement, Adverbial.
- `structure`: a Chiasm, Parallelism, List, or Acrostic over a word range. `structure_part` holds its parts in `position` order, nested through `parent_id`. `structure_part_pair` pairs the parts that mirror each other.
- `verse_range`: a named passage, such as "Visit of the Magi".

### Study notes

- `summary`: notes on a chapter, book, or `verse_range`, with `text`. `summary_kind` names the kind (Doctrine, Key verses, Symbols, Setting, and more) and `summary_kind_work` lists which kinds each work has.

The full table definitions:

```sql
select sql from sqlite_master where type = 'table'
```

## Examples

A verse:

```sql
select group_concat(w.before || w.text || w.after, '' order by w.position) as text
from word w
join verse v on v.id = w.verse_id
join chapter c on c.id = v.chapter_id
join book b on b.id = c.book_id
join edition e on e.id = c.edition_id
where e.name = 'Book of Mormon (2013)' and b.name = '1 Nephi' and c.number = 3 and v.number = 7
```

A chapter, verse by verse:

```sql
select v.number as verse, group_concat(w.before || w.text || w.after, '' order by w.position) as text
from verse v
join word w on w.verse_id = v.id
join chapter c on c.id = v.chapter_id
join book b on b.id = c.book_id
join edition e on e.id = c.edition_id
where e.name = 'King James Version (1769)' and b.name = 'Psalms' and c.number = 23
group by v.id
order by v.number
```

Which Lehi is which:

```sql
select e.id, e.name, e.description
from entity e
join entity_type t on t.id = e.entity_type_id
where t.name = 'Person' and e.name = 'Lehi'
```

How often each book names Moroni, son of Mormon:

```sql
select b.name as book, count(*) as mentions
from mention m
join mention_kind k on k.id = m.mention_kind_id
join word w on w.id = m.first_word_id
join verse v on v.id = w.verse_id
join chapter c on c.id = v.chapter_id
join book b on b.id = c.book_id
where k.name = 'Refers to'
  and m.entity_id = (select id from entity where name = 'Moroni' and description like 'Son of Mormon%')
group by b.id
order by min(w.sequence)
```

Lehi's descendants for three generations:

```sql
with recursive family(id, parent_id, generation) as (
  select id, null, 0 from entity where name = 'Lehi' and description like '%father of Nephi%'
  union all
  select r.subject_id, r.object_id, f.generation + 1
  from relationship r
  join relationship_kind k on k.id = r.relationship_kind_id and k.name = 'child of'
  join family f on f.id = r.object_id
  where f.generation < 3
)
select f.generation, e.name, p.name as parent
from family f
join entity e on e.id = f.id
left join entity p on p.id = f.parent_id
```

Paul's travels, for a map:

```sql
select f.name as from_place, f.latitude as from_lat, f.longitude as from_lon,
       t.name as to_place, t.latitude as to_lat, t.longitude as to_lon, j.days
from journey j
join entity p on p.id = j.traveler_id
join entity_type pt on pt.id = p.entity_type_id
left join entity f on f.id = j.from_id
join entity t on t.id = j.to_id
join word w on w.id = j.first_word_id
where p.name = 'Paul' and pt.name = 'Person'
order by w.sequence
```

Who speaks to whom in the Book of Mormon:

```sql
select sp.name as speaker, li.name as listener, count(*) as speeches
from speech s
join speech_speaker ss on ss.speech_id = s.id
join entity sp on sp.id = ss.entity_id
join speech_listener sl on sl.speech_id = s.id
join entity li on li.id = sl.entity_id
join word w on w.id = s.first_word_id
join verse v on v.id = w.verse_id
join chapter c on c.id = v.chapter_id
join edition e on e.id = c.edition_id
where e.name = 'Book of Mormon (2013)'
group by sp.id, li.id
order by speeches desc
```

A timeline of events:

```sql
select e.name, d.from_year, d.to_year
from date d
join entity e on e.id = d.entity_id
join entity_type t on t.id = e.entity_type_id
join counting_system cs on cs.id = d.counting_system_id
where t.name = 'Event' and cs.name = 'BC/AD'
order by d.from_year
```

Where the Book of Mormon quotes Isaiah:

```sql
select fb.name || ' ' || fc.number || ':' || fv.number as quoting,
       tb.name || ' ' || tc.number || ':' || tv.number as quoted
from passage_link l
join link_kind k on k.id = l.link_kind_id
join word fw on fw.id = l.from_first_word_id
join verse fv on fv.id = fw.verse_id
join chapter fc on fc.id = fv.chapter_id
join book fb on fb.id = fc.book_id
join edition fe on fe.id = fc.edition_id
join word tw on tw.id = l.to_first_word_id
join verse tv on tv.id = tw.verse_id
join chapter tc on tc.id = tv.chapter_id
join book tb on tb.id = tc.book_id
where k.name = 'Quotes' and fe.name = 'Book of Mormon (2013)' and tb.name = 'Isaiah'
order by fw.sequence
```

How the KJV translates the Hebrew word for "beginning" (Strong's H7225):

```sql
select kjv.text as english, count(*) as uses
from headword h
join word heb on heb.headword_id = h.id
join word_match m on m.other_word_id = heb.id
join word kjv on kjv.id = m.word_id
where h.strongs = 'H7225'
group by kjv.text
order by uses desc
```

## License

The data is [CC BY 4.0](https://github.com/mikaelweiss/standard-works-corpus/blob/main/LICENSE-DATA.txt). Credit the Standard Works Corpus and keep its [credits](https://github.com/mikaelweiss/standard-works-corpus/blob/main/CREDITS.md) when you share it.
