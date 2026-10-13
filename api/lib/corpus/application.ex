defmodule Corpus.Application do
  @moduledoc false

  use Application

  @impl true
  def start(_type, _args) do
    children = [
      Corpus.Database,
      {Cachex, [name: Corpus.Cache, hooks: Corpus.Cache.hooks()]},
      {Corpus.RateLimit, clean_period: :timer.minutes(1)},
      {Registry, keys: :duplicate, name: Corpus.RateLimit.Running},
      CorpusWeb.Endpoint
    ]

    Supervisor.start_link(children, strategy: :one_for_one, name: Corpus.Supervisor)
  end

  @impl true
  def config_change(changed, _new, removed) do
    CorpusWeb.Endpoint.config_change(changed, removed)
    :ok
  end
end
