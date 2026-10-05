# Tagging

Rules for adding entities and mentions to `scripture.db`. Read the schema with `sqlite3 scripture.db .schema` before writing.

## Working

- Write data only. Never change the schema.
- Tag one chapter per transaction. Run `pragma foreign_key_check` before committing.
- Tag a chapter's verse with no number too.
- Read the chapters before and after when a reference depends on them.

## Entities

- Reuse an entity before creating one. Search `entity.name` and `entity_name.name`, then read the description and existing mentions to confirm it is the same one.
- Create an entity for anything a reader would look up across scripture: a specific person, group, place, event, object, record, office, or topic. Common nouns used generically, such as a rock, a bed, or the earth, are not entities.
- Use the narrowest type: City, not Place.
- The description is one sentence that tells the entity apart from others with the same name: "Son of Lehi and Sariah", not "A prophet".
- In `entity_name`, `is_title` is 1 for a designation such as "the Lord" or "Holy One of Israel", and 0 for a proper name such as "Elohim".

## Mentions

Tag every word or phrase that refers to an entity: names, titles, pronouns, and descriptions such as "my father" or "goodly parents".

- **Refers to:** the words point to the entity. Cover the shortest phrase that does: "father" in "my father", "Spirit of the Lord" as one phrase. Leave out a leading "the" or "a".
- **About:** the passage is about the entity without naming it. Cover the whole passage. Topics attach this way: a passage on prayer is About Prayer even if the word never appears.
- A word inside a longer mention gets its own mention too. In "my father", "my" refers to the speaker.
- A word that refers to several entities gets one mention for each. "Four sons" refers to Laman, Lemuel, Sam, and Nephi.
- "I", "me", "my", and "mine" refer to whoever is speaking, including a speaker quoted inside the text.
- Leave out words that refer to no specific entity: the "it" in "it came to pass", and people in general ("those who come unto thee").
- Bible names are already tagged. Add every other mention, and fix any that are wrong.

## Names of God

- "The Lord", "Lord God", and "God" refer to Jesus Christ or God the Father. Decide each one from its passage.
- "The Lord" and Jehovah refer to Jesus Christ unless the passage points to the Father: the Father of Jesus Christ, the one who sends the Messiah, or one being addressed beside the Son.
- "God" alone refers to the Father unless the passage points to Christ, such as "the God of Israel" in 3 Nephi 11:14.
- Where one passage names both, tag each name to its own entity, as in Psalm 110:1.
