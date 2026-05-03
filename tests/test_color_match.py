"""Tests for color-match utilities."""
import json
from pathlib import Path
from PIL import Image

from arttools.color_match import cli, _similarity_score, _classify_colors, _color_distance, _hex_to_rgb
from click.testing import CliRunner


def _make_test_image(tmp_path: Path, color: tuple, name: str = "test.png") -> Path:
    """Create a test image dominated by color but with enough variation for quantization."""
    img = Image.new("RGB", (100, 100), color=color)
    # Add small regions of other colors so quantizer has distinct clusters to work with
    for x in range(10):
        for y in range(10):
            img.putpixel((x, y), (255 - color[0], 255 - color[1], 255 - color[2]))
    for x in range(10, 20):
        for y in range(10):
            img.putpixel((x, y), (color[0] // 2, color[1] // 2, color[2] // 2))
    p = tmp_path / name
    img.save(p)
    return p


# ── unit tests ────────────────────────────────────────────────────────────────

def test_hex_to_rgb():
    assert _hex_to_rgb("#ff0000") == (255, 0, 0)
    assert _hex_to_rgb("#000000") == (0, 0, 0)
    assert _hex_to_rgb("#ffffff") == (255, 255, 255)


def test_color_distance_identical():
    assert _color_distance("#ff0000", "#ff0000") == 0.0


def test_color_distance_opposite():
    d = _color_distance("#000000", "#ffffff")
    assert d > 400  # sqrt(3 * 255^2) ≈ 441


def test_similarity_score_identical_palettes():
    palette = [{"hex": "#ff0000", "frequency": 50}, {"hex": "#0000ff", "frequency": 50}]
    score = _similarity_score(palette, palette)
    assert score == 100


def test_similarity_score_very_different():
    a = [{"hex": "#000000", "frequency": 100}]
    b = [{"hex": "#ffffff", "frequency": 100}]
    score = _similarity_score(a, b)
    assert score < 50


def test_classify_colors_shared():
    a = [{"hex": "#ff0000", "frequency": 100}]
    b = [{"hex": "#fe0000", "frequency": 100}]  # nearly identical
    shared, only_a, only_b = _classify_colors(a, b, threshold=10)
    assert len(shared) == 1
    assert len(only_a) == 0
    assert len(only_b) == 0


def test_classify_colors_unique():
    a = [{"hex": "#ff0000", "frequency": 100}]
    b = [{"hex": "#0000ff", "frequency": 100}]  # completely different
    shared, only_a, only_b = _classify_colors(a, b, threshold=10)
    assert len(shared) == 0
    assert "#ff0000" in only_a
    assert "#0000ff" in only_b


# ── CLI tests ─────────────────────────────────────────────────────────────────

def test_cli_terminal_output(tmp_path):
    a = _make_test_image(tmp_path, (200, 50, 50), "a.png")
    b = _make_test_image(tmp_path, (200, 60, 50), "b.png")  # very similar
    result = CliRunner().invoke(cli, [str(a), str(b)])
    assert result.exit_code == 0, result.output
    assert "Similarity:" in result.output
    assert "/100" in result.output


def test_cli_json_output(tmp_path):
    a = _make_test_image(tmp_path, (200, 50, 50), "a.png")
    b = _make_test_image(tmp_path, (50, 50, 200), "b.png")
    result = CliRunner().invoke(cli, [str(a), str(b), "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "similarity" in data
    assert "palette_a" in data
    assert "palette_b" in data
    assert 0 <= data["similarity"] <= 100


def test_cli_similar_images_score_high(tmp_path):
    a = _make_test_image(tmp_path, (200, 50, 50), "a.png")
    b = _make_test_image(tmp_path, (205, 48, 52), "b.png")  # nearly identical color
    result = CliRunner().invoke(cli, [str(a), str(b), "--format", "json"])
    data = json.loads(result.output)
    assert data["similarity"] > 80


def test_cli_different_images_score_low(tmp_path):
    a = _make_test_image(tmp_path, (255, 0, 0), "a.png")    # pure red
    b = _make_test_image(tmp_path, (0, 0, 255), "b.png")    # pure blue
    result = CliRunner().invoke(cli, [str(a), str(b), "--format", "json"])
    data = json.loads(result.output)
    assert data["similarity"] < 70


def test_cli_color_count_option(tmp_path):
    a = _make_test_image(tmp_path, (200, 50, 50), "a.png")
    b = _make_test_image(tmp_path, (50, 200, 50), "b.png")
    result = CliRunner().invoke(cli, [str(a), str(b), "--colors", "3", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data["palette_a"]) == 3
    assert len(data["palette_b"]) == 3
