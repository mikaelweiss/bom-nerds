import Config

config :corpus, CorpusWeb.Endpoint, cache_static_manifest: "priv/static/cache_manifest.json"

# Cloudflare Tunnel is the only way in, so it is the only source of this header.
config :corpus, client_ip_header: "cf-connecting-ip"

config :logger, level: :info
