defmodule CorpusWeb.ChapterLive do
  use CorpusWeb, :live_view

  import CorpusWeb.Scripture

  alias Corpus.Scripture

  def mount(%{"edition" => edition, "book" => book, "chapter" => number}, _session, socket) do
    if Scripture.available?() do
      chapter =
        with {number, ""} <- Integer.parse(number),
             %{} = chapter <- Scripture.chapter(edition, book, number) do
          chapter
        else
          _ -> raise CorpusWeb.NotFoundError
        end

      {:ok,
       assign(socket,
         page_title: "#{chapter.book.name} #{chapter.number}",
         chapter: chapter,
         verse: nil,
         word: nil,
         details: nil,
         word_details: nil
       )}
    else
      {:ok, assign(socket, page_title: "Read", chapter: nil)}
    end
  end

  def handle_params(_params, _uri, %{assigns: %{chapter: nil}} = socket),
    do: {:noreply, socket}

  def handle_params(params, _uri, socket) do
    verse = Enum.find(socket.assigns.chapter.verses, &(to_string(&1.number) == params["v"]))
    word = verse && Enum.find(verse.words, &(to_string(&1.position) == params["w"]))

    {:noreply,
     assign(socket,
       verse: verse,
       word: word,
       details: verse && details(socket.assigns, verse),
       word_details: word && Scripture.word(word.id)
     )}
  end

  defp details(%{verse: %{id: id}, details: details}, %{id: id}), do: details
  defp details(_assigns, verse), do: Scripture.verse(verse.id)

  def handle_event("select", params, socket) do
    {verse_id, word_id} = selection(params)
    verse = Enum.find(socket.assigns.chapter.verses, &(&1.id == verse_id))
    word = word_id && Enum.find(verse.words, &(&1.id == word_id))
    query = if word, do: [v: verse.number, w: word.position], else: [v: verse.number]
    {:noreply, push_patch(socket, to: chapter_path(socket.assigns.chapter, query))}
  end

  def handle_event("close", _params, socket),
    do: {:noreply, push_patch(socket, to: chapter_path(socket.assigns.chapter, []))}

  defp chapter_path(chapter, []),
    do: ~p"/read/#{chapter.edition.slug}/#{chapter.book.slug}/#{chapter.number}"

  defp chapter_path(chapter, query),
    do: ~p"/read/#{chapter.edition.slug}/#{chapter.book.slug}/#{chapter.number}?#{query}"

  def render(%{chapter: nil} = assigns) do
    ~H"""
    <Layouts.app>
      <section class="mx-auto max-w-5xl px-6 py-12">
        <h1 class="font-serif text-4xl font-semibold tracking-tight">Read</h1>
        <p class="mt-4 text-muted-foreground">The scripture text is not installed yet.</p>
      </section>
    </Layouts.app>
    """
  end

  def render(assigns) do
    ~H"""
    <Layouts.app>
      <div class="mx-auto max-w-5xl px-6 py-10 lg:grid lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-12">
        <article class={@verse && "pb-[60vh] lg:pb-0"}>
          <.link
            navigate={~p"/read?#{[edition: @chapter.edition.slug]}"}
            class="text-sm text-muted-foreground hover:underline"
          >
            {@chapter.edition.name}
          </.link>
          <h1 class="mt-2 font-serif text-4xl font-semibold tracking-tight">
            {@chapter.book.name} {@chapter.number}
          </h1>

          <div
            id="chapter-text"
            phx-hook=".ScrollToSelected"
            lang={@chapter.edition.language}
            dir={@chapter.edition.rtl && "rtl"}
            class={[
              "mt-8 max-w-prose font-serif",
              if(@chapter.edition.rtl,
                do: "text-2xl leading-loose",
                else: "text-[1.1875rem] leading-8"
              )
            ]}
          >
            <.verse
              :if={@chapter.heading}
              verse={@chapter.heading}
              class="mb-3 text-base italic text-muted-foreground"
            />
            <.verse
              :for={verse <- @chapter.verses}
              verse={verse}
              selected={@verse && @verse.id == verse.id}
              selected_word={@word && @word.id}
              on_select="select"
            />
          </div>

          <nav
            aria-label="Chapters"
            class="mt-12 flex items-center justify-between gap-4 border-t pt-6"
          >
            <.chapter_link :if={@chapter.previous} location={@chapter.previous} direction="previous" />
            <.chapter_link :if={@chapter.next} location={@chapter.next} direction="next" />
          </nav>
        </article>

        <aside class={[
          "lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:self-start lg:overflow-y-auto",
          if(@verse,
            do:
              "fixed inset-x-0 bottom-0 z-30 max-h-[60vh] overflow-y-auto rounded-t-2xl border-t bg-background p-6 shadow-2xl lg:static lg:z-auto lg:rounded-xl lg:border lg:shadow-none",
            else: "hidden lg:block"
          )
        ]}>
          <div :if={@verse} class="space-y-10">
            <.word_panel :if={@word_details} word={@word_details} on_close="close" />
            <.verse_panel :if={@details} details={@details} on_close={!@word_details && "close"} />
          </div>
          <p :if={!@verse} class="pt-24 text-sm text-muted-foreground">
            Click a verse number or any word to see who is speaking, where, the people and places
            named, and the Hebrew or Greek behind the English.
          </p>
        </aside>
      </div>

      <script :type={Phoenix.LiveView.ColocatedHook} name=".ScrollToSelected">
        export default {
          mounted() {
            this.reveal(true)
          },
          updated() {
            this.reveal(false)
          },
          reveal(loading) {
            const selected = this.el.querySelector("[data-selected]")
            if (selected === this.revealed) return
            this.revealed = selected
            if (!selected) return
            const wide = window.matchMedia("(min-width: 1024px)").matches
            if (loading) {
              selected.scrollIntoView({block: wide ? "center" : "start"})
            } else if (!wide && selected.getBoundingClientRect().top > window.innerHeight * 0.35) {
              selected.scrollIntoView({block: "start", behavior: "smooth"})
            }
          }
        }
      </script>
    </Layouts.app>
    """
  end

  attr :location, :map, required: true
  attr :direction, :string, required: true

  defp chapter_link(assigns) do
    ~H"""
    <.link
      navigate={reader_path(@location)}
      rel={if @direction == "next", do: "next", else: "prev"}
      aria-label={"#{String.capitalize(@direction)} chapter, #{@location.book_name} #{@location.chapter}"}
      class={[
        "inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent",
        @direction == "next" && "ms-auto"
      ]}
    >
      <svg
        :if={@direction == "previous"}
        viewBox="0 0 24 24"
        class="size-4"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M19 12H5M12 19l-7-7 7-7" />
      </svg>
      {@location.book_name} {@location.chapter}
      <svg
        :if={@direction == "next"}
        viewBox="0 0 24 24"
        class="size-4"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M5 12h14M12 5l7 7-7 7" />
      </svg>
    </.link>
    """
  end
end
