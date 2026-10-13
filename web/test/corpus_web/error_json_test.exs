defmodule CorpusWeb.ErrorJSONTest do
  use ExUnit.Case, async: true

  test "renders an error" do
    assert CorpusWeb.ErrorJSON.render("404.json", %{}) == %{error: "Not Found"}
  end
end
