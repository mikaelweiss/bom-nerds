defmodule CorpusWeb.ExamplesLive do
  use CorpusWeb, :live_view

  alias CorpusWeb.Examples

  def mount(_params, _session, socket) do
    {:ok, assign(socket, page_title: "Examples", examples: Examples.with_rows())}
  end

  def render(assigns) do
    ~H"""
    <Layouts.app>
      <section class="mx-auto max-w-5xl px-6 py-16">
        <h1 class="font-serif text-4xl font-semibold tracking-tight">Examples</h1>
        <p class="mt-4 max-w-2xl text-lg text-muted-foreground">
          Visualizations drawn straight from the API. Each one shows the query behind it.
        </p>
        <Examples.card_grid examples={@examples} class="mt-10" />
      </section>
    </Layouts.app>
    """
  end
end
