insert into work (slug, name) values
    ('bible', 'Bible'),
    ('bom', 'Book of Mormon'),
    ('dc', 'Doctrine and Covenants'),
    ('pgp', 'Pearl of Great Price');

insert into segment_kind (slug, name) values
    ('verse', 'Verse'),
    ('title', 'Title'),
    ('subtitle', 'Subtitle'),
    ('heading', 'Heading'),
    ('superscription', 'Superscription'),
    ('subscription', 'Subscription'),
    ('acrostic_label', 'Acrostic label'),
    ('testimony', 'Testimony'),
    ('preface', 'Preface'),
    ('note', 'Note'),
    ('figure_explanation', 'Figure explanation'),
    ('paragraph', 'Paragraph');

insert into alignment_kind (slug, name) values
    ('same', 'Same word'),
    ('variant', 'Variant'),
    ('translates', 'Translates'),
    ('parallel', 'Parallel'),
    ('no_counterpart', 'No counterpart');

insert into entity_type (slug, parent_slug, name) values
    ('person', null, 'Person'),
    ('group', null, 'Group'),
    ('place', null, 'Place'),
    ('event', null, 'Event'),
    ('object', null, 'Object'),
    ('record', 'object', 'Record'),
    ('topic', null, 'Topic'),
    ('time_period', null, 'Time period');

insert into relation_type (slug, name, inverse_name) values
    ('child_of', 'child of', 'parent of'),
    ('spouse_of', 'spouse of', 'spouse of'),
    ('sibling_of', 'sibling of', 'sibling of'),
    ('descendant_of', 'descendant of', 'ancestor of'),
    ('member_of', 'member of', 'has member'),
    ('leader_of', 'leader of', 'led by'),
    ('office_holder', 'holds office of', 'office held by'),
    ('part_of', 'part of', 'has part'),
    ('participant_in', 'participant in', 'has participant'),
    ('took_place_at', 'took place at', 'site of'),
    ('located_in', 'located in', 'contains'),
    ('north_of', 'north of', 'south of'),
    ('east_of', 'east of', 'west of'),
    ('higher_than', 'higher than', 'lower than'),
    ('near', 'near', 'near'),
    ('borders', 'borders', 'borders'),
    ('journey_to', 'journey to', 'journey from'),
    ('named_after', 'named after', 'namesake of'),
    ('kept_by', 'kept by', 'keeper of'),
    ('written_by', 'written by', 'author of'),
    ('abridged_from', 'abridged from', 'abridged into'),
    ('handed_to', 'handed to', 'received from');

insert into speech_mode (slug, name) values
    ('narration', 'Narration'),
    ('spoken', 'Spoken'),
    ('written', 'Written'),
    ('prayer', 'Prayer'),
    ('song', 'Song');

insert into clause_role (slug, name) values
    ('subject', 'Subject'),
    ('verb', 'Verb'),
    ('object', 'Object'),
    ('indirect_object', 'Indirect object'),
    ('complement', 'Complement'),
    ('adverbial', 'Adverbial');

insert into structure_kind (slug, name) values
    ('chiasm', 'Chiasm'),
    ('parallelism', 'Parallelism'),
    ('list', 'List'),
    ('acrostic', 'Acrostic');

insert into link_type (slug, name) values
    ('quotes', 'Quotes'),
    ('parallel', 'Parallel'),
    ('same_event', 'Same event'),
    ('alludes', 'Alludes to'),
    ('fulfills', 'Fulfills'),
    ('cross_reference', 'Cross-reference');

insert into calendar (slug, name) values
    ('western', 'BC/AD'),
    ('since_lehi', 'Years since Lehi left Jerusalem'),
    ('reign_of_judges', 'Years of the reign of the judges'),
    ('since_sign', 'Years since the sign of Christ''s birth');
