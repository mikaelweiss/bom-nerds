defmodule CorpusWeb.ApiTest do
  use CorpusWeb.ConnCase, async: false

  @moduletag :tmp_dir

  @slow """
  with recursive n(x) as (select 1 union all select x + 1 from n where x < 1000000000)
  select count(*) from n
  """

  describe "with a release installed" do
    setup :serve_fixture

    test "the root redirects to the latest version", %{conn: conn} do
      assert redirected_to(get(conn, "/")) == "/v2"
    end

    test "a version serves its guide", %{conn: conn} do
      conn = get(conn, "/v1")

      assert response(conn, 200) == "# Test guide\n\nQuery #{CorpusWeb.Endpoint.url()}/v1/sql.\n"
      assert response_content_type(conn, :markdown)
      assert get_resp_header(conn, "cache-control") == ["public, max-age=300, s-maxage=31536000"]
    end

    test "an unknown version is not found", %{conn: conn} do
      assert %{"error" => "There is no API version v9. " <> _} =
               json_response(get(conn, "/v9"), 404)

      assert %{"error" => "There is no API version v9."} =
               json_response(sql(conn, "v9", "select 1"), 404)
    end

    test "runs a query", %{conn: conn} do
      conn = sql(conn, "v1", "select id, name from entity where name = 'Nephi' order by id")

      assert json_response(conn, 200) == %{
               "release" => "data-1",
               "columns" => ["id", "name"],
               "rows" => [%{"id" => 1, "name" => "Nephi"}, %{"id" => 3, "name" => "Nephi"}],
               "truncated" => false
             }

      assert get_resp_header(conn, "access-control-allow-origin") == ["*"]
      assert get_resp_header(conn, "cache-control") == ["public, max-age=300, s-maxage=31536000"]
    end

    test "each version has its own tables", %{conn: conn} do
      assert %{"rows" => [%{"title" => "Moses"}]} =
               json_response(sql(conn, "v2", "select title from entity where id = 2"), 200)

      assert %{"error" => "no such column: title"} =
               json_response(sql(conn, "v1", "select title from entity"), 400)
    end

    test "keeps the order a query asks for", %{conn: conn} do
      assert %{"rows" => rows} =
               json_response(sql(conn, "v1", "select id from entity order by id desc;"), 200)

      assert rows == [%{"id" => 3}, %{"id" => 2}, %{"id" => 1}]
    end

    test "caps the rows", %{conn: conn} do
      assert %{"rows" => rows, "truncated" => true} =
               json_response(sql(conn, "v1", "select * from word"), 200)

      assert length(rows) == 5
    end

    test "cannot escape the row cap", %{conn: conn} do
      for escape <- [
            "select * from word) where 1 not in (select 1",
            "select * from word) limit 100; --",
            "select * from word) limit 100; select (1"
          ] do
        assert %{"error" => _} = json_response(sql(conn, "v1", escape), 400)
      end
    end

    test "only reads", %{conn: conn} do
      for statement <- [
            "delete from word",
            "attach 'other.db' as other",
            "pragma table_info(word)",
            "select * from pragma_table_info('word')",
            "select 1; delete from word"
          ] do
        assert %{"error" => _} = json_response(sql(conn, "v1", statement), 400)
      end

      assert %{"rows" => [%{"count" => 19}]} =
               json_response(sql(conn, "v1", "select count(*) as count from word"), 200)
    end

    test "stops a slow query", %{conn: conn} do
      assert json_response(sql(conn, "v1", @slow), 400) == %{
               "error" => "The query ran longer than 1 seconds."
             }

      assert %{"rows" => [%{"one" => 1}]} = json_response(sql(conn, "v1", "select 1 as one"), 200)
    end

    test "explains bad requests", %{conn: conn} do
      assert json_response(sql(conn, "v1", ""), 400) == %{"error" => "Pass a SQL query in q."}
      assert json_response(get(conn, "/v1/sql"), 400) == %{"error" => "Pass a SQL query in q."}

      assert json_response(sql(conn, "v1", "select x'ff'"), 400) == %{
               "error" => "The result holds binary data. Select hex(column) instead."
             }
    end

    test "limits the queries a client runs, but not cached ones", %{conn: conn} do
      limit(queries_per_minute: 2)
      conn = %{conn | remote_ip: {10, 0, 0, 1}}

      assert json_response(sql(conn, "v1", "select 1"), 200)
      assert json_response(sql(conn, "v1", "select 2"), 200)

      assert %{"error" => "Too many queries. " <> _} =
               json_response(sql(conn, "v1", "select 3"), 429)

      assert json_response(sql(conn, "v1", "select 1"), 200)

      other = %{conn | remote_ip: {10, 0, 0, 2}}
      assert json_response(sql(other, "v1", "select 3"), 200)
    end

    test "limits the queries a client runs at once", %{conn: conn} do
      limit(queries_at_once: 1)
      conn = %{conn | remote_ip: {10, 0, 0, 4}}
      slow = Task.async(fn -> sql(conn, "v1", @slow) end)
      Process.sleep(200)

      assert %{"error" => "Too many queries at once. " <> _} =
               json_response(sql(conn, "v1", "select 1"), 429)

      other = %{conn | remote_ip: {10, 0, 0, 5}}
      assert json_response(sql(other, "v1", "select 1"), 200)

      json_response(Task.await(slow), 400)
      assert json_response(sql(conn, "v1", "select 2"), 200)
    end

    test "never caches a refusal", %{conn: conn} do
      limit(queries_per_minute: 0)

      conn = sql(%{conn | remote_ip: {10, 0, 0, 3}}, "v1", "select 1")

      assert json_response(conn, 429)
      assert get_resp_header(conn, "cache-control") == ["no-store"]
      assert Corpus.Cache.get({"v1", "select 1"}) == nil
    end
  end

  test "is unavailable until a release is installed", %{conn: conn, tmp_dir: tmp_dir} do
    previous = Application.fetch_env!(:corpus, :data_dir)
    Application.put_env(:corpus, :data_dir, tmp_dir)
    restart_database()

    on_exit(fn ->
      Application.put_env(:corpus, :data_dir, previous)
      restart_database()
    end)

    assert json_response(sql(conn, "v1", "select 1"), 503) == %{
             "error" => "No data is installed yet."
           }

    assert response(get(conn, "/v1"), 200)
  end

  defp sql(conn, version, query), do: get(conn, "/#{version}/sql", q: query)

  defp limit(overrides) do
    previous = Application.fetch_env!(:corpus, :rate_limit)
    Application.put_env(:corpus, :rate_limit, Keyword.merge(previous, overrides))
    on_exit(fn -> Application.put_env(:corpus, :rate_limit, previous) end)
  end
end
