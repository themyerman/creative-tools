"""Tests for batch-resize utilities."""
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

from arttools.batch_resize import cli, _get_width
from click.testing import CliRunner


def _make_image_dir(tmp_path: Path, n: int = 3) -> Path:
    d = tmp_path / "originals"
    d.mkdir()
    for i in range(n):
        img = Image.new("RGB", (3000, 2000), color=(100 + i * 30, 50, 200))
        img.save(d / f"painting-{i + 1}.jpg")
    return d


def test_cli_dry_run_lists_files(tmp_path):
    d = _make_image_dir(tmp_path, n=3)
    result = CliRunner().invoke(cli, [str(d), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output
    assert "painting-1.jpg" in result.output


def test_cli_dry_run_creates_no_files(tmp_path):
    d = _make_image_dir(tmp_path, n=3)
    out = tmp_path / "resized"
    CliRunner().invoke(cli, [str(d), "--output", str(out), "--dry-run"])
    assert not out.exists()


def test_cli_resizes_images(tmp_path):
    d = _make_image_dir(tmp_path, n=2)
    out = tmp_path / "resized"

    with patch("arttools.batch_resize.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with patch("arttools.batch_resize._get_width", return_value=3000):
            result = CliRunner().invoke(cli, [str(d), "--output", str(out), "--width", "1200"])

    assert result.exit_code == 0, result.output
    # sips should have been called for each image
    assert mock_run.call_count >= 2


def test_cli_no_images_exits(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = CliRunner().invoke(cli, [str(empty)])
    assert result.exit_code != 0


def test_cli_default_output_is_resized_subdir(tmp_path):
    d = _make_image_dir(tmp_path, n=1)
    with patch("arttools.batch_resize.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with patch("arttools.batch_resize._get_width", return_value=3000):
            result = CliRunner().invoke(cli, [str(d)])
    assert result.exit_code == 0, result.output
    assert (d / "resized").exists()


def test_cli_preset_web(tmp_path):
    d = _make_image_dir(tmp_path, n=1)
    calls = []
    with patch("arttools.batch_resize.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        def capture(*args, **kwargs):
            calls.append(args[0])
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_run.side_effect = capture
        with patch("arttools.batch_resize._get_width", return_value=4000):
            CliRunner().invoke(cli, [str(d), "--preset", "web"])
    # Should have called sips with 2400
    assert any("2400" in str(c) for c in calls)


def test_cli_skips_resize_when_image_already_small(tmp_path):
    d = _make_image_dir(tmp_path, n=1)
    sips_calls = []
    with patch("arttools.batch_resize.subprocess.run") as mock_run:
        def capture(*args, **kwargs):
            sips_calls.append(args[0])
            return MagicMock(returncode=0, stdout="", stderr="")
        mock_run.side_effect = capture
        with patch("arttools.batch_resize._get_width", return_value=800):
            CliRunner().invoke(cli, [str(d), "--width", "2400"])
    # resampleWidth should NOT be called since image is already smaller
    assert not any("resampleWidth" in str(c) for c in sips_calls)
