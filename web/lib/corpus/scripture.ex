defmodule Corpus.Scripture do
  @moduledoc """
  The reader's queries: the editions and their books, a chapter's text, and
  everything the data knows about a verse, a word, or an entity.

  The reader is written against v1's tables, so it reads v1 whatever the latest
  API version is. With no release installed, `available?/0` is false, lists are
  empty, and lookups return nil.

  A place in the text is a location map: `edition` and `book` slugs, the
  `book_name`, `chapter`, and `verse` (nil for a chapter heading). A word range
  is a map of its `first` and `last` locations and its `reference`.
  """

  alias Corpus.{Database, Spans}

  @version "v1"

  @edition_slugs %{
    "King James Version (1769)" => "kjv",
    "Westminster Leningrad Codex" => "wlc",
    "SBL Greek New Testament" => "sblgnt"
  }

  @right_to_left ~w(hbo arc)

  @reverse_links %{
    "Quotes" => "Quoted in",
    "Alludes to" => "Alluded to in",
    "Fulfills" => "Fulfilled in"
  }

  @excerpt_words 60

  @preloaded_verses 300

  @months ~w(January February March April May June July August September October November December)

  def available?, do: database() != nil

  @doc """
  Every edition in reading order, each with its books in canonical order and
  each book with its chapters: `%{id, name, slug, work, language, rtl, books:
  [%{id, name, slug, chapters: [%{id, number}]}]}`. `language` is the ISO
  code of the edition's language.
  """
  def editions do
    case database() do
      nil -> []
      db -> cached(db, :editions, fn -> load_editions(db) end)
    end
  end

  @doc "The edition with `slug`, or nil."
  def edition(slug), do: Enum.find(editions(), &(&1.slug == slug))

  @doc ~S|The reader's address segment for an edition name, like "kjv" or "book-of-mormon".|
  def edition_slug(name) do
    Map.get_lazy(@edition_slugs, name, fn ->
      name |> String.replace(~r/\s*\(.*\)/, "") |> slugify()
    end)
  end

  @doc ~S|The reader's address segment for a book name, like "1-nephi".|
  def book_slug(name), do: slugify(name)

  defp slugify(text) do
    text
    |> :unicode.characters_to_nfd_binary()
    |> String.downcase()
    |> String.replace(~r/[^a-z0-9]+/, "-")
    |> String.trim("-")
  end

  @doc """
  The chapter at `edition_slug`, `book_slug`, `number`, or nil when there is
  none. Holds the `edition`, `book`, `number`, an optional `heading` verse, the
  numbered `verses`, and the `previous` and `next` chapters as locations. A
  verse is `%{id, number, words}` and a word is `%{id, position, before, text,
  after, supplied}`.
  """
  def chapter(edition_slug, book_slug, number) do
    with db when db != nil <- database(),
         %{} = edition <- edition(edition_slug),
         %{} = book <- Enum.find(edition.books, &(&1.slug == book_slug)),
         %{} = chapter <- Enum.find(book.chapters, &(&1.number == number)) do
      {heading, verses} =
        db
        |> verses(chapter.id)
        |> Enum.split_with(&is_nil(&1.number))

      {previous, next} = neighbors(edition, chapter)

      %{
        id: chapter.id,
        edition: Map.delete(edition, :books),
        book: Map.delete(book, :chapters),
        number: number,
        heading: List.first(heading),
        verses: verses,
        previous: previous,
        next: next
      }
    else
      _ -> nil
    end
  end

  @doc """
  One verse with its words, in the shape `chapter/3` gives, plus its
  `location`, `language`, and `rtl`. Nil when it does not exist.
  """
  def find_verse(edition_slug, book_slug, chapter, verse) do
    with %{} = found <- chapter(edition_slug, book_slug, chapter),
         %{} = match <- Enum.find(found.verses, &(&1.number == verse)) do
      Map.merge(match, %{
        location: %{
          edition: found.edition.slug,
          book: found.book.slug,
          book_name: found.book.name,
          chapter: found.number,
          verse: verse
        },
        language: found.edition.language,
        rtl: found.edition.rtl
      })
    end
  end

  @doc """
  Everything known about the verse `verse_id`: its `location` and
  `reference`, `speeches`, `settings`, `dates`, `named` and `about` entities,
  passage `links`, `structures`, and named `passages`. Nil when it does not
  exist.
  """
  def verse(verse_id) do
    with db when db != nil <- database(),
         %{lo: lo} = verse when lo != nil <- locate_verse(db, verse_id) do
      bounds = [verse.lo, verse.hi]
      {named, about} = verse_mentions(db, bounds)

      details = %{
        id: verse.id,
        speeches: speeches(db, bounds),
        settings: settings(db, bounds),
        dates: dates(db, bounds),
        named: named,
        about: about,
        links: links(db, bounds),
        structures: structures(db, bounds),
        passages: passages(db, bounds)
      }

      location = location(verse)

      details
      |> with_ranges(db)
      |> Map.merge(%{location: location, reference: reference(location, location)})
    else
      _ -> nil
    end
  end

  @doc """
  Everything known about the word `word_id`: its text, `language`, `rtl`,
  `location`, `headword`, `meaning`, `part_of_speech`, `grammar`, the
  `originals` it translates, English `parallels`, and the entities it
  `refers_to`. An original word also has its KJV `translations` in this verse
  (`%{text, location, position}`, or nil) and the KJV `renderings` of its
  headword. Nil when the word does not exist.
  """
  def word(word_id) do
    with db when db != nil <- database(),
         %{} = word <- load_word(db, word_id) do
      original? = word.language != "en"
      grammar = grammar(db, [word.id])

      %{
        id: word.id,
        text: word.text,
        supplied: word.supplied == 1,
        verse_id: word.verse_id,
        position: word.position,
        language: word.language,
        rtl: word.language in @right_to_left,
        location: location(word),
        headword: headword(word),
        meaning: word.meaning && %{gloss: word.meaning, definition: word.definition},
        part_of_speech: word.part_of_speech,
        grammar: Map.get(grammar, word.id, []),
        originals: if(original?, do: [], else: originals(db, word.id)),
        parallels: if(original?, do: [], else: parallels(db, word.id)),
        translations: if(original?, do: translations(db, word.id), else: nil),
        renderings: if(original?, do: renderings(db, word.headword_id), else: []),
        refers_to: refers_to(db, word.sequence)
      }
    else
      _ -> nil
    end
  end

  @doc """
  Everything known about the entity `id`: `name`, `description`, `type`,
  `latitude` and `longitude`, other `names`, `relationships` both ways,
  `journeys`, the books it is `named` in, and the passages `about` it. Books
  list their verses when the entity is named in few enough of them; otherwise
  `entity_verses/3` loads one book's verses. Nil when it does not exist.
  """
  def entity(id) do
    with db when db != nil <- database(),
         %{} = entity <- load_entity(db, id) do
      named = named_books(db, id)
      preload? = Enum.sum_by(named, & &1.count) <= @preloaded_verses

      named =
        if preload?,
          do: fill_verses(named, db |> named_verses(id, nil) |> Enum.group_by(&book_key/1)),
          else: named

      Map.merge(entity, %{
        names: other_names(db, id, entity.name),
        relationships: relationships(db, id),
        journeys: journeys(db, id),
        named: named,
        about: about_books(db, id)
      })
    else
      _ -> nil
    end
  end

  @doc "The verses of one book that name the entity `id`, as locations."
  def entity_verses(id, edition_id, book_id) do
    case database() do
      nil -> []
      db -> db |> named_verses(id, {edition_id, book_id}) |> Enum.map(&location/1)
    end
  end

  @doc "A reference such as `Alma 32:21`, `Alma 32:21-23`, or `Alma 32:21-33:2`."
  def reference(%{} = first, %{} = last) do
    cond do
      first.book_name != last.book_name ->
        "#{point(first)}-#{point(last)}"

      first.chapter != last.chapter ->
        "#{point(first)}-#{verse_label(last)}"

      first.verse != last.verse ->
        "#{point(first)}-#{last.verse}"

      true ->
        point(first)
    end
  end

  def reference(%{} = location), do: reference(location, location)

  defp point(location), do: "#{location.book_name} #{verse_label(location)}"

  defp verse_label(%{chapter: chapter, verse: nil}), do: "#{chapter}"
  defp verse_label(%{chapter: chapter, verse: verse}), do: "#{chapter}:#{verse}"

  defp database, do: Database.get(@version)

  # Rows carry edition ids. This small map keeps a lookup per row from copying
  # every edition's books out of the cache.
  defp edition_summary(id) do
    summaries =
      cached(database(), :edition_summaries, fn ->
        Map.new(editions(), &{&1.id, Map.take(&1, [:slug, :name])})
      end)

    Map.fetch!(summaries, id)
  end

  defp cached(%{release: %{"tag" => tag}}, key, load) do
    {_status, value} =
      Cachex.fetch(Corpus.Cache, {:scripture, tag, key}, fn -> {:commit, load.()} end)

    value
  end

  defp all(%{pool: pool}, sql, params \\ []) do
    %{columns: columns, rows: rows} = Exqlite.query!(pool, sql, params)
    keys = Enum.map(columns, &String.to_atom/1)
    Enum.map(rows, &(keys |> Enum.zip(&1) |> Map.new()))
  end

  defp one(db, sql, params), do: db |> all(sql, params) |> List.first()

  defp load_editions(db) do
    db
    |> all("""
    select e.id as edition_id, e.name as edition, wk.name as work, l.iso_code as language,
           b.id as book_id, b.name as book, c.id as chapter_id, c.number as chapter
    from edition e
    join work wk on wk.id = e.work_id
    join language l on l.id = e.language_id
    join edition_book eb on eb.edition_id = e.id
    join book b on b.id = eb.book_id
    join chapter c on c.edition_id = e.id and c.book_id = b.id
    order by e.id, eb.position, c.number
    """)
    |> Enum.chunk_by(& &1.edition_id)
    |> Enum.map(fn [first | _] = rows ->
      %{
        id: first.edition_id,
        name: first.edition,
        slug: edition_slug(first.edition),
        work: first.work,
        language: first.language,
        rtl: first.language in @right_to_left,
        books:
          rows
          |> Enum.chunk_by(& &1.book_id)
          |> Enum.map(fn [book | _] = chapters ->
            %{
              id: book.book_id,
              name: book.book,
              slug: book_slug(book.book),
              chapters: Enum.map(chapters, &%{id: &1.chapter_id, number: &1.chapter})
            }
          end)
      }
    end)
  end

  defp verses(db, chapter_id) do
    db
    |> all(
      """
      select v.id as verse_id, v.number as verse, w.id, w.position, w.before, w.text, w.after, w.supplied
      from verse v
      join word w on w.verse_id = v.id
      where v.chapter_id = ?1
      order by v.number is not null, v.number, w.position
      """,
      [chapter_id]
    )
    |> Enum.chunk_by(& &1.verse_id)
    |> Enum.map(fn [first | _] = words ->
      %{
        id: first.verse_id,
        number: first.verse,
        words:
          Enum.map(words, fn word ->
            word
            |> Map.take([:id, :position, :before, :text, :after])
            |> Map.put(:supplied, word.supplied == 1)
          end)
      }
    end)
  end

  defp neighbors(edition, chapter) do
    chapters =
      for book <- edition.books, chapter <- book.chapters do
        {chapter.id,
         %{
           edition: edition.slug,
           book: book.slug,
           book_name: book.name,
           chapter: chapter.number,
           verse: nil
         }}
      end

    index = Enum.find_index(chapters, fn {id, _} -> id == chapter.id end)
    previous = if index > 0, do: chapters |> Enum.at(index - 1) |> elem(1)
    next = with {_id, location} <- Enum.at(chapters, index + 1), do: location
    {previous, next}
  end

  @locate """
  select w.id as word_id, w.sequence, v.number as verse, c.number as chapter,
         c.edition_id, b.name as book_name
  from word w
  join verse v on v.id = w.verse_id
  join chapter c on c.id = v.chapter_id
  join book b on b.id = c.book_id
  """

  defp locate_verse(db, verse_id) do
    one(
      db,
      """
      select v.id, v.number as verse, c.number as chapter, c.edition_id, b.name as book_name,
             min(w.sequence) as lo, max(w.sequence) as hi
      from verse v
      join chapter c on c.id = v.chapter_id
      join book b on b.id = c.book_id
      join word w on w.verse_id = v.id
      where v.id = ?1
      """,
      [verse_id]
    )
  end

  defp location(row) do
    %{
      edition: edition_summary(row.edition_id).slug,
      book: book_slug(row.book_name),
      book_name: row.book_name,
      chapter: row.chapter,
      verse: row.verse
    }
  end

  # Every row of `table` whose word range overlaps the words ?1 to ?2.
  # ?3 is the longest range in the table, so no overlapping range starts
  # before ?1 - ?3.
  defp overlapping(table, first \\ "first_word_id", last \\ "last_word_id") do
    """
    from word f
    join #{table} t on t.#{first} = f.id
    join word l on l.id = t.#{last}
    """
  end

  @overlaps "f.sequence between ?1 - ?3 and ?2 and l.sequence >= ?1"

  defp window(db, kind, [lo, hi]), do: [lo, hi, Spans.longest(db, kind)]

  defp speeches(db, bounds) do
    speeches =
      all(
        db,
        """
        select t.id, m.name as mode, th.id as through_id, th.name as through,
               t.first_word_id, t.last_word_id
        #{overlapping("speech")}
        join speech_mode m on m.id = t.speech_mode_id
        left join entity th on th.id = t.through_id
        where #{@overlaps}
        order by f.sequence
        """,
        window(db, :speech, bounds)
      )

    ids = Jason.encode!(Enum.map(speeches, & &1.id))
    speakers = speech_people(db, "speech_speaker", ids)
    listeners = speech_people(db, "speech_listener", ids)

    Enum.map(speeches, fn speech ->
      %{
        mode: speech.mode,
        through: speech.through_id && %{id: speech.through_id, name: speech.through},
        speakers: Map.get(speakers, speech.id, []),
        listeners: Map.get(listeners, speech.id, []),
        range: {speech.first_word_id, speech.last_word_id}
      }
    end)
  end

  defp speech_people(db, table, ids) do
    db
    |> all(
      """
      select x.speech_id, e.id, e.name
      from #{table} x
      join entity e on e.id = x.entity_id
      where x.speech_id in (select value from json_each(?1))
      order by e.name
      """,
      [ids]
    )
    |> Enum.group_by(& &1.speech_id, &Map.take(&1, [:id, :name]))
  end

  defp settings(db, bounds) do
    all(
      db,
      """
      select e.id, e.name
      #{overlapping("setting")}
      join entity e on e.id = t.place_id
      where #{@overlaps}
      group by e.id
      order by min(f.sequence)
      """,
      window(db, :setting, bounds)
    )
  end

  defp dates(db, bounds) do
    db
    |> all(
      """
      select cs.name as system, t.from_year, t.from_month, t.from_day,
             t.to_year, t.to_month, t.to_day
      #{overlapping("date")}
      join counting_system cs on cs.id = t.counting_system_id
      where #{@overlaps}
      order by f.sequence
      """,
      window(db, :date, bounds)
    )
    |> Enum.map(&%{text: date_text(&1), system: &1.system})
    |> Enum.uniq()
  end

  defp date_text(date) do
    from = {date.from_year, date.from_month, date.from_day}
    to = {date.to_year, date.to_month, date.to_day}

    case date.system do
      "BC/AD" when from == to ->
        calendar_date(from)

      "BC/AD" when date.from_year < 0 and date.to_year < 0 and date.from_month == nil ->
        "#{-date.from_year} to #{-date.to_year} BC"

      "BC/AD" ->
        "#{calendar_date(from)} to #{calendar_date(to)}"

      _ when from == to ->
        counted_date(from)

      _ ->
        "#{counted_date(from)} to #{counted_date(to)}"
    end
  end

  defp calendar_date({year, month, day}) do
    year = if year < 0, do: "#{-year} BC", else: "AD #{year}"
    month = month && Enum.at(@months, month - 1)
    [day, month, year] |> Enum.reject(&is_nil/1) |> Enum.join(" ")
  end

  defp counted_date({year, month, day}) do
    ["Year #{year}", month && "month #{month}", day && "day #{day}"]
    |> Enum.reject(&is_nil/1)
    |> Enum.join(", ")
  end

  defp verse_mentions(db, bounds) do
    mentions =
      all(
        db,
        """
        select k.name as kind, e.id, e.name, e.description
        #{overlapping("mention")}
        join mention_kind k on k.id = t.mention_kind_id
        join entity e on e.id = t.entity_id
        where #{@overlaps}
        group by k.id, e.id
        order by min(f.sequence)
        """,
        window(db, :mention, bounds)
      )

    {named, about} = Enum.split_with(mentions, &(&1.kind == "Refers to"))
    {Enum.map(named, &Map.delete(&1, :kind)), Enum.map(about, &Map.delete(&1, :kind))}
  end

  defp links(db, [lo, hi]) do
    db
    |> all(
      """
      select t.id, k.name as kind, k.two_way, 'from' as side,
             t.to_first_word_id as first_word_id, t.to_last_word_id as last_word_id,
             o.sequence as other_lo, ol.sequence as other_hi
      #{overlapping("passage_link", "from_first_word_id", "from_last_word_id")}
      join link_kind k on k.id = t.link_kind_id
      join word o on o.id = t.to_first_word_id
      join word ol on ol.id = t.to_last_word_id
      where #{@overlaps}
      union all
      select t.id, k.name, k.two_way, 'to',
             t.from_first_word_id, t.from_last_word_id, o.sequence, ol.sequence
      #{overlapping("passage_link", "to_first_word_id", "to_last_word_id")}
      join link_kind k on k.id = t.link_kind_id
      join word o on o.id = t.from_first_word_id
      join word ol on ol.id = t.from_last_word_id
      where f.sequence between ?1 - ?4 and ?2 and l.sequence >= ?1
      order by 7
      """,
      [lo, hi, Spans.longest(db, :link_from), Spans.longest(db, :link_to)]
    )
    |> Enum.map(fn link ->
      %{
        kind: link_label(link),
        text: excerpt(db, link.other_lo, link.other_hi),
        range: {link.first_word_id, link.last_word_id}
      }
    end)
  end

  defp link_label(%{side: "to", two_way: 0, kind: kind}),
    do: Map.get(@reverse_links, kind, "Linked from")

  defp link_label(%{kind: kind}), do: kind

  # A verse's last word has no trailing space, so verses join with one.
  defp excerpt(db, lo, hi) do
    text =
      db
      |> all(
        """
        select verse_id, before, text, after from word
        where sequence between ?1 and ?2
        order by sequence
        """,
        [lo, min(hi, lo + @excerpt_words - 1)]
      )
      |> Enum.chunk_by(& &1.verse_id)
      |> Enum.map_join(" ", fn words ->
        words |> Enum.map_join(&(&1.before <> &1.text <> &1.after)) |> String.trim()
      end)

    if hi - lo >= @excerpt_words, do: text <> " …", else: text
  end

  defp structures(db, bounds) do
    all(
      db,
      """
      select k.name as kind, t.first_word_id, t.last_word_id
      #{overlapping("structure")}
      join structure_kind k on k.id = t.structure_kind_id
      where #{@overlaps}
      order by f.sequence
      """,
      window(db, :structure, bounds)
    )
    |> Enum.map(&%{kind: &1.kind, range: {&1.first_word_id, &1.last_word_id}})
  end

  defp passages(db, bounds) do
    all(
      db,
      """
      select t.name, t.first_word_id, t.last_word_id
      #{overlapping("verse_range")}
      where #{@overlaps}
      order by f.sequence
      """,
      window(db, :verse_range, bounds)
    )
    |> Enum.map(&%{name: &1.name, range: {&1.first_word_id, &1.last_word_id}})
  end

  # Replaces each `range: {first_word_id, last_word_id}` with a range map,
  # locating every word in one query.
  defp with_ranges(details, db) do
    lists = Map.take(details, [:speeches, :links, :structures, :passages])

    ids =
      for {_key, items} <- lists, %{range: {first, last}} <- items, id <- [first, last], do: id

    locations = locations(db, ids)

    Map.merge(
      details,
      Map.new(lists, fn {key, items} ->
        {key, Enum.map(items, &%{&1 | range: range(locations, &1.range)})}
      end)
    )
  end

  defp locations(_db, []), do: %{}

  defp locations(db, ids) do
    db
    |> all("#{@locate} where w.id in (select value from json_each(?1))", [
      Jason.encode!(Enum.uniq(ids))
    ])
    |> Map.new(&{&1.word_id, location(&1)})
  end

  defp range(locations, {first, last}) do
    first = Map.fetch!(locations, first)
    last = Map.fetch!(locations, last)
    %{first: first, last: last, reference: reference(first, last)}
  end

  defp load_word(db, word_id) do
    one(
      db,
      """
      select w.id, w.text, w.supplied, w.sequence, w.verse_id, w.position,
             v.number as verse, c.number as chapter, c.edition_id, b.name as book_name,
             lg.iso_code as language, h.id as headword_id, h.text as headword, h.strongs,
             h.gloss, m.gloss as meaning, m.definition, p.name as part_of_speech
      from word w
      join verse v on v.id = w.verse_id
      join chapter c on c.id = v.chapter_id
      join book b on b.id = c.book_id
      join edition e on e.id = c.edition_id
      join language lg on lg.id = e.language_id
      left join headword h on h.id = w.headword_id
      left join meaning m on m.id = w.meaning_id
      left join part_of_speech p on p.id = w.part_of_speech_id
      where w.id = ?1
      """,
      [word_id]
    )
  end

  defp headword(%{headword_id: nil}), do: nil

  defp headword(row), do: %{text: row.headword, strongs: row.strongs, gloss: row.gloss}

  defp originals(db, word_id) do
    words =
      all(
        db,
        """
        select o.id, o.text, lg.iso_code as language, h.id as headword_id, h.text as headword,
               h.strongs, h.gloss
        from word_match m
        join word o on o.id = m.other_word_id
        join verse v on v.id = o.verse_id
        join chapter c on c.id = v.chapter_id
        join edition e on e.id = c.edition_id
        join language lg on lg.id = e.language_id
        left join headword h on h.id = o.headword_id
        where m.word_id = ?1 and lg.iso_code <> 'en'
        order by o.sequence
        """,
        [word_id]
      )

    grammar = grammar(db, Enum.map(words, & &1.id))

    Enum.map(words, fn word ->
      %{
        id: word.id,
        text: word.text,
        rtl: word.language in @right_to_left,
        headword: headword(word),
        grammar: Map.get(grammar, word.id, []),
        renderings: renderings(db, word.headword_id)
      }
    end)
  end

  defp parallels(db, word_id) do
    db
    |> all(
      """
      #{@locate}
      join word_match m on w.id = case m.word_id when ?1 then m.other_word_id else m.word_id end
      join edition e on e.id = c.edition_id
      join language lg on lg.id = e.language_id
      where (m.word_id = ?1 or m.other_word_id = ?1) and lg.iso_code = 'en'
      order by w.sequence
      """,
      [word_id]
    )
    |> Enum.map(&location/1)
    |> Enum.uniq()
  end

  defp translations(db, word_id) do
    words =
      all(
        db,
        """
        select k.text, k.position, v.number as verse, c.number as chapter, c.edition_id,
               b.name as book_name
        from word_match m
        join word k on k.id = m.word_id
        join verse v on v.id = k.verse_id
        join chapter c on c.id = v.chapter_id
        join book b on b.id = c.book_id
        where m.other_word_id = ?1
        order by k.sequence
        """,
        [word_id]
      )

    case words do
      [] ->
        nil

      [first | _] ->
        %{
          text: Enum.map_join(words, " ", & &1.text),
          location: location(first),
          position: first.position
        }
    end
  end

  # Words matched to the same original word read as one phrase, so "the
  # beginning" counts once rather than as "the" and "beginning".
  defp renderings(_db, nil), do: []

  defp renderings(db, headword_id) do
    all(
      db,
      """
      select phrase, count(*) as count
      from (
        select group_concat(lower(k.text), ' ' order by k.sequence) as phrase
        from word o
        join word_match m on m.other_word_id = o.id
        join word k on k.id = m.word_id
        where o.headword_id = ?1
        group by o.id
      )
      group by phrase
      order by count desc, phrase
      limit 12
      """,
      [headword_id]
    )
  end

  defp refers_to(db, sequence) do
    all(
      db,
      """
      select e.id, e.name, e.description
      #{overlapping("mention")}
      join mention_kind k on k.id = t.mention_kind_id
      join entity e on e.id = t.entity_id
      where #{@overlaps} and k.name = 'Refers to'
      group by e.id
      order by e.name
      """,
      window(db, :mention, [sequence, sequence])
    )
  end

  defp grammar(_db, []), do: %{}

  defp grammar(db, ids) do
    ids = Jason.encode!(ids)

    hebrew =
      all(
        db,
        """
        select x.word_id, p.name as part_of_speech, wt.name as word_type, st.name as stem,
               vf.name as verb_form, x.person, g.name as gender, n.name as number,
               s.name as state
        from hebrew_word x
        join word w on w.id = x.word_id
        left join part_of_speech p on p.id = w.part_of_speech_id
        left join word_type wt on wt.id = x.word_type_id
        left join stem st on st.id = x.stem_id
        left join verb_form vf on vf.id = x.verb_form_id
        left join gender g on g.id = x.gender_id
        left join grammatical_number n on n.id = x.grammatical_number_id
        left join state s on s.id = x.state_id
        where x.word_id in (select value from json_each(?1))
        """,
        [ids]
      )

    greek =
      all(
        db,
        """
        select x.word_id, p.name as part_of_speech, wt.name as word_type, t.name as tense,
               x.second_form, v.name as voice, m.name as mood, x.person,
               gc.name as grammatical_case, g.name as gender, n.name as number,
               pn.name as possessor, d.name as degree, x.indeclinable, x.crasis, x.attic_form,
               tl.name as transliterated_from
        from greek_word x
        join word w on w.id = x.word_id
        left join part_of_speech p on p.id = w.part_of_speech_id
        left join word_type wt on wt.id = x.word_type_id
        left join tense t on t.id = x.tense_id
        left join voice v on v.id = x.voice_id
        left join mood m on m.id = x.mood_id
        left join grammatical_case gc on gc.id = x.grammatical_case_id
        left join gender g on g.id = x.gender_id
        left join grammatical_number n on n.id = x.grammatical_number_id
        left join grammatical_number pn on pn.id = x.possessor_number_id
        left join degree d on d.id = x.degree_id
        left join language tl on tl.id = x.transliterated_from_id
        where x.word_id in (select value from json_each(?1))
        """,
        [ids]
      )

    Map.new(hebrew ++ greek, &{&1.word_id, grammar_labels(&1)})
  end

  defp grammar_labels(row) do
    [
      row.part_of_speech,
      row.word_type,
      row[:stem],
      row[:verb_form],
      tense(row),
      row[:voice],
      row[:mood],
      row.person && "#{ordinal(row.person)} person",
      row[:grammatical_case],
      row.gender,
      row.number,
      row[:state],
      row[:possessor] && "#{row.possessor} possessor",
      row[:degree],
      row[:indeclinable] == 1 && "Indeclinable",
      row[:crasis] == 1 && "Crasis",
      row[:attic_form] == 1 && "Attic form",
      row[:transliterated_from] && "Transliterated from #{row.transliterated_from}"
    ]
    |> Enum.filter(&is_binary/1)
    |> Enum.uniq()
  end

  defp tense(%{tense: tense, second_form: 1}) when tense != nil,
    do: "Second #{String.downcase(tense)}"

  defp tense(row), do: row[:tense]

  defp ordinal(1), do: "1st"
  defp ordinal(2), do: "2nd"
  defp ordinal(3), do: "3rd"

  defp load_entity(db, id) do
    one(
      db,
      """
      select e.id, e.name, e.description, t.name as type, e.latitude, e.longitude
      from entity e
      join entity_type t on t.id = e.entity_type_id
      where e.id = ?1
      """,
      [id]
    )
  end

  defp other_names(db, id, name) do
    db
    |> all(
      """
      select name, is_title from entity_name
      where entity_id = ?1 and name <> ?2
      order by is_title, name
      """,
      [id, name]
    )
    |> Enum.map(&%{name: &1.name, title: &1.is_title == 1})
  end

  defp relationships(db, id) do
    relationships =
      all(
        db,
        """
        select r.id, k.name as label, o.id as other_id, o.name as other_name,
               o.description as other_description
        from relationship r
        join relationship_kind k on k.id = r.relationship_kind_id
        join entity o on o.id = r.object_id
        where r.subject_id = ?1
        union all
        select r.id, k.reverse_name, s.id, s.name, s.description
        from relationship r
        join relationship_kind k on k.id = r.relationship_kind_id
        join entity s on s.id = r.subject_id
        where r.object_id = ?1
        order by 2, 4
        """,
        [id]
      )

    evidence =
      all(
        db,
        """
        select x.relationship_id, x.first_word_id, x.last_word_id
        from relationship_evidence x
        join word f on f.id = x.first_word_id
        where x.relationship_id in (select value from json_each(?1))
        order by f.sequence
        """,
        [Jason.encode!(Enum.map(relationships, & &1.id))]
      )

    locations = locations(db, Enum.flat_map(evidence, &[&1.first_word_id, &1.last_word_id]))

    evidence =
      Enum.group_by(
        evidence,
        & &1.relationship_id,
        &range(locations, {&1.first_word_id, &1.last_word_id})
      )

    Enum.map(relationships, fn relationship ->
      %{
        label: relationship.label,
        other: %{
          id: relationship.other_id,
          name: relationship.other_name,
          description: relationship.other_description
        },
        evidence: Map.get(evidence, relationship.id, [])
      }
    end)
  end

  defp journeys(db, id) do
    journeys =
      all(
        db,
        """
        select j.traveler_id, t.name as traveler, j.from_id, fr.name as from_name,
               j.to_id, tt.name as to_name, j.days, j.first_word_id, j.last_word_id
        from journey j
        join entity t on t.id = j.traveler_id
        left join entity fr on fr.id = j.from_id
        join entity tt on tt.id = j.to_id
        join word f on f.id = j.first_word_id
        where j.traveler_id = ?1 or j.from_id = ?1 or j.to_id = ?1
        order by f.sequence
        """,
        [id]
      )

    locations = locations(db, Enum.flat_map(journeys, &[&1.first_word_id, &1.last_word_id]))

    Enum.map(journeys, fn journey ->
      %{
        traveler: %{id: journey.traveler_id, name: journey.traveler},
        from: journey.from_id && %{id: journey.from_id, name: journey.from_name},
        to: %{id: journey.to_id, name: journey.to_name},
        days: journey.days,
        range: range(locations, {journey.first_word_id, journey.last_word_id})
      }
    end)
  end

  @named_from """
  from mention m
  join mention_kind k on k.id = m.mention_kind_id and k.name = 'Refers to'
  join word w on w.id = m.first_word_id
  join verse v on v.id = w.verse_id
  join chapter c on c.id = v.chapter_id
  join book b on b.id = c.book_id
  """

  defp named_books(db, id) do
    db
    |> all(
      """
      select c.edition_id, b.id as book_id, b.name as book_name, count(distinct v.id) as count
      #{@named_from}
      where m.entity_id = ?1
      group by c.edition_id, b.id
      order by min(w.sequence)
      """,
      [id]
    )
    |> Enum.map(&book_summary/1)
  end

  defp book_summary(row) do
    %{
      edition_id: row.edition_id,
      edition: edition_summary(row.edition_id).name,
      book_id: row.book_id,
      book_name: row.book_name,
      count: row.count,
      verses: nil
    }
  end

  defp named_verses(db, id, book) do
    {filter, params} =
      case book do
        nil ->
          {"", [id]}

        {edition_id, book_id} ->
          {"and c.edition_id = ?2 and c.book_id = ?3", [id, edition_id, book_id]}
      end

    all(
      db,
      """
      select c.edition_id, b.id as book_id, b.name as book_name, c.number as chapter,
             v.number as verse
      #{@named_from}
      where m.entity_id = ?1 #{filter}
      group by v.id
      order by min(w.sequence)
      """,
      params
    )
  end

  defp book_key(row), do: {row.edition_id, row.book_id}

  defp fill_verses(books, verses) do
    Enum.map(books, fn book ->
      %{book | verses: verses |> Map.get(book_key(book), []) |> Enum.map(&location/1)}
    end)
  end

  defp about_books(db, id) do
    mentions =
      all(
        db,
        """
        select c.edition_id, b.id as book_id, b.name as book_name, m.first_word_id,
               m.last_word_id
        from mention m
        join mention_kind k on k.id = m.mention_kind_id and k.name = 'About'
        join word w on w.id = m.first_word_id
        join verse v on v.id = w.verse_id
        join chapter c on c.id = v.chapter_id
        join book b on b.id = c.book_id
        where m.entity_id = ?1
        order by w.sequence
        """,
        [id]
      )

    locations = locations(db, Enum.flat_map(mentions, &[&1.first_word_id, &1.last_word_id]))

    mentions
    |> Enum.chunk_by(&book_key/1)
    |> Enum.map(fn [first | _] = rows ->
      %{
        book_summary(Map.put(first, :count, length(rows)))
        | verses: Enum.map(rows, &range(locations, {&1.first_word_id, &1.last_word_id}))
      }
    end)
  end
end
