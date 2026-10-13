defmodule Corpus.GitHub do
  @moduledoc """
  Reads the latest data release from GitHub and downloads its database.
  """

  @asset "scripture-db.zip"

  def latest_release do
    case Req.get(req(), url: "/repos/#{repository()}/releases/latest") do
      {:ok, %{status: 200, body: body}} ->
        case Enum.find(body["assets"], &(&1["name"] == @asset)) do
          nil ->
            {:error, "Release #{body["tag_name"]} has no #{@asset}."}

          asset ->
            {:ok,
             %{
               "tag" => body["tag_name"],
               "published_at" => body["published_at"],
               "url" => body["html_url"],
               "download_url" => asset["browser_download_url"]
             }}
        end

      {:ok, %{status: status}} ->
        {:error, "GitHub answered #{status}."}

      {:error, exception} ->
        {:error, Exception.message(exception)}
    end
  end

  def download(url, path) do
    case Req.get(req(), url: url, into: File.stream!(path), receive_timeout: :timer.minutes(5)) do
      {:ok, %{status: 200}} -> :ok
      {:ok, %{status: status}} -> {:error, "Download answered #{status}."}
      {:error, exception} -> {:error, Exception.message(exception)}
    end
  end

  defp repository, do: Application.fetch_env!(:corpus, :repository)

  defp req do
    auth =
      case Application.get_env(:corpus, :github_token) do
        nil -> []
        token -> [auth: {:bearer, token}]
      end

    Req.new(
      [base_url: "https://api.github.com"] ++
        auth ++ Application.get_env(:corpus, :req_options, [])
    )
  end
end
