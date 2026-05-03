"""batch-resize CLI — resize a folder of images to web-ready sizes using sips."""
import subprocess
import shutil
import sys
from pathlib import Path

import click


PRESETS = {
    "web":   2400,   # full display image
    "thumb": 480,    # thumbnail / grid card
    "hero":  1600,   # hero / banner (wide crop)
    "small": 800,    # inline / preview
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".tif"}


@click.command()
@click.argument("source", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Output directory (default: <source>/resized)")
@click.option("--width", "-w", type=int, default=None,
              help="Max width in pixels (overrides --preset)")
@click.option("--preset", "-p", default="web", show_default=True,
              type=click.Choice(list(PRESETS)),
              help="Size preset: web=2400px, thumb=480px, hero=1600px, small=800px")
@click.option("--format", "-f", "fmt",
              type=click.Choice(["jpg", "png", "original"]), default="jpg", show_default=True,
              help="Output format")
@click.option("--quality", "-q", default=85, show_default=True,
              help="JPEG quality (1-100, ignored for PNG)")
@click.option("--dry-run", is_flag=True, help="Show what would be done without writing files")
def cli(source, output, width, preset, fmt, quality, dry_run):
    """Resize all images in a directory to web-ready sizes using macOS sips.

    Examples:\n
      batch-resize ~/art/originals\n
      batch-resize ~/art/originals --preset thumb --output ~/art/thumbs\n
      batch-resize ~/art/ --width 1200 --format png\n
      batch-resize ~/art/ --preset web --dry-run
    """
    max_width = width if width is not None else PRESETS[preset]

    dest = output or (source / "resized")

    files = sorted(f for f in source.iterdir() if f.suffix.lower() in IMAGE_EXTS)

    if not files:
        click.echo(f"No images found in {source}", err=True)
        sys.exit(1)

    click.echo(f"\n  {len(files)} images → {dest}  (max {max_width}px wide, {fmt})\n", err=True)

    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    ok = skipped = 0
    for f in files:
        out_ext = f".{fmt}" if fmt != "original" else f.suffix.lower()
        out_name = f.stem + out_ext
        out_path = dest / out_name

        if dry_run:
            click.echo(f"  [dry-run] {f.name} → {out_name}")
            continue

        try:
            # Copy to dest first (sips edits in place)
            shutil.copy2(f, out_path)

            # Resize: sips --resampleWidth only scales down, never up
            img_w = _get_width(f)
            if img_w is None or img_w > max_width:
                subprocess.run(
                    ["sips", "--resampleWidth", str(max_width), str(out_path)],
                    check=True, capture_output=True,
                )

            # Convert format if needed
            if fmt == "jpg" and f.suffix.lower() != ".jpg":
                subprocess.run(
                    ["sips", "-s", "format", "jpeg",
                     "-s", "formatOptions", str(quality),
                     str(out_path), "--out", str(out_path)],
                    check=True, capture_output=True,
                )
            elif fmt == "jpg":
                subprocess.run(
                    ["sips", "-s", "formatOptions", str(quality), str(out_path)],
                    check=True, capture_output=True,
                )
            elif fmt == "png" and f.suffix.lower() != ".png":
                subprocess.run(
                    ["sips", "-s", "format", "png",
                     str(out_path), "--out", str(out_path)],
                    check=True, capture_output=True,
                )

            size_kb = out_path.stat().st_size // 1024
            click.echo(f"  ✓  {f.name} → {out_name}  ({size_kb} KB)")
            ok += 1
        except Exception as e:
            click.echo(f"  ✗  {f.name}: {e}", err=True)
            skipped += 1

    if not dry_run:
        click.echo(f"\n  {ok} resized, {skipped} failed → {dest}\n", err=True)


def _get_width(path: Path) -> int | None:
    """Return image width via sips without loading into Python."""
    try:
        result = subprocess.run(
            ["sips", "--getProperty", "pixelWidth", str(path)],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.splitlines():
            if "pixelWidth" in line:
                return int(line.split(":")[-1].strip())
    except Exception:
        pass
    return None
