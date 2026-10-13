defmodule Corpus.MixProject do
  use Mix.Project

  def project do
    [
      app: :corpus,
      version: "0.1.0",
      elixir: "~> 1.17",
      elixirc_paths: elixirc_paths(Mix.env()),
      start_permanent: Mix.env() == :prod,
      aliases: aliases(),
      deps: deps(),
      listeners: [Phoenix.CodeReloader]
    ]
  end

  def application do
    [
      mod: {Corpus.Application, []},
      extra_applications: [:logger, :runtime_tools]
    ]
  end

  def cli do
    [
      preferred_envs: [precommit: :test]
    ]
  end

  defp elixirc_paths(:test), do: ["lib", "test/support"]
  defp elixirc_paths(_), do: ["lib"]

  defp deps do
    [
      {:phoenix, "~> 1.8.13"},
      {:jason, "~> 1.2"},
      {:bandit, "~> 1.5"},
      {:exqlite, "~> 0.42.0"},
      {:req, "~> 0.7.5"},
      {:cachex, "~> 4.1"},
      {:hammer, "~> 7.4"}
    ]
  end

  defp aliases do
    [
      setup: ["deps.get", "corpus.install"],
      precommit: ["compile --warnings-as-errors", "deps.unlock --unused", "format", "test"]
    ]
  end
end
