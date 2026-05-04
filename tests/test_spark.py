"""Tests for daily-spark writing prompt generator."""
import json
from unittest.mock import patch, MagicMock

from writingtools.spark import (
    cli, _generate_starters,
    _load_config, _build_genres, _assign_voices,
    _collect_all_influences, _sample_no_repeat,
)
from writingtools.render import render_email
from click.testing import CliRunner


SAMPLE_VOICES = {
    "vanilla": "Clear, unaffected prose.",
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

SAMPLE_CARDS = {
    "sf": {
        "protagonist": "Commander Yara Nkosi needs to reach the colony before the signal dies.",
        "antagonist":  "Admiral Crane wants to erase the colony's existence from every record.",
        "setting":     "A decaying orbital station above a planet no government will acknowledge.",
        "conflict":    "Only one of them can control what the colony knows — and neither can afford the other to survive.",
    },
    "fantasy": {
        "protagonist": "The hedge-witch Dael wants to unmake the treaty that erased her village.",
        "antagonist":  "The treaty-keeper Sorn wants the old order preserved at any cost.",
        "setting":     "A borderland where two dying empires share a river neither can cross.",
        "conflict":    "The treaty is the only thing keeping the war cold — and Dael's village is the price of peace.",
    },
}


def _mock_client(response=None):
    if response is None:
        response = SAMPLE_CARDS
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

def test_assign_voices_no_repeats():
    genres = _build_genres(SAMPLE_CONFIG)
    result = _assign_voices(list(genres.keys()), SAMPLE_VOICES)
    assert len(result) == len(genres)
    assert len(set(result.values())) == len(result)


def test_assign_voices_all_keys_covered():
    genres = _build_genres(SAMPLE_CONFIG)
    keys = list(genres.keys())
    result = _assign_voices(keys, SAMPLE_VOICES)
    assert set(result.keys()) == set(keys)


def test_assign_voices_values_from_pool():
    genres = _build_genres(SAMPLE_CONFIG)
    result = _assign_voices(list(genres.keys()), SAMPLE_VOICES)
    for v in result.values():
        assert v in SAMPLE_VOICES


# ── sampling helpers ──────────────────────────────────────────────────────────

def test_collect_all_influences():
    influences = _collect_all_influences(SAMPLE_CONFIG)
    assert any("Influence A" in i for i in influences)
    assert len(influences) > 0


def test_sample_no_repeat_under_pool():
    pool = ["a", "b", "c", "d", "e"]
    result = _sample_no_repeat(pool, 3)
    assert len(result) == 3
    assert len(set(result)) == 3


def test_sample_no_repeat_over_pool():
    pool = ["a", "b"]
    result = _sample_no_repeat(pool, 5)
    assert len(result) == 5


# ── render tests ──────────────────────────────────────────────────────────────

def test_render_email_is_valid_html():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(SAMPLE_CARDS, genres)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_render_email_contains_genre_labels():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(SAMPLE_CARDS, genres)
    assert "Science Fiction" in html
    assert "Fantasy" in html


def test_render_email_shows_story_sections():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(SAMPLE_CARDS, genres)
    assert "Protagonist" in html
    assert "Antagonist" in html
    assert "Setting" in html
    assert "Conflict" in html


def test_render_email_shows_card_content():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(SAMPLE_CARDS, genres)
    assert "Yara Nkosi" in html
    assert "hedge-witch" in html


def test_render_email_shows_voice():
    genres = _build_genres(SAMPLE_CONFIG)
    voice_map = {k: "campfire" for k in SAMPLE_CARDS}
    html = render_email(SAMPLE_CARDS, genres, voice_map=voice_map)
    assert "campfire" in html


def test_render_email_shows_influence():
    genres = _build_genres(SAMPLE_CONFIG)
    influence_map = {"sf": "Ursula K. Le Guin (depth)", "fantasy": "Terry Pratchett (humour)"}
    html = render_email(SAMPLE_CARDS, genres, influence_map=influence_map)
    assert "Le Guin" in html
    assert "Pratchett" in html


def test_render_email_no_mashup_remnants():
    genres = _build_genres(SAMPLE_CONFIG)
    html = render_email(SAMPLE_CARDS, genres)
    assert "wildcard" not in html
    assert "Mashup" not in html


# ── generation tests ──────────────────────────────────────────────────────────

def test_generate_starters_returns_cards():
    genres = _build_genres(SAMPLE_CONFIG)
    with patch("writingtools.spark._github_client", return_value=_mock_client()):
        result = _generate_starters(
            ["sf", "fantasy"], genres, "gpt-4o-mini",
            SAMPLE_CONFIG["writer_profile"],
            {"sf": "campfire", "fantasy": "pulp"},
            {"sf": "Le Guin", "fantasy": "Pratchett"},
        )
    assert "sf" in result
    assert "Yara Nkosi" in result["sf"]["protagonist"]
    assert "conflict" in result["sf"]
    assert "setting" in result["sf"]


def test_generate_starters_handles_error():
    genres = _build_genres(SAMPLE_CONFIG)
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("fail")
    with patch("writingtools.spark._github_client", return_value=mock_client):
        result = _generate_starters(["sf"], genres, "gpt-4o-mini")
    assert result == {}


# ── CLI tests ─────────────────────────────────────────────────────────────────

def test_cli_default_generates_three_cards():
    all_genres = list(SAMPLE_CONFIG["genres"].keys())
    selected = all_genres[:3]
    response = {k: SAMPLE_CARDS.get(k, {
        "protagonist": f"Hero of {k}.",
        "antagonist":  f"Villain of {k}.",
        "setting":     f"A place in {k}.",
        "conflict":    f"Stakes in {k}.",
    }) for k in selected}
    with patch("writingtools.spark._github_client", return_value=_mock_client(response)), \
         patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG), \
         patch("writingtools.spark.random.sample", side_effect=lambda pop, n: (selected if set(pop) == set(all_genres) else list(pop)[:n])):
        result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0, result.output
    assert "Protagonist" in result.output


