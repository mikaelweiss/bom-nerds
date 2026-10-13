defmodule CorpusWeb.ExampleLive do
  use CorpusWeb, :live_view

  alias CorpusWeb.Examples

  def mount(%{"slug" => slug}, _session, socket) do
    example = Examples.get(slug) || raise CorpusWeb.NotFoundError

    {:ok,
     assign(socket,
       page_title: example.title(),
       example: example,
       rows: Examples.rows(example)
     )}
  end

  def render(assigns) do
    ~H"""
    <Layouts.app>
      <section class="mx-auto max-w-5xl px-6 py-12">
        <.link
          navigate={~p"/examples"}
          aria-label="Back to examples"
          class="-ml-2 inline-flex size-10 items-center justify-center rounded-md hover:bg-accent"
        >
          <svg
            viewBox="0 0 24 24"
            class="size-5"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
        </.link>
        <h1 class="mt-6 font-serif text-4xl font-semibold tracking-tight">{@example.title()}</h1>
        <p class="mt-4 max-w-2xl text-lg text-muted-foreground">{@example.description()}</p>

        <div class="mt-10 rounded-xl border p-4 sm:p-8">
          <Examples.chart example={@example} rows={@rows} />
        </div>

        <h2 class="mt-12 font-serif text-2xl font-semibold">The query</h2>
        <pre class="mt-4 overflow-x-auto rounded-lg border bg-muted p-4 text-sm"><code>{@example.sql()}</code></pre>
        <p class="mt-4 text-muted-foreground">
          <a href={Examples.api_url(@example)} class="underline">Run it on the API</a>
          to see the rows this chart is drawn from.
        </p>
      </section>
    </Layouts.app>
    """
  end
end
