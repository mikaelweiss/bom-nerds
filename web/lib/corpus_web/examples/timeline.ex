defmodule CorpusWeb.Examples.Timeline do
  @behaviour CorpusWeb.Examples

  use Phoenix.Component

  import CorpusWeb.Examples, only: [scale: 3, px: 1]

  @width 800
  @row 22
  @label 110
  @top 30
  @first -1100
  @last 500

  def slug, do: "timeline"
  def title, do: "When the scriptures take place"

  def description,
    do:
      "The years each book of the Bible and Book of Mormon covers, from the dates its passages carry."

  def sql do
    """
    select b.name as book, wk.name as work,
           min(d.from_year) as from_year,
           max(coalesce(d.to_year, d.from_year)) as to_year
    from date d
    join counting_system cs on cs.id = d.counting_system_id
    join word w on w.id = d.first_word_id
    join verse v on v.id = w.verse_id
    join chapter c on c.id = v.chapter_id
    join book b on b.id = c.book_id
    join work wk on wk.id = b.work_id
    where cs.name = 'BC/AD' and d.from_year < 1000
    group by b.id
    order by from_year, to_year
    """
  end

  attr :rows, :list, required: true
  attr :preview, :boolean, default: false

  def chart(assigns) do
    x = &px(scale(&1, {@first, @last}, {@label, @width - 10}))

    bars =
      assigns.rows
      |> Enum.with_index()
      |> Enum.map(fn {row, i} ->
        x1 = x.(row["from_year"])

        %{
          book: row["book"],
          years: "#{year(row["from_year"])} to #{year(row["to_year"])}",
          x: x1,
          y: @top + i * @row,
          width: max(x.(row["to_year"]) - x1, 4),
          color: if(row["work"] == "Book of Mormon", do: "fill-chart-2", else: "fill-chart-1")
        }
      end)

    ticks = for year <- -1000..400//200, do: %{x: x.(year), label: year(year)}

    assigns =
      assign(assigns,
        bars: bars,
        ticks: ticks,
        width: @width,
        height: @top + length(bars) * @row + 30,
        row: @row,
        label: @label
      )

    ~H"""
    <svg viewBox={"0 0 #{@width} #{@height}"} class="w-full" role="img" aria-label="Timeline of books">
      <g :for={tick <- @ticks}>
        <line x1={tick.x} x2={tick.x} y1="20" y2={@height - 30} class="stroke-border" />
        <text
          :if={!@preview}
          x={tick.x}
          y="12"
          font-size="11"
          text-anchor="middle"
          class="fill-muted-foreground"
        >
          {tick.label}
        </text>
      </g>
      <g :for={bar <- @bars}>
        <rect x={bar.x} y={bar.y} width={bar.width} height={@row - 6} rx="3" class={bar.color}>
          <title>{bar.book}, {bar.years}</title>
        </rect>
        <text
          :if={!@preview}
          x={@label - 8}
          y={bar.y + 12}
          font-size="12"
          text-anchor="end"
          class="fill-foreground"
        >
          {bar.book}
        </text>
      </g>
      <g :if={!@preview} font-size="12" class="fill-foreground">
        <rect x={@width - 230} y={@height - 22} width="12" height="12" rx="2" class="fill-chart-1" />
        <text x={@width - 212} y={@height - 12}>Bible</text>
        <rect x={@width - 160} y={@height - 22} width="12" height="12" rx="2" class="fill-chart-2" />
        <text x={@width - 142} y={@height - 12}>Book of Mormon</text>
      </g>
    </svg>
    """
  end

  defp year(0), do: "0"
  defp year(year) when year < 0, do: "#{-year} BC"
  defp year(year), do: "AD #{year}"
end
