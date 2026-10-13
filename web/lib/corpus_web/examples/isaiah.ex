defmodule CorpusWeb.Examples.Isaiah do
  @behaviour CorpusWeb.Examples

  use Phoenix.Component

  import CorpusWeb.Examples, only: [scale: 3, px: 1]

  @width 800
  @height 420
  @side 40
  @top 70
  @bottom 350

  def slug, do: "isaiah"
  def title, do: "Isaiah in the Book of Mormon"

  def description,
    do:
      "Each line joins a passage of the Book of Mormon, along the top in reading order, to the chapter of Isaiah it quotes, along the bottom."

  def sql do
    """
    with bom as (
      select min(w.sequence) as first, max(w.sequence) as last
      from word w
      join verse v on v.id = w.verse_id
      join chapter c on c.id = v.chapter_id
      join edition e on e.id = c.edition_id
      where e.name = 'Book of Mormon (2013)'
    )
    select fb.name as book, fb.name || ' ' || fc.number as quoting,
           'Isaiah ' || tc.number || ':' || tv.number as quoted,
           1.0 * (fw.sequence - bom.first) / (bom.last - bom.first) as quoting_at,
           tc.number + 1.0 * tv.number / (select max(number) from verse where chapter_id = tc.id) as quoted_at
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
    cross join bom
    where k.name = 'Quotes' and fe.name = 'Book of Mormon (2013)' and tb.name = 'Isaiah'
    order by fw.sequence
    """
  end

  attr :rows, :list, required: true
  attr :preview, :boolean, default: false

  def chart(assigns) do
    top_x = &px(scale(&1, {0, 1}, {@side, @width - @side}))
    bottom_x = &px(scale(&1, {1, 67}, {@side, @width - @side}))
    middle = (@top + @bottom) / 2

    links =
      for row <- assigns.rows do
        x1 = top_x.(row["quoting_at"])
        x2 = bottom_x.(row["quoted_at"])

        %{
          title: "#{row["quoting"]} quotes #{row["quoted"]}",
          path: "M#{x1},#{@top} C#{x1},#{middle} #{x2},#{middle} #{x2},#{@bottom}"
        }
      end

    books =
      assigns.rows
      |> Enum.uniq_by(& &1["book"])
      |> Enum.map(&%{name: &1["book"], x: top_x.(&1["quoting_at"])})

    chapters =
      for chapter <- [1, 10, 20, 30, 40, 50, 60, 66],
          do: %{number: chapter, x: bottom_x.(chapter)}

    assigns =
      assign(assigns,
        links: links,
        books: books,
        chapters: chapters,
        width: @width,
        height: @height,
        side: @side,
        top: @top,
        bottom: @bottom
      )

    ~H"""
    <svg
      viewBox={"0 0 #{@width} #{@height}"}
      class="w-full"
      role="img"
      aria-label="Isaiah in the Book of Mormon"
    >
      <line
        x1={@side}
        x2={@width - @side}
        y1={@top}
        y2={@top}
        class="stroke-chart-2"
        stroke-width="4"
        stroke-linecap="round"
      />
      <line
        x1={@side}
        x2={@width - @side}
        y1={@bottom}
        y2={@bottom}
        class="stroke-chart-1"
        stroke-width="4"
        stroke-linecap="round"
      />
      <path
        :for={link <- @links}
        d={link.path}
        fill="none"
        class="stroke-foreground"
        stroke-opacity="0.3"
        stroke-width="1.5"
      >
        <title>{link.title}</title>
      </path>
      <g :if={!@preview} font-size="12" class="fill-foreground">
        <text x={@side} y="24" font-weight="600">Book of Mormon</text>
        <text :for={book <- @books} x={book.x} y={@top - 12} text-anchor="middle">{book.name}</text>
        <text x={@side} y={@height - 10} font-weight="600">Isaiah</text>
        <text
          :for={chapter <- @chapters}
          x={chapter.x}
          y={@bottom + 22}
          text-anchor="middle"
          class="fill-muted-foreground"
        >
          {chapter.number}
        </text>
      </g>
    </svg>
    """
  end
end
