# BOM Nerds

One open database of the standard works: the Bible, Book of Mormon, Doctrine and Covenants, and Pearl of Great Price. Every word is connected to the people, places, and ideas it talks about.

## What's inside

The text and original-language data are complete. The rest is being tagged chapter by chapter.

- **Text:** every verse, word by word, with the Hebrew and Greek originals linked to the English.
- **Original words:** headwords, Strong's numbers, meanings, and full grammar for each word.
- **People, places, and things:** every person, group, city, land, event, and topic, tagged everywhere the text names or refers to them, pronouns included.
- **Relationships:** family trees, who led whom, what lies north of what, each backed by the verse that says it.
- **Speeches:** who is speaking, to whom, and through which prophet.
- **Journeys:** who traveled where, and how long it took.
- **Dates:** BC/AD and the Book of Mormon's own calendars.
- **Links:** cross-references, quotes, parallels, and fulfilled prophecies.
- **Structure:** sentences, clauses, chiasms, and parallelisms.
- **Study notes:** summaries of each chapter's key verses, doctrine, symbols, setting, and more.

## What you can do with it

- **Study:** read every verse about Moroni, every word Alma spoke, or every place the Book of Mormon quotes Isaiah.
- **Visualize:** draw family trees, map journeys, plot a timeline, or graph who talks to whom.
- **Search the originals:** find every use of a Hebrew or Greek word, whatever the English says.
- **Build:** power a study app, a game, a chatbot, or a research project.

## Get it

Download the latest [release](https://github.com/mikaelweiss/bom-nerds/releases/latest):

- `scripture-db.zip` is a SQLite database.
- `scripture-json.zip` is every table as JSON.

```sh
sqlite3 scripture.db "select name, description from entity where name = 'Nephi'"
```

## License

The data is [CC BY 4.0](LICENSE-DATA.txt) and the code is [Apache 2.0](LICENSE.md). Keep the [credits](CREDITS.md) when you share the data.
