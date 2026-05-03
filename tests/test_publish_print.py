"""Tests for publish-print utilities."""
import json
import re
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from arttools.site_updater import update_search, update_feed, update_cart_js, update_404
from arttools.publish_print import cli
from click.testing import CliRunner


# ── site_updater tests ────────────────────────────────────────────────────────

def _make_search_json(tmp: Path, items: list) -> Path:
    p = tmp / "search.json"
    p.write_text(json.dumps(items, indent=2))
    return p


def _make_feed_xml(tmp: Path) -> Path:
    p = tmp / "feed.xml"
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        '  <channel>\n'
        '  <item>\n'
        '    <title>Existing Print</title>\n'
        '    <link>https://myerman.art/prints/existing/</link>\n'
        '  </item>\n'
        '  </channel>\n'
        '</rss>\n'
    )
    return p


def _make_cart_js(tmp: Path) -> Path:
    p = tmp / "cart.js"
    p.write_text(
        "(function () {\n"
        "  var SKU_TO_SIZE = {\n"
        "    'OLD-PRINT': '12×12',\n"
        "  };\n"
        "\n"
        "  // Fallback map for cart items saved before slug was stored\n"
        "  var SKU_TO_SLUG = {\n"
        "    'OLD-PRINT': 'old-print',\n"
        "  };\n"
        "\n"
        "  function getCart() { return []; }\n"
        "})();\n"
    )
    return p


def _make_404_html(tmp: Path) -> Path:
    p = tmp / "404.html"
    p.write_text(
        "<html><body><script>\n"
        "  var all = [\n"
        "          { slug: \"old-print\",  title: \"Old Print\" },\n"
        "        ];\n"
        "</script></body></html>\n"
    )
    return p


def test_update_search_adds_entry(tmp_path, monkeypatch):
    p = _make_search_json(tmp_path, [{"slug": "old", "title": "Old"}])
    monkeypatch.setattr("arttools.site_updater.SEARCH_JSON", p)
    result = update_search("new-print", "New Print", ["tag1"], "A story.", "2026-05-01")
    assert result is True
    data = json.loads(p.read_text())
    assert data[0]["slug"] == "new-print"
    assert data[0]["tags"] == ["tag1"]


def test_update_search_skips_duplicate(tmp_path, monkeypatch):
    p = _make_search_json(tmp_path, [{"slug": "existing", "title": "Existing"}])
    monkeypatch.setattr("arttools.site_updater.SEARCH_JSON", p)
    result = update_search("existing", "Existing", [], "story", "2026-05-01")
    assert result is False


def test_update_feed_adds_item(tmp_path, monkeypatch):
    p = _make_feed_xml(tmp_path)
    monkeypatch.setattr("arttools.site_updater.FEED_XML", p)
    result = update_feed("new-print", "New Print", "A description.")
    assert result is True
    xml = p.read_text()
    assert "new-print" in xml
    assert "New Print" in xml


def test_update_feed_skips_duplicate(tmp_path, monkeypatch):
    p = _make_feed_xml(tmp_path)
    monkeypatch.setattr("arttools.site_updater.FEED_XML", p)
    result = update_feed("existing", "Existing", "story")
    assert result is False


def test_update_cart_js_adds_sku(tmp_path, monkeypatch):
    p = _make_cart_js(tmp_path)
    monkeypatch.setattr("arttools.site_updater.CART_JS", p)
    result = update_cart_js("WOLF-MOON", "12x9", "wolf-moon")
    assert result is True
    content = p.read_text()
    assert "'WOLF-MOON': '12×9'" in content


def test_update_cart_js_adds_to_slug_map_when_differs(tmp_path, monkeypatch):
    p = _make_cart_js(tmp_path)
    monkeypatch.setattr("arttools.site_updater.CART_JS", p)
    update_cart_js("FUT-MOON", "12x12", "futurism-moon-landing")
    content = p.read_text()
    assert "'FUT-MOON'" in content
    assert "futurism-moon-landing" in content


def test_update_cart_js_skips_duplicate(tmp_path, monkeypatch):
    p = _make_cart_js(tmp_path)
    monkeypatch.setattr("arttools.site_updater.CART_JS", p)
    result = update_cart_js("OLD-PRINT", "12x12", "old-print")
    assert result is False


def test_update_cart_js_size_format(tmp_path, monkeypatch):
    p = _make_cart_js(tmp_path)
    monkeypatch.setattr("arttools.site_updater.CART_JS", p)
    update_cart_js("ABSTRACT-99", "9x12", "abstract-99")
    content = p.read_text()
    assert "'9×12'" in content


def test_update_404_adds_slug(tmp_path, monkeypatch):
    p = _make_404_html(tmp_path)
    monkeypatch.setattr("arttools.site_updater.PAGE_404", p)
    result = update_404("wolf-moon", "Wolf Moon")
    assert result is True
    content = p.read_text()
    assert 'slug: "wolf-moon"' in content
    assert 'title: "Wolf Moon"' in content


def test_update_404_skips_duplicate(tmp_path, monkeypatch):
    p = _make_404_html(tmp_path)
    monkeypatch.setattr("arttools.site_updater.PAGE_404", p)
    result = update_404("old-print", "Old Print")
    assert result is False


# ── CLI dry-run test ──────────────────────────────────────────────────────────

def test_cli_dry_run(tmp_path):
    """Dry run should produce output and exit cleanly without touching any files."""
    fake_png = tmp_path / "test.png"
    fake_png.write_bytes(b"\x89PNG\r\n\x1a\n")

    search = tmp_path / "search.json"
    search.write_text("[]")
    feed = tmp_path / "feed.xml"
    feed.write_text('<rss><channel>\n  <item><title>X</title><link>https://myerman.art/prints/x/</link></item>\n</channel></rss>')
    prints_dir = tmp_path / "prints"
    prints_dir.mkdir()

    with patch("arttools.publish_print.PRINTS_DIR", prints_dir), \
         patch("arttools.site_updater.SEARCH_JSON", search), \
         patch("arttools.site_updater.FEED_XML", feed), \
         patch("arttools.publish_print.generate_description", return_value=("A description.", ["tag"])):

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--file", str(fake_png),
            "--title", "Test Print",
            "--sku", "TEST-1",
            "--size", "12x12",
            "--prompt", "a test prompt",
            "--dry-run",
        ])

    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output.lower() or "DRY RUN" in result.output
    assert not list(prints_dir.iterdir())
