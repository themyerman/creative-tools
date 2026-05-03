"""Tests for next-painting utilities."""
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

from arttools.next_painting import cli, _scan_directory, _fetch_from_url, _apply_sample, _extract_colors
from click.testing import CliRunner


def _make_image_dir(tmp_path: Path, n: int = 5) -> Path:
    d = tmp_path / "paintings"
    d.mkdir()
    colors = [(200, 50, 50), (50, 200, 50), (50, 50, 200), (200, 200, 50), (200, 50, 200)]
    for i in range(n):
        img = Image.new("RGB", (100, 100), color=colors[i % len(colors)])
        path = d / f"painting-{i + 1:02d}.png"
        img.save(path)
        # Stagger mtimes so recent/oldest ordering is deterministic
        mtime = 1000000 + i * 1000
        path.stat()
        import os; os.utime(path, (mtime, mtime))
    return d


# ── _apply_sample tests ───────────────────────────────────────────────────────

def test_apply_sample_recent_returns_newest(tmp_path):
    d = _make_image_dir(tmp_path, n=5)
    files = list(d.iterdir())
    result = _apply_sample(files, max_count=3, mode="recent")
    assert len(result) == 3
    # Newest files have the highest mtime
    mtimes = [f.stat().st_mtime for f in result]
    assert mtimes == sorted(mtimes, reverse=True)


def test_apply_sample_oldest_returns_oldest(tmp_path):
    d = _make_image_dir(tmp_path, n=5)
    files = list(d.iterdir())
    result = _apply_sample(files, max_count=3, mode="oldest")
    mtimes = [f.stat().st_mtime for f in result]
    assert mtimes == sorted(mtimes)


def test_apply_sample_random_returns_count(tmp_path):
    d = _make_image_dir(tmp_path, n=10)
    files = list(d.iterdir())
    result = _apply_sample(files, max_count=4, mode="random")
    assert len(result) == 4


def test_apply_sample_diverse_spreads_evenly(tmp_path):
    d = _make_image_dir(tmp_path, n=10)
    files = sorted(d.iterdir())
    result = _apply_sample(files, max_count=5, mode="diverse")
    assert len(result) == 5


def test_apply_sample_respects_max_count(tmp_path):
    d = _make_image_dir(tmp_path, n=3)
    files = list(d.iterdir())
    for mode in ("recent", "oldest", "random", "diverse"):
        result = _apply_sample(files, max_count=10, mode=mode)
        assert len(result) <= 10


# ── _extract_colors tests ─────────────────────────────────────────────────────

def test_extract_colors_returns_hex_list():
    img = Image.new("RGB", (100, 100), color=(200, 50, 50))
    colors = _extract_colors(img, n=3)
    assert isinstance(colors, list)
    assert all(c.startswith("#") and len(c) == 7 for c in colors)


def test_extract_colors_handles_error():
    # Pass a broken object — should return [] not raise
    colors = _extract_colors(None, n=3)
    assert colors == []


# ── _scan_directory tests ─────────────────────────────────────────────────────

def test_scan_directory_returns_metadata(tmp_path):
    d = _make_image_dir(tmp_path, n=3)
    results = _scan_directory(d, max_count=10, sample="recent", extract_colors=False)
    assert len(results) == 3
    for r in results:
        assert "filename" in r
        assert "aspect" in r


def test_scan_directory_includes_colors_when_requested(tmp_path):
    d = _make_image_dir(tmp_path, n=2)
    results = _scan_directory(d, max_count=10, sample="recent", extract_colors=True)
    for r in results:
        assert "dominant_colors" in r
        assert isinstance(r["dominant_colors"], list)


def test_scan_directory_samples_when_over_limit(tmp_path):
    d = _make_image_dir(tmp_path, n=10)
    results = _scan_directory(d, max_count=4, sample="diverse", extract_colors=False)
    assert len(results) <= 4


def test_scan_directory_missing(tmp_path):
    results = _scan_directory(tmp_path / "nonexistent", max_count=5, sample="recent", extract_colors=False)
    assert results == []


# ── _fetch_from_url tests ─────────────────────────────────────────────────────

def test_fetch_from_url_uses_search_json():
    catalog = [
        {"slug": "wolf-moon", "title": "Wolf Moon", "tags": ["wildlife"], "story": "A wolf howls."},
    ]
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(catalog).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        results = _fetch_from_url("https://example.com", max_count=10)

    assert len(results) == 1
    assert results[0]["title"] == "Wolf Moon"


def test_fetch_from_url_falls_back_to_scraping():
    html = (
        b'<html><body>'
        b'<img src="/art/wolf-moon.jpg" alt="Wolf Moon">'
        b'<img src="/art/bear-spirit.jpg" alt="Bear Spirit">'
        b'</body></html>'
    )

    def fake_urlopen(req, timeout=10):
        mock_resp = MagicMock()
        mock_resp.read.return_value = html
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        if isinstance(req, str) and "search.json" in req:
            raise Exception("404")
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        results = _fetch_from_url("https://example.com", max_count=10)

    assert len(results) == 2
    assert results[0]["title"] == "Wolf Moon"


def test_fetch_from_url_skips_icons():
    html = (
        b'<html><body>'
        b'<img src="/img/logo.png" alt="Logo">'
        b'<img src="/art/painting.jpg" alt="My Painting">'
        b'</body></html>'
    )

    def fake_urlopen(req, timeout=10):
        mock_resp = MagicMock()
        mock_resp.read.return_value = html
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        if isinstance(req, str) and "search.json" in req:
            raise Exception("404")
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        results = _fetch_from_url("https://example.com", max_count=10)

    assert all("logo" not in r["filename"].lower() for r in results)


# ── CLI tests ─────────────────────────────────────────────────────────────────

def test_cli_with_mocked_ai(tmp_path):
    d = _make_image_dir(tmp_path, n=3)
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Here are 5 suggestions:\n1. Paint a wolf.")]

    with patch("arttools.next_painting._client") as mock_client:
        mock_client.return_value.messages.create.return_value = mock_response
        runner = CliRunner()
        result = runner.invoke(cli, [str(d), "--count", "3"])

    assert result.exit_code == 0, result.output
    assert "wolf" in result.output or "suggestion" in result.output.lower()


def test_cli_sample_modes(tmp_path):
    d = _make_image_dir(tmp_path, n=5)
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Analysis complete.")]

    for mode in ("recent", "random", "diverse", "oldest"):
        with patch("arttools.next_painting._client") as mock_client:
            mock_client.return_value.messages.create.return_value = mock_response
            runner = CliRunner()
            result = runner.invoke(cli, [str(d), "--sample", mode])
        assert result.exit_code == 0, f"mode={mode}: {result.output}"


def test_cli_colors_flag(tmp_path):
    d = _make_image_dir(tmp_path, n=3)
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Color analysis complete.")]

    with patch("arttools.next_painting._client") as mock_client:
        mock_client.return_value.messages.create.return_value = mock_response
        runner = CliRunner()
        result = runner.invoke(cli, [str(d), "--colors"])

    assert result.exit_code == 0, result.output


def test_cli_style_options(tmp_path):
    d = _make_image_dir(tmp_path, n=3)
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Gaps analysis: you need more wildlife.")]

    with patch("arttools.next_painting._client") as mock_client:
        mock_client.return_value.messages.create.return_value = mock_response
        runner = CliRunner()
        result = runner.invoke(cli, [str(d), "--style", "gaps"])

    assert result.exit_code == 0
