-- SQLite enforces foreign keys only on connections that turn them on.
pragma foreign_keys = on;

-- Text

create table language (
    id integer primary key,
    name text not null unique,
    iso_code text not null unique
) strict;

create table work (
    id integer primary key,
    name text not null unique
) strict;

create table edition (
    id integer primary key,
    work_id integer not null references work,
    language_id integer not null references language,
    name text not null unique,
    unique (id, work_id)
) strict;

create table book (
    id integer primary key,
    work_id integer not null references work,
    name text not null,
    unique (id, work_id),
    unique (work_id, name)
) strict;

-- work_id lets both foreign keys require that the edition and the book belong to the same work.
create table edition_book (
    edition_id integer not null,
    book_id integer not null,
    work_id integer not null,
    position integer not null,
    primary key (edition_id, book_id),
    unique (edition_id, position),
    foreign key (edition_id, work_id) references edition (id, work_id),
    foreign key (book_id, work_id) references book (id, work_id)
) strict;

-- Editions number some chapters differently, so each edition has its own.
create table chapter (
    id integer primary key,
    edition_id integer not null,
    book_id integer not null,
    number integer not null,
    unique (edition_id, book_id, number),
    foreign key (edition_id, book_id) references edition_book
) strict;

-- A verse without a number is the text printed before verse 1: a book title, a chapter heading, a psalm's title.
create table verse (
    id integer primary key,
    chapter_id integer not null references chapter,
    number integer,
    unique (chapter_id, number)
) strict;

create unique index verse_heading on verse (chapter_id) where number is null;

create table part_of_speech (
    id integer primary key,
    name text not null unique
) strict;

-- sequence is reading order across the whole database, so a passage is every word whose sequence falls between its
-- first and last word. It is the one stored value that could be computed, because a passage needs one number to compare.
create table word (
    id integer primary key,
    verse_id integer not null references verse,
    position integer not null,
    sequence integer not null unique,
    text text not null,
    before text not null default '',
    after text not null default '',
    supplied integer not null default 0 check (supplied in (0, 1)),
    headword_id integer references headword,
    part_of_speech_id integer references part_of_speech,
    meaning_id integer,
    unique (verse_id, position),
    foreign key (headword_id, meaning_id) references meaning (headword_id, id),
    check (meaning_id is null or headword_id is not null)
) strict;

create index word_headword_meaning on word (headword_id, meaning_id);

-- Grammar of Hebrew, Aramaic, and Greek words

create table stem (
    id integer primary key,
    name text not null unique
) strict;

create table verb_form (
    id integer primary key,
    name text not null unique
) strict;

create table tense (
    id integer primary key,
    name text not null unique
) strict;

create table voice (
    id integer primary key,
    name text not null unique
) strict;

create table mood (
    id integer primary key,
    name text not null unique
) strict;

create table gender (
    id integer primary key,
    name text not null unique
) strict;

create table grammatical_number (
    id integer primary key,
    name text not null unique
) strict;

create table grammatical_case (
    id integer primary key,
    name text not null unique
) strict;

create table state (
    id integer primary key,
    name text not null unique
) strict;

create table degree (
    id integer primary key,
    name text not null unique
) strict;

-- The narrower kind a grammar code gives some parts of speech: a cardinal number, a personal pronoun, a negative particle.
create table word_type (
    id integer primary key,
    name text not null unique
) strict;

create table hebrew_word (
    word_id integer primary key references word,
    word_type_id integer references word_type,
    stem_id integer references stem,
    verb_form_id integer references verb_form,
    person integer check (person between 1 and 3),
    gender_id integer references gender,
    grammatical_number_id integer references grammatical_number,
    state_id integer references state
) strict;

create trigger hebrew_word_language_insert before insert on hebrew_word
when (select l.iso_code from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id
      join edition e on e.id = c.edition_id join language l on l.id = e.language_id where w.id = new.word_id) <> 'hbo'
begin
    select raise(abort, 'a hebrew_word must be a word of a Hebrew edition');
end;

create trigger hebrew_word_language_update before update of word_id on hebrew_word
when (select l.iso_code from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id
      join edition e on e.id = c.edition_id join language l on l.id = e.language_id where w.id = new.word_id) <> 'hbo'
begin
    select raise(abort, 'a hebrew_word must be a word of a Hebrew edition');
end;

-- second_form marks Robinson's "2": a second aorist, future, or perfect.
create table greek_word (
    word_id integer primary key references word,
    word_type_id integer references word_type,
    tense_id integer references tense,
    second_form integer not null default 0 check (second_form in (0, 1)),
    voice_id integer references voice,
    mood_id integer references mood,
    person integer check (person between 1 and 3),
    grammatical_case_id integer references grammatical_case,
    gender_id integer references gender,
    grammatical_number_id integer references grammatical_number,
    possessor_number_id integer references grammatical_number,
    degree_id integer references degree,
    indeclinable integer not null default 0 check (indeclinable in (0, 1)),
    crasis integer not null default 0 check (crasis in (0, 1)),
    attic_form integer not null default 0 check (attic_form in (0, 1)),
    transliterated_from_id integer references language
) strict;

