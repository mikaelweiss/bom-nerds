defmodule Mix.Tasks.Corpus.Install do
  @shortdoc "Installs the latest data release"
  @moduledoc """
  Downloads the latest data release and builds a database for each API
  version. Restart the app to serve it.
  """

  use Mix.Task

  @requirements ["app.config"]

  @impl true
  def run(_args) do
    {:ok, _} = Application.ensure_all_started(:req)

    case Corpus.Install.run() do
      {:ok, release} -> Mix.shell().info("Installed #{release["tag"]}.")
      {:error, reason} -> Mix.raise("Could not install the latest release: #{reason}")
    end
  end
end
