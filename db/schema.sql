-- SQLite enforces foreign keys only on connections that turn them on.
pragma foreign_keys = on;

-- Text

create table work (
    id text primary key,
    name text not null
) strict;

create table edition (
    id text primary key,
    work_id text not null references work,
    name text not null,
    language text not null
) strict;

create table book (
    id text primary key,
    work_id text not null references work,
    name text not null
) strict;

create table edition_book (
    edition_id text not null references edition,
    book_id text not null references book,
    position integer not null,
    primary key (edition_id, book_id),
    unique (edition_id, position)
) strict;

-- Word ids follow reading order within an edition, so a passage is every word
-- whose id falls between its first and last word.
create table word (
    id integer primary key,
    edition_id text not null,
    book_id text not null,
    chapter integer not null,
    verse integer not null,
    position integer not null,
    text text not null,
    before text not null default '',
    after text not null default '',
    supplied integer not null default 0 check (supplied in (0, 1)),
    unique (edition_id, book_id, chapter, verse, position),
    foreign key (edition_id, book_id) references edition_book
) strict;

-- Dictionary

create table part_of_speech (
    id text primary key,
    name text not null
) strict;

create table headword (
    id integer primary key,
    language text not null,
    text text not null,
    strongs text,
    gloss text,
    unique (language, text, strongs)
) strict;

create table meaning (
    id integer primary key,
    headword_id integer not null references headword,
    number integer not null,
    gloss text not null,
    definition text,
    unique (headword_id, number)
) strict;

create table word_headword (
    word_id integer primary key references word,
    headword_id integer not null references headword,
    part_of_speech text not null references part_of_speech,
    grammar text
) strict;

create index word_headword_headword on word_headword (headword_id);

create table word_meaning (
    word_id integer primary key references word,
    meaning_id integer not null references meaning
) strict;

create index word_meaning_meaning on word_meaning (meaning_id);

-- Word matches are stored once, lower word id first.
create table word_match (
    word_id integer not null references word,
    other_word_id integer not null references word,
    primary key (word_id, other_word_id),
    check (word_id < other_word_id)
) strict;

create index word_match_other on word_match (other_word_id);

-- Entities

create table entity_type (
    id text primary key,
    parent_id text references entity_type,
    name text not null
) strict;

create table entity (
    id text primary key,
    type_id text not null references entity_type,
    name text not null,
    description text not null
) strict;

create table entity_name (
    entity_id text not null references entity,
    name text not null,
    is_title integer not null default 0 check (is_title in (0, 1)),
    primary key (entity_id, name)
) strict;

create index entity_name_name on entity_name (name);

create table entity_book (
    entity_id text not null references entity,
    book_id text not null references book,
    primary key (entity_id, book_id)
) strict;

-- Mentions

create table mention_kind (
    id text primary key,
    name text not null
) strict;

create table mention (
    id integer primary key,
    entity_id text not null references entity,
    kind_id text not null references mention_kind,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    unique (entity_id, kind_id, first_word_id, last_word_id),
    check (first_word_id <= last_word_id)
) strict;

create index mention_first_word on mention (first_word_id, last_word_id);

-- Speakers

create table speech_mode (
    id text primary key,
    name text not null
) strict;

create table speech (
    id integer primary key,
    speaker_id text not null references entity,
    mode_id text not null references speech_mode,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    unique (first_word_id, last_word_id),
    check (first_word_id <= last_word_id)
) strict;

create index speech_speaker on speech (speaker_id);

create table speech_listener (
    speech_id integer not null references speech on delete cascade,
    entity_id text not null references entity,
    primary key (speech_id, entity_id)
) strict;

create index speech_listener_entity on speech_listener (entity_id);

-- Relationships

create table relationship_kind (
    id text primary key,
    name text not null,
    reverse_name text not null,
    two_way integer not null check (two_way in (0, 1))
) strict;

create table relationship (
    id integer primary key,
    subject_id text not null references entity,
    kind_id text not null references relationship_kind,
    object_id text not null references entity,
    days real,
    unique (subject_id, kind_id, object_id),
    check (subject_id <> object_id)
) strict;

create index relationship_object on relationship (object_id);

create table relationship_evidence (
    relationship_id integer not null references relationship on delete cascade,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    primary key (relationship_id, first_word_id, last_word_id),
    check (first_word_id <= last_word_id)
) strict;

-- Dates

create table counting_system (
    id text primary key,
    name text not null
) strict;

-- BC/AD years count 1 BC as 0 and 2 BC as -1, so ranges subtract cleanly.
create table date (
    id integer primary key,
    first_word_id integer references word,
    last_word_id integer references word,
    entity_id text references entity,
    relationship_id integer references relationship on delete cascade,
    system_id text not null references counting_system,
    from_year integer not null,
    from_month integer check (from_month between 1 and 12),
    from_day integer check (from_day between 1 and 31),
    to_year integer not null,
    to_month integer check (to_month between 1 and 12),
    to_day integer check (to_day between 1 and 31),
    evidence_first_word_id integer not null references word,
    evidence_last_word_id integer not null references word,
    check ((first_word_id is null) = (last_word_id is null)),
    check ((first_word_id is not null) + (entity_id is not null) + (relationship_id is not null) = 1),
    check (first_word_id <= last_word_id),
    check (evidence_first_word_id <= evidence_last_word_id),
    check (to_year >= from_year)
) strict;

create index date_first_word on date (first_word_id, last_word_id);
create index date_entity on date (entity_id);
create index date_relationship on date (relationship_id);

-- Passage links

create table link_kind (
    id text primary key,
    name text not null,
    two_way integer not null check (two_way in (0, 1))
) strict;

create table passage_link (
    id integer primary key,
    kind_id text not null references link_kind,
    from_first_word_id integer not null references word,
    from_last_word_id integer not null references word,
    to_first_word_id integer not null references word,
    to_last_word_id integer not null references word,
    unique (kind_id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id),
    check (from_first_word_id <= from_last_word_id),
    check (to_first_word_id <= to_last_word_id)
) strict;

create index passage_link_from on passage_link (from_first_word_id, from_last_word_id);
create index passage_link_to on passage_link (to_first_word_id, to_last_word_id);

-- Grammar

create table sentence (
    id integer primary key,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    unique (first_word_id, last_word_id),
    check (first_word_id <= last_word_id)
) strict;

create table clause (
    id integer primary key,
    sentence_id integer not null references sentence on delete cascade,
    parent_id integer references clause on delete cascade,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    check (first_word_id <= last_word_id)
) strict;

create index clause_sentence on clause (sentence_id);
create index clause_parent on clause (parent_id);

create table clause_role (
    id text primary key,
    name text not null
) strict;

create table clause_part (
    id integer primary key,
    clause_id integer not null references clause on delete cascade,
    role_id text not null references clause_role,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    check (first_word_id <= last_word_id)
) strict;

create index clause_part_clause on clause_part (clause_id);

-- Literary structures

create table structure_kind (
    id text primary key,
    name text not null
) strict;

create table structure (
    id integer primary key,
    kind_id text not null references structure_kind,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    check (first_word_id <= last_word_id)
) strict;

create index structure_first_word on structure (first_word_id, last_word_id);

-- Parts are numbered in reading order across the whole structure, nested parts included.
create table structure_part (
    id integer primary key,
    structure_id integer not null references structure on delete cascade,
    parent_id integer references structure_part on delete cascade,
    position integer not null,
    label text not null,
    pairs_with_id integer references structure_part,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    unique (structure_id, position),
    check (first_word_id <= last_word_id)
) strict;