def test_cli_single_genre_mode():
    with patch("writingtools.spark._github_client", return_value=_mock_client({"sf": SAMPLE_CARDS["sf"]})), \
         patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG):
        result = CliRunner().invoke(cli, ["--genre", "sf"])
    assert result.exit_code == 0, result.output
    assert "Yara Nkosi" in result.output


def test_cli_unknown_genre_exits():
    with patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG):
        result = CliRunner().invoke(cli, ["--genre", "horror"])
    assert result.exit_code != 0


def test_cli_print_html():
    response = {
        "sf": SAMPLE_CARDS["sf"],
        "fantasy": SAMPLE_CARDS["fantasy"],
        "western": {
            "protagonist": "A surveyor named Cole.",
            "antagonist":  "A cattleman named Rudd.",
            "setting":     "A sun-baked border town.",
            "conflict":    "Every line drawn is a death warrant.",
        },
    }
    with patch("writingtools.spark._github_client", return_value=_mock_client(response)), \
         patch("writingtools.spark._load_config", return_value=SAMPLE_CONFIG):
        result = CliRunner().invoke(cli, ["--print-html"])
    assert result.exit_code == 0, result.output
    assert "<!DOCTYPE html>" in result.output


def test_cli_no_cards_exits():
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
    all_genres = list(SAMPLE_CONFIG["genres"].keys())
    selected = all_genres[:3]
    response = {k: SAMPLE_CARDS.get(k, {
        "protagonist": f"Hero of {k}.",
        "antagonist":  f"Villain of {k}.",
        "setting":     f"A place in {k}.",
        "conflict":    f"Stakes in {k}.",
    }) for k in selected}
    with patch("writingtools.spark._github_client", return_value=_mock_client(response)), \
         patch("writingtools.spark.random.sample", side_effect=lambda pop, n: (selected if set(pop) == set(all_genres) else list(pop)[:n])):
        result = CliRunner().invoke(cli, ["--config", str(cfg_file)])
    assert result.exit_code == 0, result.output
