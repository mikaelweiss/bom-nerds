defmodule Corpus.Fixture do
  @moduledoc """
  A small scripture.db shaped like a release, for tests.

  Word ids run backwards so code that confuses ids with sequence fails.

  `database!(path, reader: true)` adds the reader's text and annotations: Luke
  and John in the KJV, Genesis in Hebrew, Luke and John in Greek, the words
  matched between them, and the people, places, speeches, links, and passages
  around them.
  """

  alias Exqlite.Sqlite3

  @schema """
  create table language (id integer primary key, name text not null unique, iso_code text not null unique) strict;
  create table work (id integer primary key, name text not null unique) strict;
  create table edition (
    id integer primary key,
    work_id integer not null references work,
    language_id integer not null default 1 references language,
    name text not null
  ) strict;
  create table book (id integer primary key, work_id integer not null references work, name text not null) strict;
  create table edition_book (
    edition_id integer not null references edition,
    book_id integer not null references book,
    position integer not null,
    primary key (edition_id, book_id)
  ) strict;
  create table chapter (
    id integer primary key,
    edition_id integer not null,
    book_id integer not null,
    number integer not null,
    foreign key (edition_id, book_id) references edition_book
  ) strict;
  create table verse (id integer primary key, chapter_id integer not null references chapter, number integer) strict;
  create table part_of_speech (id integer primary key, name text not null unique) strict;
  create table headword (
    id integer primary key,
    language_id integer not null references language,
    text text not null,
    strongs text,
    gloss text
  ) strict;
  create table meaning (
    id integer primary key,
    headword_id integer not null references headword,
    number integer not null,
    gloss text not null,
    definition text
  ) strict;
  create table word (
    id integer primary key,
    verse_id integer not null references verse,
    position integer not null,
    sequence integer not null unique,
    text text not null,
    before text not null default '',
    after text not null default '',
    supplied integer not null default 0,
    headword_id integer references headword,
    part_of_speech_id integer references part_of_speech,
    meaning_id integer references meaning
  ) strict;
  create table word_match (
    word_id integer not null references word,
    other_word_id integer not null references word,
    primary key (word_id, other_word_id)
  ) strict;
  create table word_type (id integer primary key, name text not null unique) strict;
  create table stem (id integer primary key, name text not null unique) strict;
  create table verb_form (id integer primary key, name text not null unique) strict;
  create table tense (id integer primary key, name text not null unique) strict;
  create table voice (id integer primary key, name text not null unique) strict;
  create table mood (id integer primary key, name text not null unique) strict;
  create table gender (id integer primary key, name text not null unique) strict;
  create table grammatical_number (id integer primary key, name text not null unique) strict;
  create table grammatical_case (id integer primary key, name text not null unique) strict;
  create table state (id integer primary key, name text not null unique) strict;
  create table degree (id integer primary key, name text not null unique) strict;
  create table hebrew_word (
    word_id integer primary key references word,
    word_type_id integer references word_type,
    stem_id integer references stem,
    verb_form_id integer references verb_form,
    person integer,
    gender_id integer references gender,
    grammatical_number_id integer references grammatical_number,
    state_id integer references state
  ) strict;
  create table greek_word (
    word_id integer primary key references word,
    word_type_id integer references word_type,
    tense_id integer references tense,
    second_form integer not null default 0,
    voice_id integer references voice,
    mood_id integer references mood,
    person integer,
    grammatical_case_id integer references grammatical_case,
    gender_id integer references gender,
    grammatical_number_id integer references grammatical_number,
    possessor_number_id integer references grammatical_number,
    degree_id integer references degree,
    indeclinable integer not null default 0,
    crasis integer not null default 0,
    attic_form integer not null default 0,
    transliterated_from_id integer references language
  ) strict;
  create table entity_type (id integer primary key, parent_id integer references entity_type, name text not null unique) strict;
  create table entity (
    id integer primary key,
    entity_type_id integer not null default 1 references entity_type,
    name text not null,
    description text not null default '',
    latitude real,
    longitude real
  ) strict;
  create table entity_name (
    entity_id integer not null references entity,
    name text not null,
    is_title integer not null default 0,
    primary key (entity_id, name)
  ) strict;
  create table mention_kind (id integer primary key, name text not null unique) strict;
  create table mention (
    id integer primary key,
    entity_id integer not null references entity,
    mention_kind_id integer not null references mention_kind,
    first_word_id integer not null references word,
    last_word_id integer not null references word
  ) strict;
  create table speech_mode (id integer primary key, name text not null unique) strict;
  create table speech (
    id integer primary key,
    through_id integer references entity,
    speech_mode_id integer not null default 2 references speech_mode,
    first_word_id integer not null references word,
    last_word_id integer not null references word
  ) strict;
  create table speech_speaker (speech_id integer not null references speech, entity_id integer not null references entity, primary key (speech_id, entity_id)) strict;
  create table speech_listener (speech_id integer not null references speech, entity_id integer not null references entity, primary key (speech_id, entity_id)) strict;
  create table setting (
    id integer primary key,
    place_id integer not null references entity,
    first_word_id integer not null references word,
    last_word_id integer not null references word
  ) strict;
  create table counting_system (id integer primary key, name text not null unique, needs_evidence integer not null) strict;
  create table date (
    id integer primary key,
    first_word_id integer references word,
    last_word_id integer references word,
    entity_id integer references entity,
    counting_system_id integer not null references counting_system,
    from_year integer not null,
    from_month integer,
    from_day integer,
    to_year integer not null,
    to_month integer,
    to_day integer
  ) strict;
  create table link_kind (id integer primary key, name text not null unique, two_way integer not null) strict;
  create table passage_link (
    id integer primary key,
    link_kind_id integer not null default 6 references link_kind,
    from_first_word_id integer not null references word,
    from_last_word_id integer not null references word,
    to_first_word_id integer not null references word,
    to_last_word_id integer not null references word
  ) strict;
  create table structure_kind (id integer primary key, name text not null unique) strict;
  create table structure (
    id integer primary key,
    structure_kind_id integer not null references structure_kind,
    first_word_id integer not null references word,
    last_word_id integer not null references word
  ) strict;
  create table verse_range (
    id integer primary key,
    name text not null unique,
    first_word_id integer not null references word,
    last_word_id integer not null references word
  ) strict;
  create table relationship_kind (
    id integer primary key,
    name text not null unique,
    reverse_name text not null,
    two_way integer not null
  ) strict;
  create table relationship (
    id integer primary key,
    subject_id integer not null references entity,
    relationship_kind_id integer not null references relationship_kind,
    object_id integer not null references entity
  ) strict;
  create table relationship_evidence (
    relationship_id integer not null references relationship,
    first_word_id integer not null references word,
    last_word_id integer not null references word,
    primary key (relationship_id, first_word_id, last_word_id)
  ) strict;
  create table journey (
    id integer primary key,
    traveler_id integer not null references entity,
    from_id integer references entity,
    to_id integer not null references entity,
    days real,
    first_word_id integer not null references word,
    last_word_id integer not null references word
  ) strict;

  insert into language values (1, 'English', 'en'), (2, 'Biblical Hebrew', 'hbo'), (3, 'Koine Greek', 'grc');
  insert into part_of_speech values (1, 'Noun'), (2, 'Proper noun'), (3, 'Verb');
  insert into word_type values (5, 'Common');
  insert into stem values (1, 'Qal');
  insert into verb_form values (1, 'Perfect');
  insert into tense values (4, 'Aorist');
  insert into voice values (1, 'Active');
  insert into mood values (1, 'Indicative');
  insert into gender values (1, 'Masculine'), (2, 'Feminine');
  insert into grammatical_number values (1, 'Singular'), (2, 'Plural');
  insert into grammatical_case values (1, 'Nominative'), (3, 'Dative'), (4, 'Accusative');
  insert into state values (1, 'Absolute');
  insert into degree values (1, 'Comparative');
  insert into entity_type values (1, null, 'Person'), (3, null, 'Place'), (4, 3, 'City');
  insert into mention_kind values (1, 'Refers to'), (2, 'About');
  insert into speech_mode values (1, 'Narration'), (2, 'Spoken');
  insert into counting_system values (4, 'BC/AD', 0);
  insert into link_kind values (1, 'Quotes', 0), (2, 'Parallel', 1), (6, 'Cross-reference', 1);
  insert into structure_kind values (1, 'Chiasm');
  insert into relationship_kind values (1, 'child of', 'parent of', 0);

  insert into work values (1, 'Bible'), (2, 'Book of Mormon');
  insert into edition (id, work_id, name) values (1, 1, 'King James Version (1769)'), (2, 2, 'Book of Mormon (2013)');
  insert into book values (1, 1, 'Genesis'), (2, 2, '1 Nephi');
  insert into edition_book values (1, 1, 1), (2, 2, 1);
  insert into chapter values (1, 1, 1, 1), (2, 1, 1, 2), (3, 2, 2, 3);
  insert into verse values (1, 1, null), (2, 1, 1), (3, 1, 2), (4, 2, 1), (5, 3, 7);
  insert into entity (id, name, description, latitude, longitude) values
    (1, 'Nephi', 'Son of Lehi.', null, null),
    (2, 'Moses', 'Prophet who led Israel out of Egypt.', 31.5, 35.5),
    (3, 'Nephi', 'Son of Helaman.', null, null);
  insert into entity_name (entity_id, name) values (1, 'Nephi'), (2, 'Moses'), (2, 'Moshe');
  """

  @verses [
    {1, "Genesis"},
    {2, "In the beginning."},
    {3, "And the earth was void."},
    {4, "Thus the heavens were finished."},
    {5, "I will go and do."}
  ]

  @reader_text """
  insert into edition (id, work_id, language_id, name) values
    (3, 1, 2, 'Westminster Leningrad Codex'), (4, 1, 3, 'SBL Greek New Testament');
  insert into book values (3, 1, 'Luke'), (4, 1, 'John');
  insert into edition_book values (1, 3, 2), (1, 4, 3), (3, 1, 1), (4, 3, 1), (4, 4, 2);
  insert into chapter values (4, 1, 3, 12), (5, 1, 4, 1), (6, 3, 1, 1), (7, 4, 3, 12), (8, 4, 4, 1);
  insert into verse values (6, 4, 11), (7, 5, 1), (8, 6, 1), (9, 7, 11), (10, 8, 1);
  """

  # A "+" joins two words with no space, as Hebrew prefixes are written.
  @reader_verses [
    {6, "And unto magistrates."},
    {7, "In the beginning was the Word."},
    {8, "בְּ+רֵאשִׁית בָּרָא"},
    {9, "καὶ τὰς ἀρχὰς"},
    {10, "Ἐν ἀρχῇ ἦν ὁ λόγος,"}
  ]

  @doc "Word id of the word at `sequence`."
  def word(sequence), do: 1000 - sequence

  @doc """
  Sequences of the reader's words: `:magistrates` (Luke 12:11), `:the` and
  `:beginning` (John 1:1), `:reshit` (Hebrew Genesis 1:1), `:archas` and
  `:arche` (Greek Luke 12:11 and John 1:1), and `:logos`.
  """
  def sequence(:magistrates), do: 22
  def sequence(:the), do: 24
  def sequence(:beginning), do: 25
  def sequence(:word), do: 28
  def sequence(:reshit), do: 30
  def sequence(:archas), do: 34
  def sequence(:arche), do: 36
  def sequence(:logos), do: 39

  def database!(path, opts \\ []) do
    File.rm(path)
    {:ok, db} = Sqlite3.open(path)
    :ok = Sqlite3.execute(db, @schema)
    if opts[:reader], do: :ok = Sqlite3.execute(db, @reader_text)

    words =
      for {verse_id, text} <- @verses,
          {word, position} <- Enum.with_index(String.split(text), 1) do
        {verse_id, position, word}
      end

    words = if opts[:reader], do: words ++ reader_words(), else: words

    for {{verse_id, position, text}, sequence} <- Enum.with_index(words, 1) do
      {text, trailing} = split_punctuation(text)

      :ok =
        Sqlite3.execute(
          db,
          "insert into word (id, verse_id, position, sequence, text, before, after) " <>
            "values (#{word(sequence)}, #{verse_id}, #{position}, #{sequence}, '#{text}', '', '#{trailing}')"
        )
    end

    :ok =
      Sqlite3.execute(db, """
      insert into speech (id, through_id, first_word_id, last_word_id) values (1, 1, #{word(2)}, #{word(8)}), (2, null, #{word(18)}, #{word(19)});
      insert into passage_link (id, from_first_word_id, from_last_word_id, to_first_word_id, to_last_word_id) values (1, #{word(2)}, #{word(4)}, #{word(18)}, #{word(19)});
      """)

    if opts[:reader], do: :ok = Sqlite3.execute(db, reader_rows())

    :ok = Sqlite3.close(db)
    path
  end

  # Base words keep punctuation in their text. The reader's words carry it in
  # `after`, as a release does.
  defp split_punctuation({text, trailing}), do: {text, trailing}
  defp split_punctuation(text), do: {text, " "}

  defp reader_words do
    for {verse_id, text} <- @reader_verses,
        {word, position} <- Enum.with_index(reader_tokens(text), 1) do
      {verse_id, position, word}
    end
  end

  defp reader_tokens(text) do
    text
    |> String.split(" ")
    |> Enum.flat_map(fn token ->
      [last | joined] = token |> String.split("+") |> Enum.reverse()
      [_, word, punctuation] = Regex.run(~r/^(.+?)([.,]*)$/u, last)
      Enum.reverse([{word, punctuation <> " "} | Enum.map(joined, &{&1, ""})])
    end)
  end

  defp reader_rows do
    w = &word(sequence(&1))

    """
    update word set supplied = 1 where sequence = 8;

    insert into headword values
      (1, 1, 'beginning', null, null), (2, 3, 'ἀρχή', 'G0746', 'beginning'),
      (3, 2, 'רֵאשִׁית', 'H7225', 'beginning'), (4, 1, 'magistrate', null, null),
      (5, 3, 'λόγος', 'G3056', 'word');
    insert into meaning values
      (1, 1, 1, 'That which is first', 'That which is first; the first state; commencement.'),
      (2, 4, 1, 'A public civil officer', 'A public civil officer, invested with the executive government.');
    update word set headword_id = 1, meaning_id = 1, part_of_speech_id = 1 where sequence in (4, #{sequence(:beginning)});
    update word set headword_id = 4, meaning_id = 2, part_of_speech_id = 1 where sequence = #{sequence(:magistrates)};
    update word set headword_id = 3, part_of_speech_id = 1 where sequence = #{sequence(:reshit)};
    update word set headword_id = 2, part_of_speech_id = 1 where sequence in (#{sequence(:archas)}, #{sequence(:arche)});
    update word set headword_id = 5, part_of_speech_id = 1 where sequence = #{sequence(:logos)};
    insert into hebrew_word (word_id, word_type_id, gender_id, grammatical_number_id, state_id) values
      (#{w.(:reshit)}, 5, 2, 1, 1);
    insert into greek_word (word_id, grammatical_case_id, gender_id, grammatical_number_id) values
      (#{w.(:archas)}, 4, 2, 2), (#{w.(:arche)}, 3, 2, 1), (#{w.(:logos)}, 1, 1, 1);
    insert into word_match values
      (#{word(4)}, #{w.(:reshit)}),
      (#{w.(:the)}, #{w.(:arche)}), (#{w.(:beginning)}, #{w.(:arche)}),
      (#{w.(:magistrates)}, #{w.(:archas)}), (#{w.(:word)}, #{w.(:logos)});

    insert into entity (id, entity_type_id, name, description, latitude, longitude) values
      (4, 1, 'Lehi', 'Father of Nephi.', null, null),
      (5, 4, 'Jerusalem', 'Capital of Judah.', 31.777, 35.234),
      (6, 1, 'God', 'The Creator.', null, null),
      (7, 1, 'Helaman', 'Nephite chief judge and prophet.', null, null);
    insert into entity_name values
      (1, 'son of Lehi', 1), (3, 'Nephi', 0), (3, 'son of Helaman', 1), (5, 'Salem', 0);
    insert into relationship values (1, 1, 1, 4), (2, 3, 1, 7);
    insert into relationship_evidence values
      (1, #{word(15)}, #{word(19)}), (2, #{w.(:magistrates)}, #{w.(:magistrates)});
    insert into journey values (1, 1, null, 5, 3, #{word(15)}, #{word(19)});
    insert into mention values
      (1, 1, 1, #{word(15)}, #{word(15)}),
      (2, 3, 1, #{w.(:magistrates)}, #{w.(:magistrates)}),
      (3, 2, 2, #{word(2)}, #{word(9)}),
      (4, 6, 1, #{w.(:word)}, #{w.(:word)});
    insert into speech_speaker values (1, 6), (2, 1);
    insert into speech_listener values (1, 2), (2, 4);
    insert into setting values (1, 5, #{word(15)}, #{word(19)}), (2, 5, #{word(3)}, #{word(9)});
    insert into date (id, first_word_id, last_word_id, counting_system_id, from_year, to_year) values
      (1, #{word(15)}, #{word(19)}, 4, -600, -592);
    insert into passage_link values (2, 2, #{word(3)}, #{word(6)}, #{word(10)}, #{word(14)});
    insert into structure values (1, 1, #{word(2)}, #{word(9)});
    insert into verse_range values (1, 'The Creation', #{word(2)}, #{word(14)});
    """
  end

  def zip!(database_path) do
    {:ok, {_name, zip}} =
      :zip.create(~c"scripture-db.zip", [{~c"scripture.db", File.read!(database_path)}], [:memory])

    zip
  end

  @doc """
  Makes `tag` GitHub's latest release, holding `zip`. Each download sends
  `{:downloaded, tag}` to the process that downloads.
  """
  def publish(tag, zip) do
    Req.Test.stub(Corpus.GitHub, fn
      %{request_path: "/repos/" <> _} = conn ->
        Req.Test.json(conn, %{
          "tag_name" => tag,
          "published_at" => "2026-10-11T00:00:00Z",
          "html_url" => "https://github.com/releases/#{tag}",
          "assets" => [
            %{
              "name" => "scripture-db.zip",
              "browser_download_url" => "https://github.com/download/#{tag}/scripture-db.zip"
            }
          ]
        })

      conn ->
        send(self(), {:downloaded, tag})
        Plug.Conn.send_resp(conn, 200, zip)
    end)
  end
end