create trigger greek_word_language_insert before insert on greek_word
when (select l.iso_code from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id
      join edition e on e.id = c.edition_id join language l on l.id = e.language_id where w.id = new.word_id) <> 'grc'
begin
    select raise(abort, 'a greek_word must be a word of a Greek edition');
end;

create trigger greek_word_language_update before update of word_id on greek_word
when (select l.iso_code from word w join verse v on v.id = w.verse_id join chapter c on c.id = v.chapter_id
      join edition e on e.id = c.edition_id join language l on l.id = e.language_id where w.id = new.word_id) <> 'grc'
begin
    select raise(abort, 'a greek_word must be a word of a Greek edition');
end;

-- Dictionary

-- strongs is the Strong's number as written, such as H0001b: an outside standard.
create table headword (
    id integer primary key,
    language_id integer not null references language,
    text text not null,
    strongs text,
    gloss text,
    unique (language_id, text, strongs)
) strict;

-- Unique on (headword_id, id) so a word's meaning must belong to its headword.
create table meaning (
    id integer primary key,
    headword_id integer not null references headword,
    number integer not null,
    gloss text not null,
    definition text,
    unique (headword_id, number),
    unique (headword_id, id)
) strict;

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
    id integer primary key,
    parent_id integer references entity_type,
    name text not null unique
) strict;

-- tipnr is the entity's identifier in STEPBible's TIPNR, its unified Strong's number such as H0175: an outside standard.
create table entity (
    id integer primary key,
    entity_type_id integer not null references entity_type,
    name text not null,
    description text not null,
    tipnr text unique
) strict;

-- Names and titles other than entity.name.
create table entity_name (
    entity_id integer not null references entity,
    name text not null,
    is_title integer not null default 0 check (is_title in (0, 1)),
    primary key (entity_id, name)
) strict;

create index entity_name_name on entity_name (name);

create trigger entity_name_main_insert before insert on entity_name
when new.name = (select name from entity where id = new.entity_id)
begin
    select raise(abort, 'an entity''s main name belongs in entity.name');
end;

create trigger entity_name_main_update before update on entity_name
when new.name = (select name from entity where id = new.entity_id)
begin
    select raise(abort, 'an entity''s main name belongs in entity.name');
end;

create trigger entity_main_name_update before update of name on entity
when exists (select 1 from entity_name where entity_id = new.id and name = new.name)
begin
    select raise(abort, 'an entity''s main name belongs in entity.name');
end;

-- Mentions

create table mention_kind (
    id integer primary key,
    name text not null unique
) strict;

create table mention (
    id integer primary key,
    entity_id integer not null references entity,
    mention_kind_id integer not null references mention_kind,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    unique (entity_id, mention_kind_id, first_word_id, last_word_id)
) strict;

create index mention_first_word on mention (first_word_id, last_word_id);

-- Speakers

create table speech_mode (
    id integer primary key,
    name text not null unique
) strict;

create table speech (
    id integer primary key,
    speaker_id integer not null references entity,
    through_id integer references entity,
    speech_mode_id integer not null references speech_mode,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    unique (first_word_id, last_word_id),
    check (through_id <> speaker_id)
) strict;

create index speech_speaker on speech (speaker_id);

create table speech_listener (
    speech_id integer not null references speech on delete cascade,
    entity_id integer not null references entity,
    primary key (speech_id, entity_id)
) strict;

create index speech_listener_entity on speech_listener (entity_id);

-- Relationships

create table relationship_kind (
    id integer primary key,
    name text not null unique,
    reverse_name text not null,
    two_way integer not null check (two_way in (0, 1))
) strict;

create table relationship (
    id integer primary key,
    subject_id integer not null references entity,
    relationship_kind_id integer not null references relationship_kind,
    object_id integer not null references entity,
    check (subject_id <> object_id)
) strict;

-- A pair of entities holds each kind once, in either direction: two-way kinds
-- are stored once, and a one-way kind that runs both ways contradicts itself.
create unique index relationship_pair on relationship (relationship_kind_id, min(subject_id, object_id), max(subject_id, object_id));
create index relationship_subject on relationship (subject_id);
create index relationship_object on relationship (object_id);

create table relationship_evidence (
    relationship_id integer not null references relationship on delete cascade,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    primary key (relationship_id, first_word_id, last_word_id)
) strict;

-- Journeys

create table journey (
    id integer primary key,
    traveler_id integer not null references entity,
    from_id integer references entity,
    to_id integer not null references entity,
    days real check (days > 0),
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    check (from_id <> to_id)
) strict;

