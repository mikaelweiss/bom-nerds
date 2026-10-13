defmodule CorpusWeb.Router do
  use CorpusWeb, :router

  pipeline :api do
    plug :fetch_query_params
    plug :allow_any_origin
  end

  scope "/", CorpusWeb do
    pipe_through :api

    get "/", GuideController, :index
    get "/:version", GuideController, :show
    get "/:version/sql", SqlController, :run
  end

  defp allow_any_origin(conn, _opts),
    do: put_resp_header(conn, "access-control-allow-origin", "*")
end
