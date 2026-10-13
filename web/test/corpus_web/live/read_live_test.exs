defmodule CorpusWeb.ReadLiveTest do
  use CorpusWeb.ConnCase, async: false

  import Phoenix.LiveViewTest

  @moduletag :tmp_dir

  describe "with a release installed" do
    @describetag :reader
    setup :serve_fixture

    test "lists each edition's books in edition order, each linking to its first chapter", %{
      conn: conn
    } do
      for {edition, books} <- [
            {"kjv", [{"Genesis", "genesis/1"}, {"Luke", "luke/12"}, {"John", "john/1"}]},
            {"wlc", [{"Genesis", "genesis/1"}]},
            {"sblgnt", [{"Luke", "luke/12"}, {"John", "john/1"}]},
            {"book-of-mormon", [{"1 Nephi", "1-nephi/3"}]}
          ] do
        {:ok, view, _html} = live(conn, "/read?edition=#{edition}")

        assert book_order(view, edition) ==
                 Enum.map(books, fn {_name, path} -> hd(String.split(path, "/")) end)

        for {name, path} <- books do
          assert has_element?(view, ~s(#books a[href="/read/#{edition}/#{path}"]), name)
        end
      end
    end

    test "lists a book's chapters", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/read")

      assert has_element?(view, ~s(a[href="/read/kjv/genesis/2"][aria-label="Genesis 2"]))
    end
  end

  test "renders without a release installed", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/read")

    assert html =~ "The scripture text is not installed yet."
  end

  defp book_order(view, edition) do
    view
    |> element("#books")
    |> render()
    |> then(&Regex.scan(~r{href="/read/#{edition}/([^/]+)/}, &1, capture: :all_but_first))
    |> List.flatten()
    |> Enum.dedup()
  end
end
