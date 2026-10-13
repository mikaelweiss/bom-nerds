defmodule CorpusWeb.ExamplesLiveTest do
  use CorpusWeb.ConnCase, async: true

  import Phoenix.LiveViewTest

  alias CorpusWeb.Examples

  test "lists every example", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/examples")

    for example <- Examples.all() do
      assert has_element?(view, ~s(a[href="/examples/#{example.slug()}"]), example.title())
    end
  end

  test "an example links back to the list", %{conn: conn} do
    {:ok, view, _html} = live(conn, "/examples/pauls-journeys")

    assert has_element?(view, ~s(a[href="/examples"][aria-label="Back to examples"]))
  end

  test "an unknown example is not found", %{conn: conn} do
    assert_raise CorpusWeb.NotFoundError, fn -> live(conn, "/examples/nope") end
  end

  test "the API is not served on the site's host", %{conn: conn} do
    assert response(get(conn, "/v1/sql?q=select 1"), 404)
  end
end
