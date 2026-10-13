defmodule CorpusWeb.EntityLive do
  use CorpusWeb, :live_view

  import CorpusWeb.Scripture, only: [entity_link: 1, reader_path: 1]

  alias Corpus.Scripture

  def mount(%{"id" => id}, _session, socket) do
    if Scripture.available?() do
      entity =
        with {id, ""} <- Integer.parse(id),
             %{} = entity <- Scripture.entity(id) do
          entity
        else
          _ -> raise CorpusWeb.NotFoundError
        end

      {:ok, assign(socket, page_title: entity.name, entity: entity)}
    else
      {:ok, assign(socket, page_title: "Not installed", entity: nil)}
    end
  end

  def handle_event("expand", %{"edition" => edition, "book" => book}, socket) do
    {edition, book} = {String.to_integer(edition), String.to_integer(book)}
    entity = socket.assigns.entity
    verses = Scripture.entity_verses(entity.id, edition, book)

    named =
      Enum.map(entity.named, fn
        %{edition_id: ^edition, book_id: ^book} = named -> %{named | verses: verses}
        named -> named
      end)

    {:noreply, assign(socket, entity: %{entity | named: named})}
  end

  def render(%{entity: nil} = assigns) do
    ~H"""
    <Layouts.app>
      <section class="mx-auto max-w-5xl px-6 py-12">
        <p class="text-muted-foreground">The scripture data is not installed yet.</p>
      </section>
    </Layouts.app>
    """
  end

  def render(assigns) do
    assigns =
      assign(assigns,
        names: Enum.reject(assigns.entity.names, & &1.title),
        titles: Enum.filter(assigns.entity.names, & &1.title),
        relationships: Enum.chunk_by(assigns.entity.relationships, & &1.label)
      )

    ~H"""
    <Layouts.app>
      <article class="mx-auto max-w-5xl px-6 py-12">
        <p class="text-sm text-muted-foreground">{@entity.type}</p>
        <h1 class="mt-2 font-serif text-4xl font-semibold tracking-tight">{@entity.name}</h1>
        <p :if={@entity.description != ""} class="mt-4 max-w-2xl text-lg text-muted-foreground">
          {@entity.description}
        </p>

        <dl class="mt-8 grid max-w-2xl gap-3 text-sm sm:grid-cols-[10rem_1fr]">
          <%= if @names != [] do %>
            <dt class="text-muted-foreground">Also called</dt>
            <dd>{Enum.map_join(@names, ", ", & &1.name)}</dd>
          <% end %>
          <%= if @titles != [] do %>
            <dt class="text-muted-foreground">Titles</dt>
            <dd>{Enum.map_join(@titles, ", ", & &1.name)}</dd>
          <% end %>
          <%= if @entity.latitude do %>
            <dt class="text-muted-foreground">Location</dt>
            <dd>
              <a
                href={"https://www.openstreetmap.org/?mlat=#{@entity.latitude}&mlon=#{@entity.longitude}#map=9/#{@entity.latitude}/#{@entity.longitude}"}
                class="underline underline-offset-4"
              >
                {@entity.latitude}, {@entity.longitude}
              </a>
            </dd>
          <% end %>
        </dl>

        <.block :if={@relationships != []} title="Relationships">
          <dl class="grid gap-x-6 gap-y-4 sm:grid-cols-[10rem_1fr]">
            <%= for [%{label: label} | _] = group <- @relationships do %>
              <dt class="text-muted-foreground">{label}</dt>
              <dd class="space-y-1">
                <p :for={relationship <- group}>
                  <.entity_link entity={relationship.other} />
                  <span :for={range <- relationship.evidence} class="ms-2 text-sm">
                    <.link
                      navigate={reader_path(range.first)}
                      class="text-muted-foreground hover:underline"
                    >
                      {range.reference}
                    </.link>
                  </span>
                </p>
              </dd>
            <% end %>
          </dl>
        </.block>

        <.block :if={@entity.journeys != []} title="Journeys">
          <ol class="space-y-2">
            <li :for={journey <- @entity.journeys}>
              <.entity_link entity={journey.traveler} />
              <span :if={journey.from}>from <.entity_link entity={journey.from} /></span>
              to
              <.entity_link entity={journey.to} /><span :if={journey.days}>, {days(journey.days)}</span>
              <.link
                navigate={reader_path(journey.range.first)}
                class="ms-2 text-sm text-muted-foreground hover:underline"
              >
                {journey.range.reference}
              </.link>
            </li>
          </ol>
        </.block>

        <.block :if={@entity.named != []} title="Named in">
          <.books books={@entity.named} noun="verse" expandable />
        </.block>

        <.block :if={@entity.about != []} title="Passages about it">
          <.books books={@entity.about} noun="passage" />
        </.block>
      </article>
    </Layouts.app>
    """
  end

  defp days(days) when days == 1, do: "1 day"
  defp days(days) when days == trunc(days), do: "#{trunc(days)} days"
  defp days(days), do: "#{days} days"

  attr :title, :string, required: true
  slot :inner_block, required: true

  defp block(assigns) do
    ~H"""
    <section class="mt-12">
      <h2 class="font-serif text-2xl font-semibold">{@title}</h2>
      <div class="mt-4">{render_slot(@inner_block)}</div>
    </section>
    """
  end

  attr :books, :list, required: true
  attr :noun, :string, required: true
  attr :expandable, :boolean, default: false

  defp books(assigns) do
    ~H"""
    <ol class="divide-y border-y">
      <li :for={book <- @books} class="py-4 sm:flex sm:gap-6">
        <div class="shrink-0 sm:w-48">
          <p class="font-serif text-lg font-semibold">{book.book_name}</p>
          <p class="text-sm text-muted-foreground">
            {book.edition}, {book.count} {if book.count == 1, do: @noun, else: @noun <> "s"}
          </p>
        </div>
        <div class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-sm sm:mt-1">
          <.link
            :for={verse <- book.verses || []}
            navigate={reader_path(Map.get(verse, :first, verse))}
            class="tabular-nums hover:underline"
          >
            {verse_label(verse)}
          </.link>
          <button
            :if={@expandable && book.verses == nil}
            type="button"
            phx-click="expand"
            phx-value-edition={book.edition_id}
            phx-value-book={book.book_id}
            class="text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            Show verses
          </button>
        </div>
      </li>
    </ol>
    """
  end

  defp verse_label(%{reference: reference, first: %{book_name: book}}),
    do: String.replace_prefix(reference, book <> " ", "")

  defp verse_label(%{verse: nil} = location), do: "#{location.chapter}"
  defp verse_label(location), do: "#{location.chapter}:#{location.verse}"
end
