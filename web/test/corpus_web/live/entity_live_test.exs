defmodule CorpusWeb.EntityLiveTest do
  use CorpusWeb.ConnCase, async: false

  import Phoenix.LiveViewTest

  @moduletag :tmp_dir

  describe "with a release installed" do
    @describetag :reader
    setup :serve_fixture

    test "the two people named Nephi each have their own page", %{conn: conn} do
      {:ok, view, html} = live(conn, "/entities/1")

      assert has_element?(view, "h1", "Nephi")
      assert html =~ "Son of Lehi."
      assert html =~ "son of Lehi"
      assert has_element?(view, ~s(a[href="/entities/4"]), "Lehi")
      assert has_element?(view, ~s(a[href="/read/book-of-mormon/1-nephi/3?v=7"]), "1 Nephi 3:7")
      assert has_element?(view, "li", "1 Nephi")
      refute html =~ "Helaman"
      refute html =~ "Luke"

      {:ok, view, html} = live(conn, "/entities/3")

      assert has_element?(view, "h1", "Nephi")
      assert html =~ "Son of Helaman."
      assert has_element?(view, ~s(a[href="/entities/7"]), "Helaman")
      assert has_element?(view, ~s(a[href="/read/kjv/luke/12?v=11"]), "12:11")
      refute html =~ "Lehi"
      refute html =~ "1 Nephi"
    end

    test "shows relationships from the other side", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/entities/4")

      assert has_element?(view, "dt", "parent of")
      assert has_element?(view, ~s(a[href="/entities/1"]), "Nephi")
    end

    test "a place shows its names, location, and journeys to it", %{conn: conn} do
      {:ok, view, html} = live(conn, "/entities/5")

      assert html =~ "Salem"
      assert has_element?(view, "a", "31.777, 35.234")
      assert has_element?(view, "li", "3 days")
      assert has_element?(view, ~s(li a[href="/entities/1"]), "Nephi")
    end

    test "a topic lists the passages about it", %{conn: conn} do
      {:ok, view, _html} = live(conn, "/entities/2")

      assert has_element?(view, ~s(a[href="/read/kjv/genesis/1?v=1"]), "1:1-2")
    end

    test "an unknown entity is not found", %{conn: conn} do
      assert_raise CorpusWeb.NotFoundError, fn -> live(conn, "/entities/999") end
      assert_raise CorpusWeb.NotFoundError, fn -> live(conn, "/entities/nephi") end
    end
  end

  test "renders without a release installed", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/entities/1")

    assert html =~ "not installed yet"
  end
end
