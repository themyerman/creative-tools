"""Tests for next-painting utilities."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

from arttools.next_painting import cli, _scan_directory, _fetch_from_site
from click.testing import CliRunner


def _make_image_dir(tmp_path: Path, n: int = 5) -> Path:
    d = tmp_path / "paintings"
    d.mkdir()
    colors = [(200, 50, 50), (50, 200, 50), (50, 50, 200), (200, 200, 50), (200, 50, 200)]
    for i in range(n):
        img = Image.new("RGB", (100, 100), color=colors[i % len(colors)])
        img.save(d / f"painting-{i + 1}.png")
    return d


def test_scan_directory_returns_metadata(tmp_path):
    d = _make_image_dir(tmp_path, n=3)
    results = _scan_directory(d, max_count=10)
    assert len(results) == 3
    for r in results:
        assert "filename" in r
        assert "aspect" in r


def test_scan_directory_samples_when_over_limit(tmp_path):
    d = _make_image_dir(tmp_path, n=20)
    results = _scan_directory(d, max_count=5)
    assert len(results) <= 5


def test_scan_directory_missing(tmp_path):
    results = _scan_directory(tmp_path / "nonexistent", max_count=5)
    assert results == []


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


def test_cli_style_options(tmp_path):
    d = _make_image_dir(tmp_path, n=3)
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Gaps analysis: you need more wildlife.")]

    with patch("arttools.next_painting._client") as mock_client:
        mock_client.return_value.messages.create.return_value = mock_response
        runner = CliRunner()
        result = runner.invoke(cli, [str(d), "--style", "gaps"])

    assert result.exit_code == 0
