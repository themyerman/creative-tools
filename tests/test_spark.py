"""Tests for daily-spark writing prompt generator."""
import json
from unittest.mock import patch, MagicMock

from writingtools.spark import cli, GENRES, _generate_prompts
from writingtools.render import render_email
from click.testing import CliRunner


SAMPLE_PROMPTS = {
    "sf":      "The colony ship's navigator discovers the star charts were falsified before departure — and the planet they've been en route to for sixty years doesn't exist.",
    "fantasy": "The executioner's blade has broken on the necks of three supposedly guilty men this week. The fourth condemned is a child.",
    "western": "The treaty surveyor arrives in a town that doesn't appear on any federal map, speaking a language the locals recognize from their grandparents.",
    "mystery": "The victim was found in a locked library with a lit cigar, a half-eaten meal, and every clock in the room stopped at different times.",
}


# ── render tests ──────────────────────────────────────────────────────────────

def test_render_email_contains_all_genres():
    html = render_email(SAMPLE_PROMPTS, GENRES)
    for g in GENRES.values():
        assert g["label"] in html
        assert g["icon"] in html


def test_render_email_contains_prompt_text():
    html = render_email(SAMPLE_PROMPTS, GENRES)
    assert "navigator" in html
    assert "executioner" in html
    assert "surveyor" in html
    assert "locked library" in html


def test_render_email_is_valid_html():
    html = render_email(SAMPLE_PROMPTS, GENRES)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_render_email_single_genre():
    html = render_email({"sf": SAMPLE_PROMPTS["sf"]}, {"sf": GENRES["sf"]})
    assert "Science Fiction" in html
    assert "Fantasy" not in html


# ── generation tests ──────────────────────────────────────────────────────────

def test_generate_prompts_returns_all_genres():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps(SAMPLE_PROMPTS)))]
    )

    with patch("writingtools.spark._github_client", return_value=mock_client):
        result = _generate_prompts(GENRES, "openai/gpt-4o-mini")

    assert set(result.keys()) == {"sf", "fantasy", "western", "mystery"}
    assert "navigator" in result["sf"]


def test_generate_prompts_handles_markdown_fence():
    fenced = "```json\n" + json.dumps(SAMPLE_PROMPTS) + "\n```"
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=fenced))]
    )

    with patch("writingtools.spark._github_client", return_value=mock_client):
        result = _generate_prompts(GENRES, "openai/gpt-4o-mini")

    assert "navigator" in result["sf"]


def test_generate_prompts_returns_empty_on_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API error")

    with patch("writingtools.spark._github_client", return_value=mock_client):
        result = _generate_prompts(GENRES, "openai/gpt-4o-mini")

    assert result == {}


# ── CLI tests ─────────────────────────────────────────────────────────────────

def test_cli_prints_prompts():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps(SAMPLE_PROMPTS)))]
    )

    with patch("writingtools.spark._github_client", return_value=mock_client):
        result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0, result.output
    assert "navigator" in result.output
    assert "executioner" in result.output


def test_cli_single_genre():
    sf_only = {"sf": SAMPLE_PROMPTS["sf"]}
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps(sf_only)))]
    )

    with patch("writingtools.spark._github_client", return_value=mock_client):
        result = CliRunner().invoke(cli, ["--genre", "sf"])

    assert result.exit_code == 0, result.output
    assert "navigator" in result.output


def test_cli_print_html():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps(SAMPLE_PROMPTS)))]
    )

    with patch("writingtools.spark._github_client", return_value=mock_client):
        result = CliRunner().invoke(cli, ["--print-html"])

    assert result.exit_code == 0, result.output
    assert "<!DOCTYPE html>" in result.output


def test_cli_no_prompts_exits():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("fail")

    with patch("writingtools.spark._github_client", return_value=mock_client):
        result = CliRunner().invoke(cli, [])

    assert result.exit_code != 0


def test_cli_email_calls_send():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps(SAMPLE_PROMPTS)))]
    )

    with patch("writingtools.spark._github_client", return_value=mock_client), \
         patch("writingtools.spark.send") as mock_send:
        result = CliRunner().invoke(cli, ["--email"])

    assert result.exit_code == 0, result.output
    mock_send.assert_called_once()
    # Confirm the HTML passed to send contains prompt content
    html_arg = mock_send.call_args[0][0]
    assert "navigator" in html_arg
