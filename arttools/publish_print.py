"""publish-print CLI — add a new print to myerman.art in one command."""
import shutil
import subprocess
from datetime import date
from pathlib import Path

import click
from jinja2 import Environment, PackageLoader

from .config import PRINTS_DIR, PRINT_PRICE, SITE_BASE_URL
from .image_ops import optimize_print
from .ai_writer import generate_description
from .site_updater import update_search, update_feed, update_cart_js, update_404


SIZE_TO_DIMS = {
    "12x12": (864, 864),
    "12x9":  (864, 648),
    "9x12":  (648, 864),
    "18x12": (1296, 864),
    "4x6":   (288, 432),
    "4x4":   (288, 288),
}

SIZE_DISPLAY = {
    "12x12": "12×12″",
    "12x9":  "12×9″",
    "9x12":  "9×12″",
    "18x12": "18×12″",
    "4x6":   "4×6″",
    "4x4":   "4×4″",
}

# Approximate display image pixel dimensions (for img width/height attrs)
DISPLAY_PIXELS = {
    "12x12": (2400, 2400),
    "12x9":  (2400, 1800),
    "9x12":  (1800, 2400),
    "18x12": (2400, 1600),
    "4x6":   (1200, 1800),
    "4x4":   (1200, 1200),
}


@click.command()
@click.option("--file",  "-f", required=True, type=click.Path(exists=True, path_type=Path), help="Source PNG file")
@click.option("--title", "-t", required=True, help="Print title, e.g. 'Abstract 9'")
@click.option("--sku",   "-s", required=True, help="SKU, e.g. ABSTRACT-9")
@click.option("--size",  "-z", required=True, type=click.Choice(list(SIZE_TO_DIMS)), help="Print size in inches")
@click.option("--prompt","-p", required=True, help="Short description prompt for AI copy generation")
@click.option("--slug",        default=None,  help="URL slug (derived from title if omitted)")
@click.option("--price",       default=PRINT_PRICE, show_default=True, help="Price in USD")
@click.option("--dry-run",     is_flag=True,  help="Show what would happen without writing files")
def cli(file, title, sku, size, prompt, slug, price, dry_run):
    """Publish a new print to myerman.art — optimizes images, generates AI copy, updates site files."""

    if slug is None:
        slug = title.lower().replace(" ", "-").replace("'", "").replace(":", "")

    report = {"slug": slug, "title": title, "sku": sku, "size": size, "actions": []}

    click.echo(f"\n🎨  Publishing: {title} ({slug})\n")

    # ── 1. Generate AI description ────────────────────────────────────────────
    click.echo("  ✦  Generating description and tags via Claude...")
    if not dry_run:
        description, tags = generate_description(title, prompt, size)
        report["description"] = description
        report["tags"] = tags
        click.echo(f"     Description: {description[:80]}...")
        click.echo(f"     Tags: {', '.join(tags)}")
    else:
        description, tags = f"[AI description for {title}]", ["tag1", "tag2"]
    report["actions"].append("ai-description")

    # ── 2. Optimize images ────────────────────────────────────────────────────
    dest_dir = PRINTS_DIR / slug
    click.echo(f"\n  ✦  Optimizing images → {dest_dir}")
    if not dry_run:
        images = optimize_print(Path(file), dest_dir, slug)
        for variant, path in images.items():
            click.echo(f"     {variant}: {path.name}")
            report["actions"].append(f"image-{variant}")
    else:
        click.echo("     [dry-run: would create display.jpg, thumb.jpg, hero.jpg]")

    # ── 3. Render print page HTML ─────────────────────────────────────────────
    page_dir = PRINTS_DIR / slug
    page_path = page_dir / "index.html"
    click.echo(f"\n  ✦  Rendering print page → {page_path}")

    env = Environment(loader=PackageLoader("arttools", "templates"))
    template = env.get_template("print_page.html")
    disp_w, disp_h = DISPLAY_PIXELS.get(size, (2400, 2400))

    html = template.render(
        slug=slug,
        title=title,
        sku=sku,
        size=size,
        size_display=SIZE_DISPLAY.get(size, size),
        description=description,
        price=price,
        display_width=disp_w,
        display_height=disp_h,
    )

    if not dry_run:
        page_dir.mkdir(parents=True, exist_ok=True)
        page_path.write_text(html, encoding="utf-8")
        report["actions"].append("print-page")
    else:
        click.echo("     [dry-run: would write index.html]")

    # ── 4. Update search.json ─────────────────────────────────────────────────
    today = date.today().isoformat()
    click.echo(f"\n  ✦  Updating search.json")
    if not dry_run:
        added = update_search(slug, title, tags, description, today)
        status = "added" if added else "already present — skipped"
        click.echo(f"     {status}")
        if added:
            report["actions"].append("search-json")
    else:
        click.echo("     [dry-run: would prepend entry]")

    # ── 5. Update feed.xml ────────────────────────────────────────────────────
    click.echo(f"\n  ✦  Updating feed.xml")
    if not dry_run:
        added = update_feed(slug, title, description)
        status = "added" if added else "already present — skipped"
        click.echo(f"     {status}")
        if added:
            report["actions"].append("feed-xml")
    else:
        click.echo("     [dry-run: would prepend <item>]")

    # ── 6. Update cart.js ─────────────────────────────────────────────────────
    click.echo(f"\n  ✦  Updating js/cart.js")
    if not dry_run:
        added = update_cart_js(sku, size, slug)
        status = "added" if added else "already present — skipped"
        click.echo(f"     {status}")
        if added:
            report["actions"].append("cart-js")
    else:
        click.echo("     [dry-run: would add to SKU_TO_SIZE]")

    # ── 7. Update 404.html ────────────────────────────────────────────────────
    click.echo(f"\n  ✦  Updating 404.html")
    if not dry_run:
        added = update_404(slug, title)
        status = "added" if added else "already present — skipped"
        click.echo(f"     {status}")
        if added:
            report["actions"].append("404-html")
    else:
        click.echo("     [dry-run: would add to random-prints list]")

    # ── 8. Report ─────────────────────────────────────────────────────────────
    _print_report(report, slug, dry_run)


def _print_report(report: dict, slug: str, dry_run: bool) -> None:
    label = "DRY RUN — nothing written" if dry_run else "Done"
    click.echo(f"\n{'─'*50}")
    click.echo(f"  {label}")
    click.echo(f"{'─'*50}")
    click.echo(f"  Slug:    {report['slug']}")
    click.echo(f"  Title:   {report['title']}")
    click.echo(f"  SKU:     {report['sku']}")
    click.echo(f"  Size:    {report['size']}")
    if not dry_run:
        click.echo(f"\n  Actions completed:")
        for action in report["actions"]:
            click.echo(f"    ✓  {action}")
        click.echo(f"\n  Next steps:")
        click.echo(f"    1. Review prints/{slug}/index.html")
        click.echo(f"    2. git add + commit + push to publish")
    click.echo(f"{'─'*50}\n")
