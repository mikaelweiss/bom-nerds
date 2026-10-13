defmodule CorpusWeb.SqlController do
  use CorpusWeb, :controller

  alias Corpus.{Cache, Database, Query, RateLimit, Versions}
  alias CorpusWeb.CacheControl

  def run(conn, %{"version" => version} = params) do
    sql = if is_binary(params["q"]), do: params["q"], else: ""

    {status, body} =
      cond do
        not Versions.exists?(version) ->
          error(404, "There is no API version #{version}.")

        database = Database.get(version) ->
          respond(conn, {version, sql}, database, sql)

        true ->
          error(503, "No data is installed yet.")
      end

    conn
    |> then(if status in [200, 400], do: &CacheControl.cache/1, else: &CacheControl.no_store/1)
    |> put_resp_content_type("application/json")
    |> send_resp(status, body)
  end

  defp respond(conn, key, database, sql) do
    with nil <- Cache.get(key),
         {:ok, response} <-
           RateLimit.run(client(conn), fn ->
             Cache.fetch(key, fn -> result(Query.run(database, sql)) end)
           end) do
      response
    else
      {:deny, message} -> error(429, message)
      cached -> cached
    end
  end

  defp result({:ok, result}) do
    case Jason.encode(result) do
      {:ok, body} -> {200, body}
      {:error, _} -> error(400, "The result holds binary data. Select hex(column) instead.")
    end
  end

  defp result({:error, message}), do: error(400, message)
  defp result({:busy, message}), do: error(503, message)

  defp error(status, message), do: {status, Jason.encode!(%{error: message})}

  defp client(conn) do
    with header when is_binary(header) <- Application.get_env(:corpus, :client_ip_header),
         [ip | _] <- get_req_header(conn, header) do
      ip
    else
      _ -> conn.remote_ip |> :inet.ntoa() |> to_string()
    end
  end
end
