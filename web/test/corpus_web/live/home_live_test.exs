defmodule CorpusWeb.HomeLiveTest do
  use CorpusWeb.ConnCase, async: true

  import Phoenix.LiveViewTest

  test "links to the latest API guide", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/")

    assert has_element?(view, ~s(a[href="/v2"]), "Read the API guide")
  end
end