create index journey_traveler on journey (traveler_id);
create index journey_from on journey (from_id);
create index journey_to on journey (to_id);

-- Dates

-- needs_evidence is 0 for a system whose dates may be our estimate where the text gives no year.
create table counting_system (
    id integer primary key,
    name text not null unique,
    needs_evidence integer not null check (needs_evidence in (0, 1))
) strict;

-- BC/AD years count 1 BC as 0 and 2 BC as -1, so ranges subtract cleanly.
create table date (
    id integer primary key,
    first_word_id integer references word,
    last_word_id integer references word,
    entity_id integer references entity,
    relationship_id integer references relationship on delete cascade,
    counting_system_id integer not null references counting_system,
    from_year integer not null,
    from_month integer check (from_month between 1 and 12),
    from_day integer check (from_day between 1 and 31),
    to_year integer not null,
    to_month integer check (to_month between 1 and 12),
    to_day integer check (to_day between 1 and 31),
    evidence_first_word_id integer references word,
    evidence_last_word_id integer references word,
    check ((first_word_id is null) = (last_word_id is null)),
    check ((evidence_first_word_id is null) = (evidence_last_word_id is null)),
    check ((first_word_id is not null) + (entity_id is not null) + (relationship_id is not null) = 1),
    check (to_year >= from_year)
) strict;

create index date_first_word on date (first_word_id, last_word_id);
create index date_entity on date (entity_id);
create index date_relationship on date (relationship_id);

create trigger date_evidence_insert before insert on date
when new.evidence_first_word_id is null and (select needs_evidence from counting_system where id = new.counting_system_id)
begin
    select raise(abort, 'a date in this counting system needs evidence');
end;

create trigger date_evidence_update before update on date
when new.evidence_first_word_id is null and (select needs_evidence from counting_system where id = new.counting_system_id)
begin
    select raise(abort, 'a date in this counting system needs evidence');
end;

-- Passage links

create table link_kind (
    id integer primary key,
    name text not null unique,
    two_way integer not null check (two_way in (0, 1))
) strict;

create table passage_link (
    id integer primary key,
    link_kind_id integer not null references link_kind,
    from_first_word_id integer not null references word,
    from_last_word_id integer not null references word,
    to_first_word_id integer not null references word,
    to_last_word_id integer not null references word,
    unique (link_kind_id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id)
) strict;

create index passage_link_from on passage_link (from_first_word_id, from_last_word_id);
create index passage_link_to on passage_link (to_first_word_id, to_last_word_id);

-- A two-way link is stored once, from the passage that comes first.
create trigger passage_link_two_way_insert before insert on passage_link
when (select two_way from link_kind where id = new.link_kind_id)
    and ((select sequence from word where id = new.from_first_word_id), (select sequence from word where id = new.from_last_word_id))
        > ((select sequence from word where id = new.to_first_word_id), (select sequence from word where id = new.to_last_word_id))
begin
    select raise(abort, 'a two-way link runs from the passage that comes first');
end;

create trigger passage_link_two_way_update before update on passage_link
when (select two_way from link_kind where id = new.link_kind_id)
    and ((select sequence from word where id = new.from_first_word_id), (select sequence from word where id = new.from_last_word_id))
        > ((select sequence from word where id = new.to_first_word_id), (select sequence from word where id = new.to_last_word_id))
begin
    select raise(abort, 'a two-way link runs from the passage that comes first');
end;

-- Grammar

create table sentence (
    id integer primary key,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    unique (first_word_id, last_word_id)
) strict;

create table clause (
    id integer primary key,
    sentence_id integer not null references sentence on delete cascade,
    parent_id integer references clause on delete cascade,
    first_word_id integer not null references word,
    last_word_id integer not null references word
) strict;

create index clause_sentence on clause (sentence_id);
create index clause_parent on clause (parent_id);

create table clause_role (
    id integer primary key,
    name text not null unique
) strict;

create table clause_part (
    id integer primary key,
    clause_id integer not null references clause on delete cascade,
    clause_role_id integer not null references clause_role,
    first_word_id integer not null references word,
    last_word_id integer not null references word
) strict;

create index clause_part_clause on clause_part (clause_id);

-- Literary structures

create table structure_kind (
    id integer primary key,
    name text not null unique
) strict;

create table structure (
    id integer primary key,
    structure_kind_id integer not null references structure_kind,
    first_word_id integer not null references word,
    last_word_id integer not null references word
) strict;

create index structure_first_word on structure (first_word_id, last_word_id);

-- Parts are numbered in reading order across the whole structure, nested parts included.
create table structure_part (
    id integer primary key,
    structure_id integer not null references structure on delete cascade,
    parent_id integer references structure_part on delete cascade,
    position integer not null,
    pairs_with_id integer references structure_part,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    unique (structure_id, position)
) strict;

