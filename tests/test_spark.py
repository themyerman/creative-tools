"""Tests for daily-spark writing prompt generator."""
import json
from unittest.mock import patch, MagicMock

from writingtools.spark import (
    cli, _generate_all, _generate_single_genres,
    _load_config, _build_genres, _assign_voices,
    _build_mashup, _collect_all_influences,
)
from writingtools.render import render_email
from click.testing import CliRunner


SAMPLE_PROMPTS = {
    "sf":      "The colony ship's navigator discovers the star charts were falsified.",
    "fantasy": "The executioner's blade has broken on three necks this week.",
    "western": "The treaty surveyor arrives in a town that doesn't appear on any federal map.",
    "mystery": "The victim was found in a locked library with every clock stopped at different times.",
}

SAMPLE_VOICES = {
    "vanilla": "Crisp, evocative prose.",
    "trailer": "In a world where... everything is at stake.",
    "campfire": "Slow, oral, present tense.",
    "pulp":    "Lurid, punchy, the city is dangerous.",
    "satiric": "Wit as a weapon, the absurd used to expose the serious.",
}

SAMPLE_CONFIG = {
    "voices": SAMPLE_VOICES,
    "writer_profile": {
        "background": "Test author background.",
        "influences": ["Influence A (note)", "Influence B (note)"],
    },
    "genres": {
        "sf": {
            "label": "Science Fiction", "icon": "🚀", "color": "#1a3a5c",
            "preferences": "Space opera.",
            "influences": ["Ursula K. Le Guin (depth)", "Brian Daley (energy)"],
        },
        "fantasy": {
            "label": "Fantasy", "icon": "⚔️", "color": "#2d1b4e",
            "preferences": "Grimdark.",
            "influences": ["Terry Pratchett (humour)", "Joe Abercrombie (realism)"],
        },
        "western": {
            "label": "Western", "icon": "🌵", "color": "#4a2c0a",
            "preferences": "Neo-western.", "influences": [],
        },
        "mystery": {
            "label": "Mystery", "icon": "🕵️", "color": "#1a2a1a",
            "preferences": "Neo-noir.", "influences": [],
        },
    },
}

SAMPLE_MASHUP_META = {
    "genre_keys": ["sf", "fantasy"],
    "genre_labels": ["Science Fiction", "Fantasy"],
    "genre_icons": ["🚀", "⚔️"],
    "genre_prefs": ["Space opera prefs.", "Grimdark prefs."],
    "voice_name": "campfire",
    "voice_instruction": "Slow, oral, present tense.",
    "influence": "Ursula K. Le Guin (depth)",
}


def _mock_client(response=None):
    if response is None:
        response = SAMPLE_PROMPTS
    mock = MagicMock()
    mock.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps(response)))]
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


# ── voice assignment ──────────────────────────────────────────────────────────

def test_assign_voices_fixed():
    genres = _build_genres(SAMPLE_CONFIG)
    result = _assign_voices(genres, "trailer", SAMPLE_VOICES)
    assert all(v == SAMPLE_VOICES["trailer"] for v in result.values())


def test_assign_voices_random_no_repeats():
    genres = _build_genres(SAMPLE_CONFIG)
    result = _assign_voices(genres, "random", SAMPLE_VOICES)
    assert len(set(result.values())) == len(result)


def test_assign_voices_falls_back_to_vanilla():
    genres = _build_genres(SAMPLE_CONFIG)
    result = _assign_voices(genres, "nonexistent", SAMPLE_VOICES)
    assert all(v == SAMPLE_VOICES["vanilla"] for v in result.values())


# ── mashup / wildcard ─────────────────────────────────────────────────────────

def test_collect_all_influences():
    influences = _collect_all_influences(SAMPLE_CONFIG)
    assert any("Influence A" in i for i in influences)
    assert len(influences) > 0


def test_build_mashup_picks_two_distinct_genres():
    genres = _build_genres(SAMPLE_CONFIG)
    wc = _build_mashup(SAMPLE_CONFIG, genres, SAMPLE_VOICES)
    assert len(wc["genre_keys"]) == 2
    assert wc["genre_keys"][0] != wc["genre_keys"][1]
    assert wc["voice_name"] in SAMPLE_VOICES
    assert len(wc["influence"]) > 0


