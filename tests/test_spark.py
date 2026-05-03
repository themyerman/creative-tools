"""Tests for daily-spark writing prompt generator."""
import json
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

from writingtools.spark import cli, _generate_prompts, _load_config, _build_genres
from writingtools.render import render_email
from click.testing import CliRunner


SAMPLE_PROMPTS = {
    "sf":      "The colony ship's navigator discovers the star charts were falsified before departure — and the planet they've been en route to for sixty years doesn't exist.",
    "fantasy": "The executioner's blade has broken on the necks of three supposedly guilty men this week. The fourth condemned is a child.",
    "western": "The treaty surveyor arrives in a town that doesn't appear on any federal map, speaking a language the locals recognize from their grandparents.",
    "mystery": "The victim was found in a locked library with a lit cigar, a half-eaten meal, and every clock in the room stopped at different times.",
}

SAMPLE_CONFIG = {
    "writer_profile": {
        "background": "Test author background.",
        "influences": ["Influence A (note)", "Influence B (note)"],
    },
    "genres": {
        "sf": {
            "label": "Science Fiction",
            "icon": "🚀",
            "color": "#1a3a5c",
            "preferences": "Space opera.",
            "influences": ["Ursula K. Le Guin (depth)", "Brian Daley (energy)"],
        },
        "fantasy": {
            "label": "Fantasy",
            "icon": "⚔️",
            "color": "#2d1b4e",
            "preferences": "Grimdark.",
            "influences": ["Terry Pratchett (humour)", "Joe Abercrombie (realism)"],
        },
        "western": {
            "label": "Western",
            "icon": "🌵",
            "color": "#4a2c0a",
            "preferences": "Neo-western.",
            "influences": [],
        },
        "mystery": {
            "label": "Mystery",
            "icon": "🕵️",
            "color": "#1a2a1a",
            "preferences": "Neo-noir.",
            "influences": [],
        },
    },
}


def _mock_client(prompts=SAMPLE_PROMPTS):
    mock = MagicMock()
    mock.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps(prompts)))]
    )
    return mock


# ── config loading ────────────────────────────────────────────────────────────

def test_load_config_bundled():
    config = _load_config(None)
    assert "genres" in config
    assert "sf" in config["genres"]
    assert "writer_profile" in config


def test_load_config_custom_file(tmp_path):
    import yaml
    cfg_file = tmp_path / "my.yaml"
    cfg_file.write_text(yaml.dump(SAMPLE_CONFIG), encoding="utf-8")
    config = _load_config(str(cfg_file))
    assert config["genres"]["sf"]["label"] == "Science Fiction"


def test_load_config_env_var(tmp_path, monkeypatch):
    import yaml
    cfg_file = tmp_path / "env.yaml"
    cfg_file.write_text(yaml.dump(SAMPLE_CONFIG), encoding="utf-8")
    monkeypatch.setenv("SPARK_CONFIG", str(cfg_file))
    config = _load_config(None)
    assert "sf" in config["genres"]


def test_build_genres_merges_influences():
    genres = _build_genres(SAMPLE_CONFIG)
    assert "Le Guin" in genres["sf"]["preferences"]
    assert genres["sf"]["label"] == "Science Fiction"


def test_build_genres_no_influences():
    config = {
        "genres": {
            "mystery": {
                "label": "Mystery", "icon": "🕵️", "color": "#000",
                "preferences": "Neo-noir.", "influences": [],
            }
        }
    }
    genres = _build_genres(config)
    assert "Tonal influences" not in genres["mystery"]["preferences"]


# ── render tests ──────────────────────────────────────────────────────────────

def test_render_email_contains_all_genres():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(SAMPLE_PROMPTS, genres)
    for g in genres.values():
        assert g["label"] in html
        assert g["icon"] in html


def test_render_email_contains_prompt_text():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(SAMPLE_PROMPTS, genres)
    assert "navigator" in html
    assert "executioner" in html
    assert "surveyor" in html
    assert "locked library" in html


def test_render_email_is_valid_html():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(SAMPLE_PROMPTS, genres)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_render_email_single_genre():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email({"sf": SAMPLE_PROMPTS["sf"]}, {"sf": genres["sf"]})
    assert "Science Fiction" in html
    assert "Fantasy" not in html


