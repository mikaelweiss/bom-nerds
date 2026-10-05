# Tagging

Rules for adding and fixing data in `scripture.db`. Read the schema with `sqlite3 scripture.db .schema` before writing.

## Working

- Write data only. Never change the schema.
- Tag one chapter per transaction. Run `pragma foreign_key_check` before committing.
- Tag a chapter's verse with no number too.
- Read the chapters before and after when a reference depends on them.
- Fix any existing row that breaks these rules.

## Entities

- Reuse an entity before creating one. Search `entity.name` and `entity_name.name`, then read the description and existing mentions to confirm it is the same one.
- An entity is one real thing. A tribe and its founder, or a city and its land, are separate entities.
- Create an entity for anything a reader would look up across scripture: a specific person, group, place, event, object, record, office, or topic. Common nouns used generically are not entities.
- Use the narrowest type that fits.
- The description is one sentence that tells the entity apart from others with the same name.
- Every form the text uses to name an entity, including other spellings, is an other name in `entity_name`. `is_title` is 1 for a designation such as "the Lord", and 0 for a proper name.

## Mentions

Tag every word or phrase that refers to an entity: names, titles, pronouns, and descriptions such as "my father".

- **Refers to:** the words point to the entity. Each noun phrase that refers is its own mention: a name and the title beside it, as in "Bera king of Sodom", are two. Leave out a leading "the" or "a".
- **About:** the passage is about the entity without naming it. Cover the whole passage. Topics attach this way.
- Decide each mention from its passage: which person of that name, and whether the words mean a person, their people, or their land.
- A word inside a longer mention gets its own mention when it refers to a different entity.
- Words that refer to several entities get one mention for each.
- "I", "me", "my", and "mine" refer to whoever is speaking.
- Leave out words that refer to no specific entity.

## Relationships

- A relationship needs evidence: a passage where the text states it, not one where it is only implied.
- Evidence may cite more than one passage when the text states the relationship in parts.
- Store each fact once. Do not add a relationship that others already imply, such as siblings who share a recorded parent.

## Speeches

- A speech is the words one speaker says, writes, prays, or sings to listeners. Cover exactly those words.
- Every speaker and listener is an entity. An unnamed speaker gets an entity of its own.
- When someone delivers another's words, as a prophet delivers the Lord's, the original speaker is the speaker and the messenger is `through_id`.
- Speeches nest: a quoted speech sits inside the speech that quotes it.
- Narration is the narrator's speech over a whole book. Do not tag it passage by passage.

## Journeys

- A journey is one traveler going from one place to another, citing the words that tell it.
- Leave the starting place empty when the text does not give it. Give days only when the text does.

## Dates

- A date is a year range in one counting system, with month and day when the text gives them. It attaches to one passage, entity, or relationship.
- A date in the text's own count cites its words. A BC/AD year the text does not state is an estimate and cites no words.
- BC/AD years count 1 BC as 0.

## Names of God

- "The Lord", "Lord God", and "God" refer to Jesus Christ or God the Father. Decide each one from its passage.
- "The Lord" and Jehovah refer to Jesus Christ unless the passage points to the Father. "God" alone refers to the Father unless the passage points to Christ.
- Where one passage names both, tag each name to its own entity.
