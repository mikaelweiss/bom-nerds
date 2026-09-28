create type review_status as enum ('unreviewed', 'verified', 'flagged');
create type source_kind as enum ('dataset', 'ai_run', 'contributor');
create type mention_kind as enum ('refers', 'about');

create table source (
    id bigint generated always as identity primary key,
    kind source_kind not null,
    name text not null,
    url text,
    license text,
    attribution text,
    details jsonb not null default '{}',
    created_at timestamptz not null default now()
);

-- Text

create table work (
    id bigint generated always as identity primary key,
    slug text not null unique,
    name text not null
);

create table book (
    id bigint generated always as identity primary key,
    work_id bigint not null references work,
    slug text not null,
    name text not null,
    unique (work_id, slug)
);

create table edition (
    id bigint generated always as identity primary key,
    work_id bigint not null references work,
    slug text not null unique,
    name text not null,
    published_year int,
    language text not null,
    is_reference boolean not null default false,
    source_id bigint not null references source
);

-- Study data attaches to reference-edition words and reaches other editions through word_alignment.
create unique index one_reference_edition_per_work on edition (work_id) where is_reference;

create table edition_book (
    edition_id bigint not null references edition,
    book_id bigint not null references book,
    seq int not null,
    primary key (edition_id, book_id),
    unique (edition_id, seq)
);

create table segment_kind (
    slug text primary key,
    name text not null
);

create table segment (
    id bigint generated always as identity primary key,
    edition_id bigint not null references edition,
    book_id bigint not null references book,
    kind text not null references segment_kind,
    chapter int,
    number int,
    label text,
    seq int not null,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed',
    unique (edition_id, seq)
);

create index on segment (edition_id, book_id, chapter, number);

create table word (
    id bigint generated always as identity primary key,
    edition_id bigint not null references edition,
    segment_id bigint not null references segment,
    seq int not null,
    text text not null,
    prefix text not null default '',
    suffix text not null default '',
    italic boolean not null default false,
    small_caps boolean not null default false,
    paragraph_start boolean not null default false,
    unique (edition_id, seq)
);

create index on word (segment_id);

create table page_break (
    first_word_id bigint primary key references word,
    page_label text not null
);

-- A span is a first and last word. It covers every word of that edition whose seq falls between them.
create function check_span() returns trigger language plpgsql as $$
declare
    first_id bigint := (to_jsonb(new) ->> tg_argv[0])::bigint;
    last_id bigint := (to_jsonb(new) ->> tg_argv[1])::bigint;
begin
    if first_id is null and last_id is null then
        return new;
    end if;
    if not exists (
        select 1
        from word f
        join word l on l.edition_id = f.edition_id and l.seq >= f.seq
        where f.id = first_id and l.id = last_id
    ) then
        raise exception '%: span %..% must run forward within one edition', tg_table_name, first_id, last_id;
    end if;
    return new;
end
$$;

-- Words and meanings

create table lemma (
    id bigint generated always as identity primary key,
    language text not null,
    text text not null,
    strongs text,
    gloss text,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed',
    unique nulls not distinct (language, text, strongs)
);

