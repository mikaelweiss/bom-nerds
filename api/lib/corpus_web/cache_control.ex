defmodule CorpusWeb.CacheControl do
  @moduledoc """
  Responses change only when a deploy installs new data or code, and every
  deploy purges Cloudflare. So Cloudflare keeps them for a year, and browsers
  recheck after five minutes.
  """

  import Plug.Conn

  def cache(conn),
    do: put_resp_header(conn, "cache-control", "public, max-age=300, s-maxage=31536000")

  def no_store(conn), do: put_resp_header(conn, "cache-control", "no-store")
end
