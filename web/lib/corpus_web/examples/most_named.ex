defmodule CorpusWeb.Examples.MostNamed do
  @behaviour CorpusWeb.Examples

  use Phoenix.Component

  import CorpusWeb.Examples, only: [scale: 3, px: 1]

  @width 800
  @row 30
  @label 160

  def slug, do: "most-named"
  def title, do: "Who the Book of Mormon names most"

  def description,
    do: "How often the text refers to each person, by name, title, or pronoun."

  def sql do
    """
    select e.name, e.description, count(*) as mentions
    from mention m
    join mention_kind k on k.id = m.mention_kind_id
    join entity e on e.id = m.entity_id
    join entity_type t on t.id = e.entity_type_id
    join word w on w.id = m.first_word_id
    join verse v on v.id = w.verse_id
    join chapter c on c.id = v.chapter_id
    join edition ed on ed.id = c.edition_id
    where k.name = 'Refers to' and t.name = 'Person' and ed.name = 'Book of Mormon (2013)'
    group by e.id
    order by mentions desc
    limit 15
    """
  end

  attr :rows, :list, required: true
  attr :preview, :boolean, default: false

  def chart(assigns) do
    most = assigns.rows |> Enum.map(& &1["mentions"]) |> Enum.max(fn -> 1 end)

    bars =
      assigns.rows
      |> Enum.with_index()
      |> Enum.map(fn {row, i} ->
        %{
          name: row["name"],
          description: row["description"],
          mentions: row["mentions"],
          y: i * @row,
          width: px(scale(row["mentions"], {0, most}, {0, @width - @label - 60}))
        }
      end)

    assigns =
      assign(assigns,
        bars: bars,
        width: @width,
        height: length(bars) * @row,
        label: @label,
        row: @row
      )

    ~H"""
    <svg viewBox={"0 0 #{@width} #{@height}"} class="w-full" role="img" aria-label="Most named people">
      <g :for={bar <- @bars}>
        <title>{bar.name}: {bar.description}</title>
        <rect
          x={@label}
          y={bar.y + 4}
          width={bar.width}
          height={@row - 8}
          rx="3"
          class="fill-chart-1"
        />
        <text
          :if={!@preview}
          x={@label - 8}
          y={bar.y + 19}
          font-size="13"
          text-anchor="end"
          class="fill-foreground"
        >
          {bar.name}
        </text>
        <text
          :if={!@preview}
          x={@label + bar.width + 6}
          y={bar.y + 19}
          font-size="12"
          class="fill-muted-foreground"
        >
          {bar.mentions}
        </text>
      </g>
    </svg>
    """
  end
end
