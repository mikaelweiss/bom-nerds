defmodule CorpusWeb.ReadLive do
  use CorpusWeb, :live_view

  alias Corpus.Scripture

  def mount(_params, _session, socket) do
    {:ok, assign(socket, page_title: "Read", editions: Scripture.editions())}
  end

  def handle_params(params, _uri, socket) do
    editions = socket.assigns.editions
    edition = Enum.find(editions, &(&1.slug == params["edition"])) || List.first(editions)
    {:noreply, assign(socket, edition: edition)}
  end

  def render(assigns) do
    ~H"""
    <Layouts.app>
      <section class="mx-auto max-w-5xl px-6 py-12">
        <h1 class="font-serif text-4xl font-semibold tracking-tight">Read</h1>
        <p class="mt-4 max-w-2xl text-lg text-muted-foreground">
          Every edition, word by word. Click any verse or word to see who is speaking, where, the
          people and places it names, and the Hebrew or Greek behind the English.
        </p>

        <p :if={@editions == []} class="mt-10 text-muted-foreground">
          The scripture text is not installed yet.
        </p>

        <nav :if={@edition} aria-label="Editions" class="mt-10 flex flex-wrap gap-2">
          <.link
            :for={edition <- @editions}
            patch={~p"/read?#{[edition: edition.slug]}"}
            aria-current={edition.id == @edition.id && "page"}
            class={[
              "rounded-full border px-4 py-1.5 text-sm transition-colors",
              if(edition.id == @edition.id,
                do: "border-foreground bg-foreground text-background",
                else: "hover:bg-accent"
              )
            ]}
          >
            {edition.name}
          </.link>
        </nav>

        <ol :if={@edition} id="books" class="mt-10 divide-y border-y">
          <li :for={book <- @edition.books} class="py-4 sm:flex sm:gap-6">
            <.link
              navigate={~p"/read/#{@edition.slug}/#{book.slug}/#{hd(book.chapters).number}"}
              class="block shrink-0 font-serif text-lg font-semibold hover:underline sm:w-48"
            >
              {book.name}
            </.link>
            <div :if={length(book.chapters) > 1} class="mt-2 flex flex-wrap gap-1 sm:mt-0.5">
              <.link
                :for={chapter <- book.chapters}
                navigate={~p"/read/#{@edition.slug}/#{book.slug}/#{chapter.number}"}
                aria-label={"#{book.name} #{chapter.number}"}
                class="inline-flex h-8 min-w-8 items-center justify-center rounded-md px-1.5 text-sm text-muted-foreground tabular-nums hover:bg-accent hover:text-foreground"
              >
                {chapter.number}
              </.link>
            </div>
          </li>
        </ol>
      </section>
    </Layouts.app>
    """
  end
end
