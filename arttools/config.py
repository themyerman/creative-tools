import os
from pathlib import Path

# Path to the myerman-art repo — override with MYERMAN_ART_DIR env var
SITE_DIR = Path(os.environ.get("MYERMAN_ART_DIR", Path.home() / "Desktop/code/myerman-art"))

PRINTS_DIR    = SITE_DIR / "prints"
SEARCH_JSON   = SITE_DIR / "search.json"
FEED_XML      = SITE_DIR / "feed.xml"
CART_JS       = SITE_DIR / "js" / "cart.js"
PAGE_404      = SITE_DIR / "404.html"

SITE_BASE_URL = "https://myerman.art"
PRINT_PRICE   = 30
