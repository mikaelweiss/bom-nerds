defmodule CorpusWeb.Layouts do
  @moduledoc false

  use CorpusWeb, :html

  import SaladUI.Helpers, only: [button_variant: 1]

  embed_templates "layouts/*"

  @repository "https://github.com/mikaelweiss/standard-works-corpus"

  def repository, do: @repository

  slot :inner_block, required: true

  def app(assigns) do
    ~H"""
    <header class="border-b">
      <nav class="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <.link navigate={~p"/"} class="font-serif text-lg font-semibold">
          Standard Works Corpus
        </.link>
        <div class="flex items-center gap-1">
          <.link navigate={~p"/examples"} class={button_variant(%{variant: "ghost"})}>
            Examples
          </.link>
          <a
            href={CorpusWeb.api_url("/#{Corpus.Versions.latest()}")}
            class={button_variant(%{variant: "ghost"})}
          >
            API
          </a>
          <a href={repository()} class={button_variant(%{variant: "ghost"})}>GitHub</a>
        </div>
      </nav>
    </header>

    <main>
      {render_slot(@inner_block)}
    </main>

    <footer class="border-t">
      <div class="mx-auto max-w-5xl px-6 py-8 text-sm text-muted-foreground">
        The data is
        <a href={"#{repository()}/blob/main/LICENSE-DATA.txt"} class="underline">CC BY 4.0</a>
        and the code is <a href={"#{repository()}/blob/main/LICENSE.md"} class="underline">Apache 2.0</a>.
        Keep the <a href={"#{repository()}/blob/main/CREDITS.md"} class="underline">credits</a>
        when you share the data.
      </div>
    </footer>
    """
  end
end