-- Summaries

create table verse_range (
    id integer primary key,
    name text not null unique,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    unique (first_word_id, last_word_id)
) strict;

create table summary_kind (
    id integer primary key,
    name text not null unique,
    description text not null
) strict;

create table summary_kind_work (
    summary_kind_id integer not null references summary_kind,
    work_id integer not null references work,
    primary key (summary_kind_id, work_id)
) strict;

create table summary (
    id integer primary key,
    summary_kind_id integer not null references summary_kind,
    chapter_id integer references chapter,
    book_id integer references book,
    verse_range_id integer references verse_range,
    text text not null check (text <> ''),
    check ((chapter_id is not null) + (book_id is not null) + (verse_range_id is not null) = 1)
) strict;

create unique index summary_chapter on summary (summary_kind_id, chapter_id) where chapter_id is not null;
create unique index summary_book on summary (summary_kind_id, book_id) where book_id is not null;
create unique index summary_range on summary (summary_kind_id, verse_range_id) where verse_range_id is not null;

create trigger summary_kind_work_insert before insert on summary
when not exists (
    select 1 from summary_kind_work k
    where k.summary_kind_id = new.summary_kind_id and k.work_id = coalesce(
        (select e.work_id from chapter c join edition e on e.id = c.edition_id where c.id = new.chapter_id),
        (select work_id from book where id = new.book_id),
        (select e.work_id from verse_range r join word w on w.id = r.first_word_id join verse v on v.id = w.verse_id
         join chapter c on c.id = v.chapter_id join edition e on e.id = c.edition_id where r.id = new.verse_range_id)))
begin
    select raise(abort, 'this summary kind does not apply to this work');
end;

create trigger summary_kind_work_update before update on summary
when not exists (
    select 1 from summary_kind_work k
    where k.summary_kind_id = new.summary_kind_id and k.work_id = coalesce(
        (select e.work_id from chapter c join edition e on e.id = c.edition_id where c.id = new.chapter_id),
        (select work_id from book where id = new.book_id),
        (select e.work_id from verse_range r join word w on w.id = r.first_word_id join verse v on v.id = w.verse_id
         join chapter c on c.id = v.chapter_id join edition e on e.id = c.edition_id where r.id = new.verse_range_id)))
begin
    select raise(abort, 'this summary kind does not apply to this work');
end;

-- Passages

-- Every passage runs forward within one edition: both ends in the same edition, the first word no later than the last.

create trigger mention_passage_insert before insert on mention
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger mention_passage_update before update of first_word_id, last_word_id on mention
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger speech_passage_insert before insert on speech
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger speech_passage_update before update of first_word_id, last_word_id on speech
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger relationship_evidence_passage_insert before insert on relationship_evidence
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger relationship_evidence_passage_update before update of first_word_id, last_word_id on relationship_evidence
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger journey_passage_insert before insert on journey
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger journey_passage_update before update of first_word_id, last_word_id on journey
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger date_passage_insert before insert on date
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
    or not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.evidence_first_word_id and b.id = new.evidence_last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger date_passage_update before update of first_word_id, last_word_id, evidence_first_word_id, evidence_last_word_id on date
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
    or not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.evidence_first_word_id and b.id = new.evidence_last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger passage_link_passage_insert before insert on passage_link
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.from_first_word_id and b.id = new.from_last_word_id)
    or not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.to_first_word_id and b.id = new.to_last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger passage_link_passage_update before update of from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id on passage_link
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.from_first_word_id and b.id = new.from_last_word_id)
    or not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.to_first_word_id and b.id = new.to_last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger sentence_passage_insert before insert on sentence
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger sentence_passage_update before update of first_word_id, last_word_id on sentence
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger clause_passage_insert before insert on clause
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger clause_passage_update before update of first_word_id, last_word_id on clause
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger clause_part_passage_insert before insert on clause_part
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger clause_part_passage_update before update of first_word_id, last_word_id on clause_part
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger structure_passage_insert before insert on structure
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger structure_passage_update before update of first_word_id, last_word_id on structure
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger structure_part_passage_insert before insert on structure_part
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger structure_part_passage_update before update of first_word_id, last_word_id on structure_part
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger verse_range_passage_insert before insert on verse_range
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;

create trigger verse_range_passage_update before update of first_word_id, last_word_id on verse_range
when not (select a.sequence <= b.sequence and ca.edition_id = cb.edition_id
         from word a join verse va on va.id = a.verse_id join chapter ca on ca.id = va.chapter_id,
              word b join verse vb on vb.id = b.verse_id join chapter cb on cb.id = vb.chapter_id
         where a.id = new.first_word_id and b.id = new.last_word_id)
begin
    select raise(abort, 'a passage must run forward within one edition');
end;
