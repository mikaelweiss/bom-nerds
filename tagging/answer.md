# Answer format

Return the passage's complete tags, one per line, and nothing else: every tag that should exist, including the current ones that are right. A current tag you leave out is deleted.

## Spans

A span is a verse reference and the exact words in quotes: `14:5 "Ashteroth Karnaim"`. Quote the words as they appear, without punctuation. When the words appear more than once in the verse, add `#2`, `#3` after the quote for the later ones: `14:9 "king"#2`. Verse 0 is a chapter's heading.

A span across verses is two spans joined by `..`, running from the first word of the first to the last word of the second: `14:1 "And it came" .. 14:12 "departed"`.

## Entities

`#123` is an existing entity. A new entity is `+` and a short name you choose, such as `+melchizedek`, defined once by an `E` line.

## Lines

```
M <span> <entity>
A <span> <entity>
E <entity> | <type> | <name> | <description>
N <entity> | <other name> | title
N <entity> | <other name> | name
X <entity> | <other name>
R <entity> | <relationship kind> | <entity> | <span>; <span>
S <speaker> | <mode> | <listener>, <listener> | <span>
S <speaker> | <mode> | <listener> | <span> | through <entity>
J <traveler> | <from or -> | <to> | <days or -> | <span>
D <span or entity> | <counting system> | <from> | <to> | <evidence span or ->
```

- `M` is a Refers to mention. `A` is an About mention.
- `E` defines a new entity, or corrects an existing one's type, name, or description.
- `N` adds an other name. `X` removes a wrong one.
- `R` is a relationship and the spans that state it.
- `S` is a speech. Leave the listener list empty when no listener is named or meant.
- `J` is a journey. `D` is a date: `<from>` and `<to>` are a year, or year-month-day.
