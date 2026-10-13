defmodule CorpusWeb.GuideController do
  use CorpusWeb, :controller

  alias Corpus.Versions
  alias CorpusWeb.CacheControl

  def show(conn, %{"version" => version}) do
    if Versions.exists?(version) do
      guide = String.replace(Versions.guide(version), "{{origin}}", CorpusWeb.Endpoint.url())

      conn
      |> CacheControl.cache()
      |> put_resp_content_type("text/markdown")
      |> send_resp(200, guide)
    else
      conn
      |> put_status(:not_found)
      |> json(%{
        error: "There is no API version #{version}. Versions: #{Enum.join(Versions.all(), ", ")}."
      })
    end
  end
end