# ── render tests ──────────────────────────────────────────────────────────────

def test_render_email_contains_genre_prompts():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(SAMPLE_PROMPTS, genres)
    for g in genres.values():
        assert g["label"] in html
    assert "navigator" in html


def test_render_email_is_valid_html():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(SAMPLE_PROMPTS, genres)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_render_email_shows_voice_name():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(SAMPLE_PROMPTS, genres, {k: "trailer" for k in genres})
    assert "trailer" in html


def test_render_email_shows_mashups():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(
        {}, genres,
        mashup_metas=[SAMPLE_MASHUP_META],
        mashup_prompts=["A ranger from the future patrols a dying forest."],
    )
    assert "Mashup" in html
    assert "Science Fiction" in html
    assert "Fantasy" in html
    assert "Le Guin" in html
    assert "ranger from the future" in html


def test_render_email_multiple_mashups():
    genres = _build_genres(SAMPLE_CONFIG)
    metas = [SAMPLE_MASHUP_META, SAMPLE_MASHUP_META]
    prompts_list = ["First mashup prompt.", "Second mashup prompt."]
    html = render_email({}, genres, mashup_metas=metas, mashup_prompts=prompts_list)
    assert html.count("⚡ Mashup") == 2


# ── generation tests ──────────────────────────────────────────────────────────

def test_generate_all_returns_mashups_and_genres():
    genres = _build_genres(SAMPLE_CONFIG)
    response = {
        "__mashup_0__": "A knight finds a spacecraft in the forest.",
        "sf": SAMPLE_PROMPTS["sf"],
    }
    with patch("writingtools.spark._github_client", return_value=_mock_client(response)):
        mashup_prompts, genre_prompts = _generate_all(
            [SAMPLE_MASHUP_META], {"sf": genres["sf"]},
            "gpt-4o-mini", SAMPLE_CONFIG["writer_profile"],
        )
    assert len(mashup_prompts) == 1
    assert "knight" in mashup_prompts[0]
    assert "navigator" in genre_prompts["sf"]


def test_generate_all_handles_error():
    genres = _build_genres(SAMPLE_CONFIG)
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("fail")
    with patch("writingtools.spark._github_client", return_value=mock_client):
        mashup_prompts, genre_prompts = _generate_all(
            [SAMPLE_MASHUP_META], {}, "gpt-4o-mini"
        )
    assert mashup_prompts == []
    assert genre_prompts == {}


def test_generate_single_genres():
    genres = _build_genres(SAMPLE_CONFIG)
    with patch("writingtools.spark._github_client", return_value=_mock_client()):
        result = _generate_single_genres({"sf": genres["sf"]}, "gpt-4o-mini")
    assert "sf" in result


# ── CLI tests ─────────────────────────────────────────────────────────────────

def test_cli_default_generates_mashups():
    response = {f"__mashup_{i}__": f"Mashup prompt {i}." for i in range(3)}
    with patch("writingtools.spark._github_client", return_value=_mock_client(response)), \
         patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG):
        result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0, result.output
    assert "Mashup prompt" in result.output


def test_cli_single_genre_mode():
    with patch("writingtools.spark._github_client", return_value=_mock_client({"sf": SAMPLE_PROMPTS["sf"]})), \
         patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG):
        result = CliRunner().invoke(cli, ["--genre", "sf"])
    assert result.exit_code == 0, result.output
    assert "navigator" in result.output


def test_cli_unknown_genre_exits():
    with patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG):
        result = CliRunner().invoke(cli, ["--genre", "horror"])
    assert result.exit_code != 0


def test_cli_print_html():
    response = {"__mashup_0__": "A mashup prompt.", "__mashup_1__": "Another.", "__mashup_2__": "Third."}
    with patch("writingtools.spark._github_client", return_value=_mock_client(response)), \
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


def test_cli_custom_config_file(tmp_path):
    import yaml
    cfg_file = tmp_path / "custom.yaml"
    cfg_file.write_text(yaml.dump(SAMPLE_CONFIG), encoding="utf-8")
    response = {f"__mashup_{i}__": f"Mashup {i}." for i in range(3)}
    with patch("writingtools.spark._github_client", return_value=_mock_client(response)):
        result = CliRunner().invoke(cli, ["--config", str(cfg_file)])
    assert result.exit_code == 0, result.output
