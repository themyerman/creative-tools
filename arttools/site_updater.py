"""Update search.json, feed.xml, cart.js, and 404.html in the myerman-art repo."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import SEARCH_JSON, FEED_XML, CART_JS, PAGE_404, SITE_BASE_URL


def update_search(slug: str, title: str, tags: list[str], description: str, date: str) -> bool:
    """Prepend a new entry to search.json. Returns True if added, False if slug already exists."""
    data = json.loads(SEARCH_JSON.read_text(encoding="utf-8"))

    if any(item["slug"] == slug for item in data):
        return False

    data.insert(0, {
        "slug": slug,
        "title": title,
        "tags": tags,
        "story": description,
        "date": date,
    })

    SEARCH_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def update_feed(slug: str, title: str, description: str) -> bool:
    """Prepend a new <item> to feed.xml. Returns True if added, False if already present."""
    xml = FEED_XML.read_text(encoding="utf-8")

    url = f"{SITE_BASE_URL}/prints/{slug}/"
    if url in xml:
        return False

    pub_date = datetime.now(timezone.utc).strftime("%a, %d %b %Y 12:00:00 +0000")
    thumb_url = f"{SITE_BASE_URL}/prints/{slug}/{slug}-thumb.jpg"

    item = (
        f'\n  <item>\n'
        f'    <title>{_escape(title)}</title>\n'
        f'    <link>{url}</link>\n'
        f'    <guid isPermaLink="true">{url}</guid>\n'
        f'    <pubDate>{pub_date}</pubDate>\n'
        f'    <description>{_escape(description)}</description>\n'
        f'    <enclosure url="{thumb_url}" type="image/jpeg" length="0"/>\n'
        f'  </item>'
    )

    xml = re.sub(r'(\n  <item>)', item + r'\1', xml, count=1)
    FEED_XML.write_text(xml, encoding="utf-8")
    return True


def update_cart_js(sku: str, size_key: str, slug: str) -> bool:
    """Add SKU to SKU_TO_SIZE (and SKU_TO_SLUG if needed) in cart.js.

    Returns True if added, False if SKU already present.
    size_key is the publish-print size string, e.g. '12x12'.
    """
    content = CART_JS.read_text(encoding="utf-8")

    if f"'{sku}':" in content or f'"{sku}":' in content:
        return False

    # Convert size key to cart.js display format: '12x12' → '12×12'
    size_display = size_key.replace("x", "×")

    # Insert into SKU_TO_SIZE before its closing  };
    # Anchor: the  };  is followed by a blank line and the SKU_TO_SLUG comment
    sku_size_marker = "\n  };\n\n  // Fallback map"
    idx = content.find(sku_size_marker)
    if idx == -1:
        return False

    new_size_line = f"\n    '{sku}': '{size_display}',"
    content = content[:idx] + new_size_line + content[idx:]

    # Insert into SKU_TO_SLUG if the slug differs from sku.lower()
    if slug != sku.lower():
        # After inserting into SKU_TO_SIZE, find SKU_TO_SLUG's closing  };
        # Its anchor: it's followed by a blank line and  function getCart
        sku_slug_marker = "\n  };\n\n  function getCart"
        idx2 = content.find(sku_slug_marker)
        if idx2 != -1:
            new_slug_line = f"\n    '{sku}':   '{slug}',"
            content = content[:idx2] + new_slug_line + content[idx2:]

    CART_JS.write_text(content, encoding="utf-8")
    return True


def update_404(slug: str, title: str) -> bool:
    """Add a print slug+title to the random-prints array in 404.html.

    Returns True if added, False if already present.
    """
    content = PAGE_404.read_text(encoding="utf-8")

    if f'"slug": "{slug}"' in content or f'slug: "{slug}"' in content:
        return False

    # The array closes with        ]; (8 spaces)
    closing = "\n        ];"
    idx = content.find(closing)
    if idx == -1:
        return False

    new_entry = f'\n          {{ slug: "{slug}",  title: "{title}" }},'
    content = content[:idx] + new_entry + content[idx:]

    PAGE_404.write_text(content, encoding="utf-8")
    return True


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
