defmodule Corpus.RateLimit do
  @moduledoc """
  Caps the queries each client runs per minute and at once, so no client can
  take every connection. Cached responses do not count.
  """

  use Hammer, backend: :ets

  @running Corpus.RateLimit.Running

  @doc "Runs `query` for `client` unless the client is over a limit."
  def run(client, query) do
    with :ok <- per_minute(client) do
      {:ok, _} = Registry.register(@running, client, nil)

      try do
        if length(Registry.lookup(@running, client)) > config(:queries_at_once),
          do: {:deny, "Too many queries at once. Wait for one to finish."},
          else: {:ok, query.()}
      after
        Registry.unregister(@running, client)
      end
    end
  end

  defp per_minute(client) do
    case hit(client, :timer.minutes(1), config(:queries_per_minute)) do
      {:allow, _count} -> :ok
      {:deny, ms} -> {:deny, "Too many queries. Try again in #{div(ms, 1000) + 1} seconds."}
    end
  end

  defp config(key), do: Application.fetch_env!(:corpus, :rate_limit)[key]
end
