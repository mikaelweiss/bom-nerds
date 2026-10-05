insert into language (id, name, iso_code) values
    (1, 'English', 'en'),
    (2, 'Biblical Hebrew', 'hbo'),
    (3, 'Biblical Aramaic', 'arc'),
    (4, 'Koine Greek', 'grc');

insert into work (id, name) values
    (1, 'Bible'),
    (2, 'Book of Mormon'),
    (3, 'Doctrine and Covenants'),
    (4, 'Pearl of Great Price');

insert into edition (id, work_id, language_id, name) values
    (1, 1, 1, 'King James Version (1769)'),
    (2, 1, 2, 'Westminster Leningrad Codex'),
    (3, 1, 4, 'SBL Greek New Testament'),
    (4, 2, 1, 'Book of Mormon (2013)'),
    (5, 3, 1, 'Doctrine and Covenants (2013)'),
    (6, 4, 1, 'Pearl of Great Price (2013)');

insert into part_of_speech (id, name) values
    (1, 'Noun'),
    (2, 'Proper noun'),
    (3, 'Pronoun'),
    (4, 'Verb'),
    (5, 'Adjective'),
    (6, 'Adverb'),
    (7, 'Preposition'),
    (8, 'Conjunction'),
    (9, 'Article'),
    (10, 'Numeral'),
    (11, 'Particle'),
    (12, 'Interjection'),
    (13, 'Suffix');

-- The values of Macula's grammar codes: OSHB morphology for Hebrew and Aramaic, Robinson's for Greek.

insert into stem (id, name) values
    (1, 'Qal'),
    (2, 'Niphal'),
    (3, 'Piel'),
    (4, 'Pual'),
    (5, 'Hiphil'),
    (6, 'Hophal'),
    (7, 'Hithpael'),
    (8, 'Polel'),
    (9, 'Polal'),
    (10, 'Hithpolel'),
    (11, 'Poel'),
    (12, 'Poal'),
    (13, 'Palel'),
    (14, 'Pulal'),
    (15, 'Qal passive'),
    (16, 'Pilpel'),
    (17, 'Polpal'),
    (18, 'Hithpalpel'),
    (19, 'Nithpael'),
    (20, 'Pealal'),
    (21, 'Pilel'),
    (22, 'Hothpaal'),
    (23, 'Tiphil'),
    (24, 'Hishtaphel'),
    (25, 'Nithpalel'),
    (26, 'Nithpoel'),
    (27, 'Hithpoel'),
    (28, 'Peal'),
    (29, 'Peil'),
    (30, 'Hithpeel'),
    (31, 'Pael'),
    (32, 'Ithpaal'),
    (33, 'Hithpaal'),
    (34, 'Aphel'),
    (35, 'Haphel'),
    (36, 'Saphel'),
    (37, 'Shaphel'),
    (38, 'Ithpeel'),
    (39, 'Ishtaphel'),
    (40, 'Hithaphel'),
    (41, 'Ithpoel'),
    (42, 'Hephal'),
    (43, 'Tiphel'),
    (44, 'Palpel'),
    (45, 'Ithpalpel'),
    (46, 'Ithpolel'),
    (47, 'Ittaphal');

insert into verb_form (id, name) values
    (1, 'Perfect'),
    (2, 'Sequential perfect'),
    (3, 'Imperfect'),
    (4, 'Sequential imperfect'),
    (5, 'Cohortative'),
    (6, 'Jussive'),
    (7, 'Imperative'),
    (8, 'Active participle'),
    (9, 'Passive participle'),
    (10, 'Infinitive absolute'),
    (11, 'Infinitive construct');

insert into tense (id, name) values
    (1, 'Present'),
    (2, 'Imperfect'),
    (3, 'Future'),
    (4, 'Aorist'),
    (5, 'Perfect'),
    (6, 'Pluperfect');

