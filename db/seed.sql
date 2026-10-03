insert into work (id, name) values
    ('bible', 'Bible'),
    ('bom', 'Book of Mormon'),
    ('dc', 'Doctrine and Covenants'),
    ('pgp', 'Pearl of Great Price');

insert into edition (id, work_id, name, language) values
    ('kjv', 'bible', 'King James Version (1769)', 'en'),
    ('wlc', 'bible', 'Westminster Leningrad Codex', 'hbo'),
    ('sblgnt', 'bible', 'SBL Greek New Testament', 'grc'),
    ('bom-2013', 'bom', 'Book of Mormon (2013)', 'en'),
    ('dc-2013', 'dc', 'Doctrine and Covenants (2013)', 'en'),
    ('pgp-2013', 'pgp', 'Pearl of Great Price (2013)', 'en');

insert into part_of_speech (id, name) values
    ('noun', 'Noun'),
    ('proper_noun', 'Proper noun'),
    ('pronoun', 'Pronoun'),
    ('verb', 'Verb'),
    ('adjective', 'Adjective'),
    ('adverb', 'Adverb'),
    ('preposition', 'Preposition'),
    ('conjunction', 'Conjunction'),
    ('article', 'Article'),
    ('numeral', 'Numeral'),
    ('particle', 'Particle'),
    ('interjection', 'Interjection');

insert into entity_type (id, parent_id, name) values
    ('person', null, 'Person'),
    ('group', null, 'Group'),
    ('place', null, 'Place'),
    ('city', 'place', 'City'),
    ('land', 'place', 'Land'),
    ('water', 'place', 'Water'),
    ('mountain', 'place', 'Mountain'),
    ('wilderness', 'place', 'Wilderness'),
    ('event', null, 'Event'),
    ('object', null, 'Object'),
    ('record', 'object', 'Record'),
    ('office', null, 'Office'),
    ('topic', null, 'Topic');

insert into mention_kind (id, name) values
    ('names', 'Names'),
    ('about', 'About');

insert into speech_mode (id, name) values
    ('narration', 'Narration'),
    ('spoken', 'Spoken'),
    ('written', 'Written'),
    ('prayer', 'Prayer'),
    ('song', 'Song');

insert into relationship_kind (id, name, reverse_name, two_way) values
    ('child_of', 'child of', 'parent of', 0),
    ('spouse_of', 'spouse of', 'spouse of', 1),
    ('sibling_of', 'sibling of', 'sibling of', 1),
    ('descendant_of', 'descendant of', 'ancestor of', 0),
    ('member_of', 'member of', 'has member', 0),
    ('leader_of', 'leader of', 'led by', 0),
    ('holds_office', 'holds office', 'office held by', 0),
    ('part_of', 'part of', 'has part', 0),
    ('took_part_in', 'took part in', 'has participant', 0),
    ('took_place_at', 'took place at', 'site of', 0),
    ('located_in', 'located in', 'contains', 0),
    ('north_of', 'north of', 'south of', 0),
    ('east_of', 'east of', 'west of', 0),
    ('higher_than', 'higher than', 'lower than', 0),
    ('near', 'near', 'near', 1),
    ('borders', 'borders', 'borders', 1),
    ('named_after', 'named after', 'namesake of', 0),
    ('kept_by', 'kept by', 'keeper of', 0),
    ('written_by', 'written by', 'author of', 0),
    ('abridged_from', 'abridged from', 'abridged into', 0);

insert into counting_system (id, name) values
    ('since_lehi', 'Years since Lehi left Jerusalem'),
    ('reign_of_judges', 'Years of the reign of the judges'),
    ('since_sign', 'Years since the sign of Christ''s birth'),
    ('bc_ad', 'BC/AD');

insert into link_kind (id, name, two_way) values
    ('quotes', 'Quotes', 0),
    ('parallel', 'Parallel', 1),
    ('same_event', 'Same event', 1),
    ('alludes_to', 'Alludes to', 0),
    ('fulfills', 'Fulfills', 0),
    ('cross_reference', 'Cross-reference', 1);

insert into clause_role (id, name) values
    ('subject', 'Subject'),
    ('verb', 'Verb'),
    ('object', 'Object'),
    ('indirect_object', 'Indirect object'),
    ('complement', 'Complement'),
    ('adverbial', 'Adverbial');

insert into structure_kind (id, name) values
    ('chiasm', 'Chiasm'),
    ('parallelism', 'Parallelism'),
    ('list', 'List'),
    ('acrostic', 'Acrostic');
