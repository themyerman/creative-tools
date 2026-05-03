"""Tests for patreon-plan utilities."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from arttools.patreon_plan import cli, _load_works, _render_markdown
from click.testing import CliRunner


SAMPLE_POSTS = [
    {
        "week": 1, "day": "Monday", "date": "2026-05-06",
        "tier": "free", "type": "New print reveal",
        "title": "Announcing: Blood Crow", "description": "First look at the new piece.",
        "copy_prompt": "Write a short reveal post for Blood Crow.",
    },
    {
        "week": 1, "day": "Thursday", "date": "2026-05-09",
        "tier": "paid", "type": "Behind-the-scenes",
        "title": "Process notes: Blood Crow", "description": "A look at how it came together.",
        "copy_prompt": "Describe the process for patrons.",
    },
    {
        "week": 2, "day": "Monday", "date": "2026-05-13",
        "tier": "free", "type": "Personal update",
        "title": "What's coming in June", "description": "Plans for next month.",
        "copy_prompt": "Write a friendly update for followers.",
    },
]


def _mock_ai_response(posts=None):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(posts or SAMPLE_POSTS))]
    return mock_response


def test_load_works_from_file(tmp_path):
    data = [{"title": f"Art {i}", "tags": ["wildlife"], "story": "A piece."} for i in range(5)]
    src = tmp_path / "search.json"
    src.write_text(json.dumps(data), encoding="utf-8")
    works = _load_works(str(src))
    assert len(works) == 5
    assert works[0]["title"] == "Art 0"


def test_load_works_limits_to_30(tmp_path):
    data = [{"title": f"Art {i}", "tags": [], "story": ""} for i in range(50)]
    src = tmp_path / "search.json"
    src.write_text(json.dumps(data), encoding="utf-8")
    works = _load_works(str(src))
    assert len(works) == 30


def test_render_markdown_structure():
    plan = {"weeks": 2, "posts_per_week": 2, "tiers": "all", "posts": SAMPLE_POSTS}
    md = _render_markdown(plan)
    assert "## Week 1" in md
    assert "## Week 2" in md
    assert "Blood Crow" in md
    assert "🔓 Free" in md
    assert "🔒 Paid" in md
    assert "Write prompt:" in md


def test_render_markdown_has_header():
    plan = {"weeks": 1, "posts_per_week": 1, "tiers": "free", "posts": SAMPLE_POSTS[:1]}
    md = _render_markdown(plan)
    assert "# Patreon Content Plan" in md


def test_cli_markdown_output(tmp_path):
    data = [{"title": "Wolf Spirit", "tags": ["wildlife"], "story": "A wolf."}]
    src = tmp_path / "search.json"
    src.write_text(json.dumps(data), encoding="utf-8")

    with patch("arttools.patreon_plan._client") as mock_client:
        mock_client.return_value.messages.create.return_value = _mock_ai_response()
        runner = CliRunner()
        result = runner.invoke(cli, ["--source", str(src), "--weeks", "2", "--posts-per-week", "2"])

    assert result.exit_code == 0, result.output
    assert "Week 1" in result.output
    assert "Blood Crow" in result.output


def test_cli_json_output(tmp_path):
    data = [{"title": "Wolf Spirit", "tags": ["wildlife"], "story": "A wolf."}]
    src = tmp_path / "search.json"
    src.write_text(json.dumps(data), encoding="utf-8")

    with patch("arttools.patreon_plan._client") as mock_client:
        mock_client.return_value.messages.create.return_value = _mock_ai_response()
        runner = CliRunner()
        result = runner.invoke(cli, ["--source", str(src), "--format", "json"])

    assert result.exit_code == 0, result.output
    start = result.output.find("{")
    data_out = json.loads(result.output[start:])
    assert "posts" in data_out
    assert isinstance(data_out["posts"], list)


def test_cli_writes_file(tmp_path):
    data = [{"title": "Wolf Spirit", "tags": ["wildlife"], "story": "A wolf."}]
    src = tmp_path / "search.json"
    src.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "plan.md"

    with patch("arttools.patreon_plan._client") as mock_client:
        mock_client.return_value.messages.create.return_value = _mock_ai_response()
        runner = CliRunner()
        result = runner.invoke(cli, ["--source", str(src), "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "Week 1" in out.read_text()


def test_cli_handles_malformed_ai_json(tmp_path):
    data = [{"title": "Art", "tags": [], "story": ""}]
    src = tmp_path / "search.json"
    src.write_text(json.dumps(data), encoding="utf-8")

    bad_response = MagicMock()
    bad_response.content = [MagicMock(text="Here is your plan! Not JSON at all.")]

    with patch("arttools.patreon_plan._client") as mock_client:
        mock_client.return_value.messages.create.return_value = bad_response
        runner = CliRunner()
        result = runner.invoke(cli, ["--source", str(src)])

    assert result.exit_code == 0


def test_cli_no_works_exits(tmp_path):
    src = tmp_path / "search.json"
    src.write_text("[]", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["--source", str(src)])
    assert result.exit_code != 0