insert into voice (id, name) values
    (1, 'Active'),
    (2, 'Middle'),
    (3, 'Passive'),
    (4, 'Middle deponent'),
    (5, 'Passive deponent'),
    (6, 'Middle or passive deponent'),
    (7, 'Middle or passive');

insert into mood (id, name) values
    (1, 'Indicative'),
    (2, 'Subjunctive'),
    (3, 'Optative'),
    (4, 'Imperative'),
    (5, 'Infinitive'),
    (6, 'Participle');

insert into gender (id, name) values
    (1, 'Masculine'),
    (2, 'Feminine'),
    (3, 'Neuter'),
    (4, 'Common'),
    (5, 'Both');

insert into grammatical_number (id, name) values
    (1, 'Singular'),
    (2, 'Plural'),
    (3, 'Dual');

insert into grammatical_case (id, name) values
    (1, 'Nominative'),
    (2, 'Genitive'),
    (3, 'Dative'),
    (4, 'Accusative'),
    (5, 'Vocative');

insert into state (id, name) values
    (1, 'Absolute'),
    (2, 'Construct'),
    (3, 'Determined');

insert into degree (id, name) values
    (1, 'Comparative'),
    (2, 'Superlative');

insert into word_type (id, name) values
    (1, 'Adjective'),
    (2, 'Cardinal number'),
    (3, 'Gentilic'),
    (4, 'Ordinal number'),
    (5, 'Common'),
    (6, 'Demonstrative'),
    (7, 'Indefinite'),
    (8, 'Interrogative'),
    (9, 'Personal'),
    (10, 'Relative'),
    (11, 'Definite article'),
    (12, 'Directional he'),
    (13, 'Paragogic he'),
    (14, 'Paragogic nun'),
    (15, 'Pronominal'),
    (16, 'Affirmation'),
    (17, 'Exhortation'),
    (18, 'Negative'),
    (19, 'Direct object marker'),
    (20, 'Reciprocal'),
    (21, 'Correlative'),
    (22, 'Correlative or interrogative'),
    (23, 'Reflexive'),
    (24, 'Possessive'),
    (25, 'Conditional'),
    (26, 'Letter'),
    (27, 'Numeral');

insert into entity_type (id, parent_id, name) values
    (1, null, 'Person'),
    (2, null, 'Group'),
    (3, null, 'Place'),
    (4, 3, 'City'),
    (5, 3, 'Land'),
    (6, 3, 'Water'),
    (7, 3, 'Mountain'),
    (8, 3, 'Wilderness'),
    (9, null, 'Event'),
    (10, null, 'Object'),
    (11, 10, 'Record'),
    (12, null, 'Office'),
    (13, null, 'Topic');

-- "Refers to" is words that name or point to an entity, pronouns included. "About" is a passage about it.
insert into mention_kind (id, name) values
    (1, 'Refers to'),
    (2, 'About');

insert into speech_mode (id, name) values
    (1, 'Narration'),
    (2, 'Spoken'),
    (3, 'Written'),
    (4, 'Prayer'),
    (5, 'Song');

insert into relationship_kind (id, name, reverse_name, two_way) values
    (1, 'child of', 'parent of', 0),
    (2, 'spouse of', 'spouse of', 1),
    (3, 'sibling of', 'sibling of', 1),
    (4, 'descendant of', 'ancestor of', 0),
    (5, 'member of', 'has member', 0),
    (6, 'leader of', 'led by', 0),
    (7, 'holds office', 'office held by', 0),
    (8, 'part of', 'has part', 0),
    (9, 'took part in', 'has participant', 0),
    (10, 'took place at', 'site of', 0),
    (11, 'located in', 'contains', 0),
    (12, 'north of', 'south of', 0),
    (13, 'east of', 'west of', 0),
    (14, 'higher than', 'lower than', 0),
    (15, 'near', 'near', 1),
    (16, 'borders', 'borders', 1),
    (17, 'named after', 'namesake of', 0),
    (18, 'kept by', 'keeper of', 0),
    (19, 'written by', 'author of', 0),
    (20, 'abridged from', 'abridged into', 0);

