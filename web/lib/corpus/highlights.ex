defmodule Corpus.Highlights do
  @moduledoc """
  The numbers and findings the landing page shows, computed from the
  installed v1 database and kept in the cache until the next release.

  A number or finding whose data the release lacks is left out, so a page
  never shows a zero for something the release does not contain.
  """

  alias Corpus.{Cache, Database, Query, Scripture}

  @version "v1"

  @counts [
    verses: "select count(*) as n from verse where number is not null",
    words: "select count(*) as n from word",
    headwords: "select count(*) as n from headword",
    relationships: "select count(*) as n from relationship",
    speeches: "select count(*) as n from speech",
    journeys: "select count(*) as n from journey",
    settings: "select count(*) as n from setting",
    dates: "select count(*) as n from date",
    structures: "select count(*) as n from structure",
    summaries: "select count(*) as n from summary"
  ]

  @doc """
  Row counts for scholars. A map holding only the keys the release supports:

    * `:aligned_words` - KJV words aligned to a Hebrew or Greek word
    * `:links` - `[%{kind, count}]` by link kind, largest first, and `:link_total`
    * `:entities` - `[%{type, count, tipnr}]` by top-level type, largest first,
      with `:entity_total` and `:tipnr_total` (entities that carry a STEPBible id)
    * `:counts` - a map of `:verses`, `:words`, `:headwords`, `:relationships`,
      `:speeches`, `:journeys`, `:settings`, `:dates`, `:structures`, and
      `:summaries`, each present only when above zero

  Verses and words are counted across every edition. The map is empty when no
  database is installed.
  """
  def scholars, do: cached(:scholars, %{}, &build_scholars/1)

  @doc """
  Findings from the text, each a map with an `:id`, the numbers that prove it,
  and a `:link` path on this site. Findings whose query returns nothing are
  left out. The list is empty when no database is installed.

    * `:moroni` - `:mentions` of Moroni, son of Mormon, and `:books`
    * `:isaiah` - `:quotes` of Isaiah in the Book of Mormon, `:chapters`
      containing them, and `:books`
    * `:alma` - `:speeches` by Alma the Younger, his top `:listeners`, and `:books`
    * `:lehi` - Lehi's `:children` and `:descendants` within three generations
    * `:beginning` - how the KJV translates Hebrew H7225: `:uses`, `:translations`,
      and the first `:verse`
  """
  def findings, do: cached(:findings, [], &build_findings/1)

  defp cached(name, empty, build) do
    case Database.get(@version) do
      nil ->
        empty

      %{release: %{"tag" => tag}} = database ->
        {_status, value} =
          Cachex.fetch(Cache, {:highlights, tag, name}, fn -> {:commit, build.(database)} end)

        value
    end
  end

  defp build_scholars(database) do
    %{
      aligned_words: aligned_words(database),
      links: links(database),
      entities: entities(database),
      counts: counts(database)
    }
    |> Enum.reject(fn {_key, value} -> value in [nil, [], %{}] end)
    |> Map.new()
    |> add_totals()
  end

  defp aligned_words(database) do
    case rows(database, "select count(*) as n from word_match") do
      [%{"n" => n}] when n > 0 -> n
      _ -> nil
    end
  end

  defp links(database) do
    database
    |> rows("""
    select k.name as kind, count(*) as n
    from passage_link l
    join link_kind k on k.id = l.link_kind_id
    group by k.id
    order by n desc, k.name
    """)
    |> Enum.map(&%{kind: &1["kind"], count: &1["n"]})
  end

  defp entities(database) do
    database
    |> rows("""
    select coalesce(p.name, t.name) as type, count(*) as n, count(e.tipnr) as tipnr
    from entity e
    join entity_type t on t.id = e.entity_type_id
    left join entity_type p on p.id = t.parent_id
    group by 1
    order by n desc, type
    """)
    |> Enum.map(&%{type: &1["type"], count: &1["n"], tipnr: &1["tipnr"]})
  end

  defp counts(database) do
    for {key, sql} <- @counts,
        [%{"n" => n}] <- [rows(database, sql)],
        n > 0,
        into: %{},
        do: {key, n}
  end

  defp add_totals(scholars) do
    scholars
    |> put_total(:links, :link_total, & &1.count)
    |> put_total(:entities, :entity_total, & &1.count)
    |> put_total(:entities, :tipnr_total, & &1.tipnr)
  end

  defp put_total(scholars, list_key, total_key, value) do
    case scholars do
      %{^list_key => list} -> Map.put(scholars, total_key, list |> Enum.map(value) |> Enum.sum())
      _ -> scholars
    end
  end

  defp build_findings(database) do
    Enum.reject(
      [moroni(database), isaiah(database), alma(database), lehi(database), beginning(database)],
      &is_nil/1
    )
  end

  defp moroni(database) do
    case rows(database, """
         select m.entity_id as entity_id, b.name as book, count(*) as mentions
         from mention m
         join mention_kind k on k.id = m.mention_kind_id
         join word w on w.id = m.first_word_id
         join verse v on v.id = w.verse_id
         join chapter c on c.id = v.chapter_id
         join book b on b.id = c.book_id
         where k.name = 'Refers to'
           and m.entity_id = (
             select id from entity
             where name = 'Moroni' and description like 'Son of Mormon%'
             order by id limit 1)
         group by b.id
         order by min(w.sequence)
         """) do
      [] ->
        nil

      [%{"entity_id" => id} | _] = rows ->
        %{
          id: :moroni,
          entity_id: id,
          mentions: sum(rows, "mentions"),
          books: Enum.map(rows, &%{book: &1["book"], mentions: &1["mentions"]}),
          link: "/entities/#{id}"
        }
    end
  end

  defp isaiah(database) do
    case rows(database, """
         select fb.name as book, count(*) as quotes, count(distinct fc.id) as chapters
         from passage_link l
         join link_kind k on k.id = l.link_kind_id
         join word fw on fw.id = l.from_first_word_id
         join verse fv on fv.id = fw.verse_id
         join chapter fc on fc.id = fv.chapter_id
         join book fb on fb.id = fc.book_id
         join edition fe on fe.id = fc.edition_id
         join word tw on tw.id = l.to_first_word_id
         join verse tv on tv.id = tw.verse_id
         join chapter tc on tc.id = tv.chapter_id
         join book tb on tb.id = tc.book_id
         where k.name = 'Quotes' and fe.name = 'Book of Mormon (2013)' and tb.name = 'Isaiah'
         group by fb.id
         order by min(fw.sequence)
         """) do
      [] ->
        nil

      rows ->
        %{
          id: :isaiah,
          quotes: sum(rows, "quotes"),
          chapters: sum(rows, "chapters"),
          books: Enum.map(rows, &%{book: &1["book"], quotes: &1["quotes"]}),
          link: "/examples/isaiah"
        }
    end
  end

  defp alma(database) do
    with [%{"id" => id, "speeches" => speeches}] <- rows(database, alma_sql()),
         [_ | _] = listeners <- rows(database, alma_listeners_sql(id)),
         [_ | _] = books <- rows(database, alma_books_sql(id)) do
      %{
        id: :alma,
        entity_id: id,
        speeches: speeches,
        listeners:
          Enum.map(listeners, &%{entity_id: &1["id"], name: &1["name"], speeches: &1["speeches"]}),
        books: Enum.map(books, &%{book: &1["book"], speeches: &1["speeches"]}),
        link: "/entities/#{id}"
      }
    else
      _ -> nil
    end
  end

  defp alma_sql do
    """
    select ss.entity_id as id, count(distinct ss.speech_id) as speeches
    from speech_speaker ss
    join entity e on e.id = ss.entity_id
    where e.name = 'Alma'
    group by ss.entity_id
    order by speeches desc, ss.entity_id
    limit 1
    """
  end

  defp alma_listeners_sql(id) do
    """
    select li.id as id, li.name as name, count(distinct ss.speech_id) as speeches
    from speech_speaker ss
    join speech_listener sl on sl.speech_id = ss.speech_id
    join entity li on li.id = sl.entity_id
    where ss.entity_id = #{id}
    group by li.id
    order by speeches desc, li.name, li.id
    limit 3
    """
  end

  defp alma_books_sql(id) do
    """
    select b.name as book, count(*) as speeches
    from speech_speaker ss
    join speech s on s.id = ss.speech_id
    join word w on w.id = s.first_word_id
    join verse v on v.id = w.verse_id
    join chapter c on c.id = v.chapter_id
    join book b on b.id = c.book_id
    where ss.entity_id = #{id}
    group by b.id
    order by min(w.sequence)
    """
  end

  defp lehi(database) do
    case rows(database, """
         with recursive family(id, generation) as (
           select id, 0 from entity where name = 'Lehi' and description like '%father of Nephi%'
           union
           select r.subject_id, f.generation + 1
           from relationship r
           join relationship_kind k on k.id = r.relationship_kind_id and k.name = 'child of'
           join family f on f.id = r.object_id
           where f.generation < 3
         )
         select f.generation as generation, e.id as id, e.name as name, t.name as type
         from family f
         join entity e on e.id = f.id
         join entity_type t on t.id = e.entity_type_id
         order by f.generation, e.id
         """) do
      [%{"generation" => 0, "id" => id} | family] ->
        people = Enum.filter(family, &(&1["type"] == "Person"))
        children = Enum.filter(people, &(&1["generation"] == 1))

        if children == [] do
          nil
        else
          %{
            id: :lehi,
            entity_id: id,
            children: Enum.map(children, &%{entity_id: &1["id"], name: &1["name"]}),
            descendants: people |> Enum.uniq_by(& &1["id"]) |> length(),
            link: "/entities/#{id}"
          }
        end

      _ ->
        nil
    end
  end

  defp beginning(database) do
    with [_ | _] = translations <- rows(database, beginning_sql()),
         [first] <- rows(database, beginning_first_sql()) do
      %{
        id: :beginning,
        strongs: "H7225",
        hebrew: first["hebrew"],
        gloss: first["gloss"],
        uses: sum(translations, "uses"),
        translations: Enum.map(translations, &%{english: &1["english"], uses: &1["uses"]}),
        verse: %{book: first["book"], chapter: first["chapter"], verse: first["verse"]},
        link: reader_path("kjv", first["book"], first["chapter"], first["verse"])
      }
    else
      _ -> nil
    end
  end

  defp beginning_sql do
    """
    select lower(kjv.text) as english, count(*) as uses
    from headword h
    join word heb on heb.headword_id = h.id
    join word_match m on m.other_word_id = heb.id
    join word kjv on kjv.id = m.word_id
    join verse v on v.id = kjv.verse_id
    join chapter c on c.id = v.chapter_id
    join edition e on e.id = c.edition_id
    where h.strongs = 'H7225' and e.name = 'King James Version (1769)'
    group by 1
    order by uses desc, english
    """
  end

  defp beginning_first_sql do
    """
    select b.name as book, c.number as chapter, v.number as verse, h.text as hebrew, h.gloss as gloss
    from headword h
    join word heb on heb.headword_id = h.id
    join word_match m on m.other_word_id = heb.id
    join word kjv on kjv.id = m.word_id
    join verse v on v.id = kjv.verse_id
    join chapter c on c.id = v.chapter_id
    join book b on b.id = c.book_id
    join edition e on e.id = c.edition_id
    where h.strongs = 'H7225' and e.name = 'King James Version (1769)'
    order by kjv.sequence
    limit 1
    """
  end

  defp reader_path(edition, book, chapter, verse),
    do: "/read/#{edition}/#{Scripture.book_slug(book)}/#{chapter}?v=#{verse}"

  defp sum(rows, key), do: rows |> Enum.map(& &1[key]) |> Enum.sum()

  defp rows(database, sql) do
    case Query.run(database, sql) do
      {:ok, %{rows: rows}} -> rows
      _ -> []
    end
  end
end
