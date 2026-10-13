defmodule CorpusWeb.ExamplesLive do
  use CorpusWeb, :live_view

  import SaladUI.Card

  alias CorpusWeb.Examples

  def mount(_params, _session, socket) do
    examples = for example <- Examples.all(), do: {example, Examples.rows(example)}
    {:ok, assign(socket, page_title: "Examples", examples: examples)}
  end

  def render(assigns) do
    ~H"""
    <Layouts.app>
      <section class="mx-auto max-w-5xl px-6 py-16">
        <h1 class="font-serif text-4xl font-semibold tracking-tight">Examples</h1>
        <p class="mt-4 max-w-2xl text-lg text-muted-foreground">
          Visualizations drawn straight from the API. Each one shows the query behind it.
        </p>
        <div class="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          <.link
            :for={{example, rows} <- @examples}
            navigate={~p"/examples/#{example.slug()}"}
            class="group rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <.card class="h-full overflow-hidden transition-shadow group-hover:shadow-md">
              <div class="aspect-[8/5] overflow-hidden border-b bg-muted/30 p-4">
                <Examples.chart example={example} rows={rows} preview />
              </div>
              <.card_header>
                <.card_title class="text-lg">{example.title()}</.card_title>
              </.card_header>
            </.card>
          </.link>
        </div>
      </section>
    </Layouts.app>
    """
  end
end