insert into counting_system (id, name, needs_evidence) values
    (1, 'Years since Lehi left Jerusalem', 1),
    (2, 'Years of the reign of the judges', 1),
    (3, 'Years since the sign of Christ''s birth', 1),
    (4, 'BC/AD', 0);

insert into link_kind (id, name, two_way) values
    (1, 'Quotes', 0),
    (2, 'Parallel', 1),
    (3, 'Same event', 1),
    (4, 'Alludes to', 0),
    (5, 'Fulfills', 0),
    (6, 'Cross-reference', 1);

insert into clause_role (id, name) values
    (1, 'Subject'),
    (2, 'Verb'),
    (3, 'Object'),
    (4, 'Indirect object'),
    (5, 'Complement'),
    (6, 'Adverbial');

insert into structure_kind (id, name) values
    (1, 'Chiasm'),
    (2, 'Parallelism'),
    (3, 'List'),
    (4, 'Acrostic');

insert into summary_kind (id, name, description) values
    (1, 'Doctrine', 'What the passage teaches about God, Christ, and the plan of salvation.'),
    (2, 'Principles', 'Lessons a reader can apply in daily life.'),
    (3, 'Christ', 'How the passage testifies of Jesus Christ or points to Him.'),
    (4, 'Covenants', 'Promises made with God and the ordinances tied to them.'),
    (5, 'Commandments', 'What God asks His people to do.'),
    (6, 'Prophecies', 'What is foretold and where it is fulfilled.'),
    (7, 'Symbols', 'Objects, events, or people that stand for something more.'),
    (8, 'Questions', 'Questions to think about or discuss.'),
    (9, 'Key verses', 'The two or three most important verses and why each matters.'),
    (10, 'Hard passages', 'Confusing verses explained simply.'),
    (11, 'Connections', 'Where the same idea or event shows up elsewhere in scripture.'),
    (12, 'Setting', 'When, where, and why it happened or was written.'),
    (13, 'People', 'Who appears and what they do.'),
    (14, 'Speakers', 'Who is talking to whom.'),
    (15, 'Original words', 'Key Hebrew or Greek words and what they mean.'),
    (16, 'Culture', 'Customs and background a modern reader would miss.'),
    (17, 'Editors'' comments', 'Where Mormon or Moroni steps in to teach.'),
    (18, 'Revelation background', 'Who the revelation was for, and the question or event that prompted it.'),
    (19, 'Translation background', 'Where Moses, Abraham, and the facsimiles came from.');

insert into summary_kind_work (summary_kind_id, work_id) values
    (1, 1),
    (1, 2),
    (1, 3),
    (1, 4),
    (2, 1),
    (2, 2),
    (2, 3),
    (2, 4),
    (3, 1),
    (3, 2),
    (3, 3),
    (3, 4),
    (4, 1),
    (4, 2),
    (4, 3),
    (4, 4),
    (5, 1),
    (5, 2),
    (5, 3),
    (5, 4),
    (6, 1),
    (6, 2),
    (6, 3),
    (6, 4),
    (7, 1),
    (7, 2),
    (7, 3),
    (7, 4),
    (8, 1),
    (8, 2),
    (8, 3),
    (8, 4),
    (9, 1),
    (9, 2),
    (9, 3),
    (9, 4),
    (10, 1),
    (10, 2),
    (10, 3),
    (10, 4),
    (11, 1),
    (11, 2),
    (11, 3),
    (11, 4),
    (12, 1),
    (12, 2),
    (12, 3),
    (12, 4),
    (13, 1),
    (13, 2),
    (13, 3),
    (13, 4),
    (14, 1),
    (14, 2),
    (14, 3),
    (14, 4),
    (15, 1),
    (16, 1),
    (17, 2),
    (18, 3),
    (19, 4);