create table sense (
    id bigint generated always as identity primary key,
    lemma_id bigint not null references lemma,
    gloss text not null,
    definition text,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on sense (lemma_id);

create table word_lemma (
    word_id bigint primary key references word,
    lemma_id bigint not null references lemma,
    part_of_speech text not null,
    morphology text,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on word_lemma (lemma_id);

create table word_sense (
    word_id bigint primary key references word,
    sense_id bigint not null references sense,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on word_sense (sense_id);

create table alignment_kind (
    slug text primary key,
    name text not null
);

create table word_alignment (
    id bigint generated always as identity primary key,
    word_id bigint not null references word,
    other_edition_id bigint not null references edition,
    other_word_id bigint references word,
    kind text not null references alignment_kind,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed',
    check ((kind = 'no_counterpart') = (other_word_id is null))
);

create index on word_alignment (word_id);
create index on word_alignment (other_word_id);

-- Entities

create table entity_type (
    slug text primary key,
    parent_slug text references entity_type,
    name text not null
);

create table entity (
    id bigint generated always as identity primary key,
    type text not null references entity_type,
    slug text not null unique,
    name text not null,
    description text,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on entity (type);

create table entity_name (
    id bigint generated always as identity primary key,
    entity_id bigint not null references entity,
    name text not null,
    is_title boolean not null default false,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed',
    unique (entity_id, name)
);

create index on entity_name (name);

-- 'refers': the words name or point to the entity ("Nephi", "he", "the Holy One of Israel").
-- 'about': the passage concerns the entity without naming it, as with topics.
create table mention (
    id bigint generated always as identity primary key,
    entity_id bigint not null references entity,
    kind mention_kind not null,
    first_word_id bigint not null references word,
    last_word_id bigint not null references word,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on mention (entity_id);
create index on mention (first_word_id);
create trigger mention_span before insert or update on mention
    for each row execute function check_span('first_word_id', 'last_word_id');

create table relation_type (
    slug text primary key,
    name text not null,
    inverse_name text not null
);

create table relation (
    id bigint generated always as identity primary key,
    subject_id bigint not null references entity,
    type text not null references relation_type,
    object_id bigint not null references entity,
    detail text,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on relation (subject_id);
create index on relation (object_id);

create table relation_evidence (
    relation_id bigint not null references relation,
    first_word_id bigint not null references word,
    last_word_id bigint not null references word,
    primary key (relation_id, first_word_id, last_word_id)
);

create trigger relation_evidence_span before insert or update on relation_evidence
    for each row execute function check_span('first_word_id', 'last_word_id');

-- Speech and grammar

create table speech_mode (
    slug text primary key,
    name text not null
);

create table speech (
    id bigint generated always as identity primary key,
    parent_id bigint references speech,
    speaker_id bigint not null references entity,
    mode text not null references speech_mode,
    first_word_id bigint not null references word,
    last_word_id bigint not null references word,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on speech (parent_id);
create index on speech (speaker_id);
create index on speech (first_word_id);
create trigger speech_span before insert or update on speech
    for each row execute function check_span('first_word_id', 'last_word_id');

create table speech_addressee (
    speech_id bigint not null references speech,
    entity_id bigint not null references entity,
    primary key (speech_id, entity_id)
);

create index on speech_addressee (entity_id);

create table sentence (
    id bigint generated always as identity primary key,
    first_word_id bigint not null references word,
    last_word_id bigint not null references word,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on sentence (first_word_id);
create trigger sentence_span before insert or update on sentence
    for each row execute function check_span('first_word_id', 'last_word_id');

create table clause (
    id bigint generated always as identity primary key,
    sentence_id bigint not null references sentence,
    parent_id bigint references clause,
    first_word_id bigint not null references word,
    last_word_id bigint not null references word,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on clause (sentence_id);
create index on clause (parent_id);
create trigger clause_span before insert or update on clause
    for each row execute function check_span('first_word_id', 'last_word_id');

create table clause_role (
    slug text primary key,
    name text not null
);

create table clause_part (
    id bigint generated always as identity primary key,
    clause_id bigint not null references clause,
    role text not null references clause_role,
    first_word_id bigint not null references word,
    last_word_id bigint not null references word,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on clause_part (clause_id);
create trigger clause_part_span before insert or update on clause_part
    for each row execute function check_span('first_word_id', 'last_word_id');

-- Literary structure

create table structure_kind (
    slug text primary key,
    name text not null
);

create table structure (
    id bigint generated always as identity primary key,
    kind text not null references structure_kind,
    first_word_id bigint not null references word,
    last_word_id bigint not null references word,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on structure (first_word_id);
create trigger structure_span before insert or update on structure
    for each row execute function check_span('first_word_id', 'last_word_id');

create table structure_part (
    id bigint generated always as identity primary key,
    structure_id bigint not null references structure,
    parent_id bigint references structure_part,
    seq int not null,
    label text not null,
    pairs_with_id bigint references structure_part,
    first_word_id bigint not null references word,
    last_word_id bigint not null references word,
    unique (structure_id, parent_id, seq)
);

create trigger structure_part_span before insert or update on structure_part
    for each row execute function check_span('first_word_id', 'last_word_id');

-- Passage links

create table link_type (
    slug text primary key,
    name text not null
);

create table passage_link (
    id bigint generated always as identity primary key,
    type text not null references link_type,
    from_first_word_id bigint not null references word,
    from_last_word_id bigint not null references word,
    to_first_word_id bigint not null references word,
    to_last_word_id bigint not null references word,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed'
);

create index on passage_link (from_first_word_id);
create index on passage_link (to_first_word_id);
create trigger passage_link_from_span before insert or update on passage_link
    for each row execute function check_span('from_first_word_id', 'from_last_word_id');
create trigger passage_link_to_span before insert or update on passage_link
    for each row execute function check_span('to_first_word_id', 'to_last_word_id');

-- Time

create table calendar (
    slug text primary key,
    name text not null
);

-- One row per count of time. A date the text gives in two counts is two rows on the same target.
-- 'western' years are astronomical: 1 BC is 0, 2 BC is -1.
create table dating (
    id bigint generated always as identity primary key,
    entity_id bigint references entity,
    relation_id bigint references relation,
    first_word_id bigint references word,
    last_word_id bigint references word,
    calendar text not null references calendar,
    start_year int not null,
    start_month int check (start_month between 1 and 12),
    start_day int check (start_day between 1 and 31),
    end_year int not null,
    end_month int check (end_month between 1 and 12),
    end_day int check (end_day between 1 and 31),
    evidence_first_word_id bigint references word,
    evidence_last_word_id bigint references word,
    source_id bigint not null references source,
    confidence real check (confidence between 0 and 1),
    review_status review_status not null default 'unreviewed',
    check (num_nonnulls(entity_id, relation_id, first_word_id) = 1),
    check ((first_word_id is null) = (last_word_id is null)),
    check ((evidence_first_word_id is null) = (evidence_last_word_id is null)),
    check (end_year >= start_year)
);

create index on dating (entity_id);
create index on dating (relation_id);
create index on dating (first_word_id);
create trigger dating_span before insert or update on dating
    for each row execute function check_span('first_word_id', 'last_word_id');
create trigger dating_evidence_span before insert or update on dating
    for each row execute function check_span('evidence_first_word_id', 'evidence_last_word_id');