# ── generation tests ──────────────────────────────────────────────────────────

def test_generate_prompts_returns_all_genres():
    genres = _build_genres(SAMPLE_CONFIG)
    with patch("writingtools.spark._github_client", return_value=_mock_client()):
        result = _generate_prompts(genres, "gpt-4o-mini", SAMPLE_CONFIG["writer_profile"])

    assert set(result.keys()) == {"sf", "fantasy", "western", "mystery"}
    assert "navigator" in result["sf"]


def test_generate_prompts_writer_profile_in_prompt():
    genres = _build_genres(SAMPLE_CONFIG)
    with patch("writingtools.spark._github_client", return_value=_mock_client()) as mock_gh:
        mock_client = _mock_client()
        with patch("writingtools.spark._github_client", return_value=mock_client):
            _generate_prompts(genres, "gpt-4o-mini", SAMPLE_CONFIG["writer_profile"])
        call_args = mock_client.chat.completions.create.call_args
        prompt_text = call_args[1]["messages"][0]["content"]
        assert "Test author background" in prompt_text
        assert "Influence A" in prompt_text


def test_generate_prompts_handles_markdown_fence():
    fenced = "```json\n" + json.dumps(SAMPLE_PROMPTS) + "\n```"
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=fenced))]
    )
    genres = _build_genres(SAMPLE_CONFIG)
    with patch("writingtools.spark._github_client", return_value=mock_client):
        result = _generate_prompts(genres, "gpt-4o-mini")

    assert "navigator" in result["sf"]


def test_generate_prompts_returns_empty_on_error():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API error")
    genres = _build_genres(SAMPLE_CONFIG)
    with patch("writingtools.spark._github_client", return_value=mock_client):
        result = _generate_prompts(genres, "gpt-4o-mini")

    assert result == {}


# ── CLI tests ─────────────────────────────────────────────────────────────────

def test_cli_prints_prompts():
    with patch("writingtools.spark._github_client", return_value=_mock_client()), \
         patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG):
        result = CliRunner().invoke(cli, [])

    assert result.exit_code == 0, result.output
    assert "navigator" in result.output
    assert "executioner" in result.output


def test_cli_single_genre():
    sf_only = {"sf": SAMPLE_PROMPTS["sf"]}
    with patch("writingtools.spark._github_client", return_value=_mock_client(sf_only)), \
         patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG):
        result = CliRunner().invoke(cli, ["--genre", "sf"])

    assert result.exit_code == 0, result.output
    assert "navigator" in result.output


def test_cli_unknown_genre_exits():
    with patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG):
        result = CliRunner().invoke(cli, ["--genre", "horror"])

    assert result.exit_code != 0


def test_cli_print_html():
    with patch("writingtools.spark._github_client", return_value=_mock_client()), \
         patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG):
        result = CliRunner().invoke(cli, ["--print-html"])

    assert result.exit_code == 0, result.output
    assert "<!DOCTYPE html>" in result.output


def test_cli_no_prompts_exits():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("fail")
    with patch("writingtools.spark._github_client", return_value=mock_client), \
         patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG):
        result = CliRunner().invoke(cli, [])

    assert result.exit_code != 0


def test_cli_email_calls_send():
    with patch("writingtools.spark._github_client", return_value=_mock_client()), \
         patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG), \
         patch("writingtools.spark.send") as mock_send:
        result = CliRunner().invoke(cli, ["--email"])

    assert result.exit_code == 0, result.output
    mock_send.assert_called_once()
    html_arg = mock_send.call_args[0][0]
    assert "navigator" in html_arg


def test_cli_custom_config_file(tmp_path):
    import yaml
    cfg_file = tmp_path / "custom.yaml"
    cfg_file.write_text(yaml.dump(SAMPLE_CONFIG), encoding="utf-8")

    with patch("writingtools.spark._github_client", return_value=_mock_client()):
        result = CliRunner().invoke(cli, ["--config", str(cfg_file)])

    assert result.exit_code == 0, result.output
