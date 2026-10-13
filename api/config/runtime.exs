import Config

if System.get_env("PHX_SERVER") do
  config :corpus, CorpusWeb.Endpoint, server: true
end

config :corpus, CorpusWeb.Endpoint,
  http: [port: String.to_integer(System.get_env("PORT", "4000"))]

config :corpus, :github_token, System.get_env("GITHUB_TOKEN")

if data_dir = System.get_env("DATA_DIR") do
  config :corpus, :data_dir, data_dir
end

if config_env() == :prod do
  config :corpus, CorpusWeb.Endpoint,
    url: [host: System.fetch_env!("PHX_HOST"), port: 443, scheme: "https"],
    http: [ip: {127, 0, 0, 1}]
end
