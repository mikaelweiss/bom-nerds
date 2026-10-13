defmodule CorpusWeb.Router do
  use CorpusWeb, :router

  pipeline :browser do
    plug :accepts, ["html"]
    plug :fetch_session
    plug :put_root_layout, html: {CorpusWeb.Layouts, :root}
    plug :protect_from_forgery
    plug :put_secure_browser_headers
  end

  pipeline :api do
    plug :fetch_query_params
    plug :allow_any_origin
  end

  scope "/", CorpusWeb do
    pipe_through :browser

    live "/", HomeLive
  end

  scope "/", CorpusWeb do
    pipe_through :api

    get "/:version", GuideController, :show
    get "/:version/sql", SqlController, :run
  end

  defp allow_any_origin(conn, _opts),
    do: put_resp_header(conn, "access-control-allow-origin", "*")
end
