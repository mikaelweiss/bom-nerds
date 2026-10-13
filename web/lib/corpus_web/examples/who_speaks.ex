defmodule CorpusWeb.Examples.WhoSpeaks do
  @behaviour CorpusWeb.Examples

  use Phoenix.Component

  import CorpusWeb.Examples, only: [px: 1]

  @width 800
  @height 560
  @pad 20
  @gap 8
  @left 250
  @right 550
  @bar 8
  @pairs 20

  def slug, do: "who-speaks"
  def title, do: "Who speaks to whom"

  def description,
    do:
      "The #{@pairs} pairs of speaker and listener who talk most in the Book of Mormon. Each band's width is how many times one speaks to the other."

  def sql do
    """
    select sp.name as speaker, li.name as listener, count(*) as speeches
    from speech s
    join speech_speaker ss on ss.speech_id = s.id
    join entity sp on sp.id = ss.entity_id
    join speech_listener sl on sl.speech_id = s.id
    join entity li on li.id = sl.entity_id
    join word w on w.id = s.first_word_id
    join verse v on v.id = w.verse_id
    join chapter c on c.id = v.chapter_id
    join edition e on e.id = c.edition_id
    where e.name = 'Book of Mormon (2013)'
    group by sp.id, li.id
    order by speeches desc
    """
  end

  attr :rows, :list, required: true
  attr :preview, :boolean, default: false

  def chart(assigns) do
    pairs = Enum.take(assigns.rows, @pairs)
    speakers = stack(pairs, "speaker")
    listeners = stack(pairs, "listener")
    total = pairs |> Enum.map(& &1["speeches"]) |> Enum.sum()
    gaps = @gap * (max(length(speakers), length(listeners)) - 1)
    unit = if total > 0, do: (@height - 2 * @pad - gaps) / total, else: 0
    speaker_nodes = position(speakers, unit)
    listener_nodes = position(listeners, unit)

    bands =
      pairs
      |> Enum.sort_by(&{index(speakers, &1["speaker"]), index(listeners, &1["listener"])})
      |> Enum.map_reduce({%{}, %{}}, fn pair, {speaker_used, listener_used} ->
        from = speaker_nodes[pair["speaker"]]
        to = listener_nodes[pair["listener"]]
        size = pair["speeches"] * unit
        y1 = from.y + Map.get(speaker_used, pair["speaker"], 0)
        y2 = to.y + Map.get(listener_used, pair["listener"], 0)

        band = %{
          title: "#{pair["speaker"]} to #{pair["listener"]}: #{pair["speeches"]}",
          path: band(y1, y2, size)
        }

        {band,
         {Map.update(speaker_used, pair["speaker"], size, &(&1 + size)),
          Map.update(listener_used, pair["listener"], size, &(&1 + size))}}
      end)
      |> elem(0)

    assigns =
      assign(assigns,
        bands: bands,
        speakers: Map.values(speaker_nodes),
        listeners: Map.values(listener_nodes),
        width: @width,
        height: @height,
        left: @left,
        right: @right,
        bar: @bar
      )

    ~H"""
    <svg
      viewBox={"0 0 #{@width} #{@height}"}
      class="w-full"
      role="img"
      aria-label="Who speaks to whom"
    >
      <path :for={band <- @bands} d={band.path} class="fill-chart-1" fill-opacity="0.35">
        <title>{band.title}</title>
      </path>
      <rect
        :for={node <- @speakers}
        x={@left - @bar}
        y={node.y}
        width={@bar}
        height={node.height}
        class="fill-chart-1"
      />
      <rect
        :for={node <- @listeners}
        x={@right}
        y={node.y}
        width={@bar}
        height={node.height}
        class="fill-chart-2"
      />
      <text
        :for={node <- @speakers}
        :if={!@preview}
        x={@left - @bar - 6}
        y={px(node.y + node.height / 2 + 4)}
        font-size="12"
        text-anchor="end"
        class="fill-foreground"
      >
        {node.name}
      </text>
      <text
        :for={node <- @listeners}
        :if={!@preview}
        x={@right + @bar + 6}
        y={px(node.y + node.height / 2 + 4)}
        font-size="12"
        class="fill-foreground"
      >
        {node.name}
      </text>
    </svg>
    """
  end

  defp stack(pairs, key) do
    pairs
    |> Enum.group_by(& &1[key], & &1["speeches"])
    |> Enum.map(fn {name, counts} -> {name, Enum.sum(counts)} end)
    |> Enum.sort_by(fn {_name, count} -> -count end)
  end

  defp position(stack, unit) do
    stack
    |> Enum.map_reduce(@pad, fn {name, count}, y ->
      height = count * unit
      {{name, %{name: name, y: px(y), height: px(height)}}, y + height + @gap}
    end)
    |> elem(0)
    |> Map.new()
  end

  defp index(stack, name), do: Enum.find_index(stack, fn {n, _count} -> n == name end)

  defp band(y1, y2, size) do
    x1 = @left
    x2 = @right
    mid = (x1 + x2) / 2

    "M#{x1},#{px(y1)} C#{mid},#{px(y1)} #{mid},#{px(y2)} #{x2},#{px(y2)} " <>
      "L#{x2},#{px(y2 + size)} C#{mid},#{px(y2 + size)} #{mid},#{px(y1 + size)} #{x1},#{px(y1 + size)} Z"
  end
end
