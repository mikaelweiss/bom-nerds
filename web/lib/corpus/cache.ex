defmodule Corpus.Cache do
  @moduledoc """
  Responses kept in memory until the next deploy restarts the app.

  Identical requests that arrive together run their query once. The least
  recently used responses are evicted past the entry limit.
  """

  import Cachex.Spec

  def hooks do
    [
      hook(module: Cachex.Limit.Accessed),
      hook(module: Cachex.Limit.Scheduled, args: {config(:entries), [], []})
    ]
  end

  def get(key) do
    {:ok, response} = Cachex.get(__MODULE__, key)
    response
  end

  @doc "The cached response for `key`, or the one `respond` builds."
  def fetch(key, respond) do
    case Cachex.fetch(__MODULE__, key, fn -> commit(respond.()) end) do
      {:error, error} -> raise error
      {_status, response} -> response
    end
  end

  defp commit({status, body} = response) do
    if status in [200, 400] and byte_size(body) <= config(:max_bytes),
      do: {:commit, response},
      else: {:ignore, response}
  end

  defp config(key), do: Application.fetch_env!(:corpus, :cache)[key]
end
