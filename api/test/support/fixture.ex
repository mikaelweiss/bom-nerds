defmodule Corpus.Fixture do
  @moduledoc """
  A small scripture.db with the core tables, for tests.

  Word ids run backwards so code that confuses ids with sequence fails.
  """

  alias Exqlite.Sqlite3

  @schema """
  create table work (id integer primary key, name text not null unique) strict;
  create table edition (id integer primary key, work_id integer not null references work, name text not null) strict;
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
  create table word (
    id integer primary key,
    verse_id integer not null references verse,
    position integer not null,
    sequence integer not null unique,
    text text not null,
    before text not null default '',
    after text not null default ''
  ) strict;
  create table entity (id integer primary key, name text not null, latitude real) strict;
  create table entity_name (entity_id integer not null references entity, name text not null, primary key (entity_id, name)) strict;
  create table speech (
    id integer primary key,
    through_id integer references entity,
    first_word_id integer not null references word,
    last_word_id integer not null references word
  ) strict;
  create table passage_link (
    id integer primary key,
    from_first_word_id integer not null references word,
    from_last_word_id integer not null references word,
    to_first_word_id integer not null references word,
    to_last_word_id integer not null references word
  ) strict;

  insert into work values (1, 'Bible'), (2, 'Book of Mormon');
  insert into edition values (1, 1, 'King James Version (1769)'), (2, 2, 'Book of Mormon (2013)');
  insert into book values (1, 1, 'Genesis'), (2, 2, '1 Nephi');
  insert into edition_book values (1, 1, 1), (2, 2, 1);
  insert into chapter values (1, 1, 1, 1), (2, 1, 1, 2), (3, 2, 2, 3);
  insert into verse values (1, 1, null), (2, 1, 1), (3, 1, 2), (4, 2, 1), (5, 3, 7);
  insert into entity values (1, 'Nephi', null), (2, 'Moses', 31.5), (3, 'Nephi', null);
  insert into entity_name values (1, 'Nephi'), (2, 'Moses'), (2, 'Moshe');
  """

  @verses [
    {1, "Genesis"},
    {2, "In the beginning."},
    {3, "And the earth was void."},
    {4, "Thus the heavens were finished."},
    {5, "I will go and do."}
  ]

  @doc "Word id of the word at `sequence`."
  def word(sequence), do: 1000 - sequence

  def database!(path) do
    File.rm(path)
    {:ok, db} = Sqlite3.open(path)
    :ok = Sqlite3.execute(db, @schema)

    words =
      for {verse_id, text} <- @verses,
          {word, position} <- Enum.with_index(String.split(text), 1) do
        {verse_id, position, word}
      end

    for {{verse_id, position, text}, sequence} <- Enum.with_index(words, 1) do
      :ok =
        Sqlite3.execute(
          db,
          "insert into word values (#{word(sequence)}, #{verse_id}, #{position}, #{sequence}, '#{text}', '', ' ')"
        )
    end

    :ok =
      Sqlite3.execute(db, """
      insert into speech values (1, 1, #{word(2)}, #{word(8)}), (2, null, #{word(18)}, #{word(19)});
      insert into passage_link values (1, #{word(2)}, #{word(4)}, #{word(18)}, #{word(19)});
      """)

    :ok = Sqlite3.close(db)
    path
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
