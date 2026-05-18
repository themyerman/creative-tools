# artist-tools

AI-powered publishing and creative tools for independent artists.

Built for [myerman.art](https://myerman.art) — a portfolio of Indigenous digital art by Tom Myer.

---

## Tools

| Command | What it does |
|---------|-------------|
| `publish-print` | Publish a new print: optimize images, generate AI copy, update site files |
| `extract-palette` | Extract a color palette from an artwork image |
| `next-painting` | Analyze a body of work and suggest what to paint next |
| `patreon-plan` | Generate a multi-week Patreon content calendar from recent work |
| `image-describe` | Walk a folder of images and write a 2-3 sentence description of each (local Ollama, no API key) |

### Install

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...
export MYERMAN_ART_DIR=/path/to/myerman-art   # defaults to ~/Desktop/code/myerman-art
```

---

## publish-print

Automates adding a new print to the site: converts a source PNG into optimized web images, generates an artist statement and search tags via Claude, renders the print page HTML, and updates `search.json` and `feed.xml`.

### Usage

```bash
publish-print \
  --file ~/Desktop/new-art-for-site/png-archive/abstract-9.png \
  --title "Abstract 9" \
  --sku ABSTRACT-9 \
  --size 12x12 \
  --prompt "swirling earth tones, geometric patterns suggesting movement and transformation"
```

**Options:**

| Flag | Required | Description |
|------|----------|-------------|
| `--file` / `-f` | ✓ | Source PNG file |
| `--title` / `-t` | ✓ | Print title |
| `--sku` / `-s` | ✓ | SKU (e.g. `ABSTRACT-9`) |
| `--size` / `-z` | ✓ | `12x12`, `12x9`, `9x12`, `18x12`, `4x6`, `4x4` |
| `--prompt` / `-p` | ✓ | Short artist note — fed to Claude for copy generation |
| `--slug` | | URL slug (derived from title if omitted) |
| `--price` | | Price in USD (default: 30) |
| `--dry-run` | | Preview what would happen without writing files |

### What it does

1. **Generates AI copy** — sends your prompt to Claude (Haiku) and gets back a 2–4 sentence artist statement in Tom's voice, plus search tags
2. **Optimizes images** — converts PNG → `display.jpg` (2400px), `thumb.jpg` (480×480 square), `hero.jpg` (1600×900) using macOS `sips`
3. **Renders print page** — fills `templates/print_page.html` and writes `prints/[slug]/index.html`
4. **Updates search.json** — prepends the new print to the site search index
5. **Updates feed.xml** — prepends a new RSS item
6. **Prints a report** — lists completed actions and remaining manual steps

### After running

The tool reminds you of the two manual steps that remain:
- Add the SKU to `SKU_TO_SIZE` in `js/cart.js`
- Add the slug to the 404 page's random print list

Then `git add . && git commit && git push` to publish.

---

## extract-palette

Extracts a color palette from any artwork image — locally or from a URL. Optionally asks Claude to name each color and describe the mood.

### Usage

```bash
# Terminal output (default)
extract-palette blood-crow.png

# CSS custom properties
extract-palette blood-crow.png --format css --colors 6 --output palette.css

# JSON (pipeable)
extract-palette https://myerman.art/prints/blood-crow/display.jpg --format json --no-ai

# Skip AI naming
extract-palette my-painting.png --no-ai
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--colors` / `-n` | 6 | Number of colors to extract |
| `--format` / `-f` | `terminal` | `terminal`, `css`, or `json` |
| `--context` / `-c` | | Brief note about the artwork — improves AI color names |
| `--no-ai` | | Skip Claude naming, use hex codes only |
| `--output` / `-o` | stdout | Write to file |

### Output formats

**Terminal** — ANSI color swatches with hex + name:
```
██  #c83220  Ember Red         (38%)
██  #1a3a5c  Deep Ocean        (22%)
```

**CSS** — ready-to-paste custom properties:
```css
:root {
  --painting-1: #c83220; /* Ember Red */
  --painting-2: #1a3a5c; /* Deep Ocean */
}
```

**JSON** — for scripting or further processing:
```json
{ "colors": [{ "hex": "#c83220", "name": "Ember Red", "frequency": 38 }], "mood": "intense, grounded" }
```

---

## next-painting

Analyzes a body of work and suggests what to paint next — looking for fresh ideas, gaps in the catalog, or opportunities to develop existing themes into series.

### Usage

```bash
# Analyze a local directory of images
next-painting ~/Desktop/new-art-for-site/png-archive

# Analyze via site catalog (fetches search.json)
next-painting https://myerman.art

# Focus on gaps or series opportunities
next-painting ~/art/ --style gaps
next-painting ~/art/ --style series

# Add personal context
next-painting ~/art/ --context "feeling drawn to wildlife lately"
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--count` / `-n` | 10 | Max images to analyze (sampled evenly if more) |
| `--context` / `-c` | | Brief note about your goals right now |
| `--style` / `-s` | `all` | `ideas`, `gaps`, `series`, or `all` |

### Output

Claude returns three sections:
1. **What I see in this body of work** — themes, strengths, patterns
2. **5 specific painting suggestions** — working title, description, and why it fits
3. **One bold idea** — something unexpected to push the work in a new direction

---

## patreon-plan

Generates a week-by-week Patreon content calendar based on your recent work. Plans a mix of free teaser posts and paid patron-only content across six post types.

### Usage

```bash
# 4-week plan (default), from local search.json
patreon-plan

# 8-week plan, 3 posts/week
patreon-plan --weeks 8 --posts-per-week 3

# From site URL, save to file
patreon-plan --source https://myerman.art --format markdown --output plan.md

# Paid-only plan, JSON output
patreon-plan --tiers paid --format json
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--weeks` / `-w` | 4 | Number of weeks to plan |
| `--posts-per-week` / `-p` | 2 | Posts per week |
| `--source` / `-s` | local `search.json` | Path to search.json or site URL |
| `--tiers` / `-t` | `all` | `free`, `paid`, or `all` |
| `--format` / `-f` | `markdown` | `markdown` or `json` |
| `--output` / `-o` | stdout | Write to file |

### Post types mixed in

- Early access / new print reveal
- Process video or timelapse teaser
- Behind-the-scenes / story behind the art
- High-res download for patrons
- Personal update / what's coming next
- Q&A or patron request shoutout

### Markdown output example

```markdown
## Week 1

### Monday 2026-05-06 — 🔓 Free
**Announcing: Blood Crow** _New print reveal_

First look at the latest piece — available now in the shop.

> **Write prompt:** Introduce Blood Crow with a short hook and a link to the print.
```

---

## photo-lineart

Converts photographs and illustrations into line art. Scores all 6 style variants plus all 15 pairwise blends (21 candidates total) and saves the top N results — flat, no subfolders — into a `compare/` folder next to your source images.

### Usage

```bash
# Default: run everything, save top 5 winners
photo-lineart photo.jpg
photo-lineart *.jpg

# Specify output folder and winner count
photo-lineart *.jpg --output ./compare/ --top 3

# Apply a color wash
photo-lineart *.jpg --tint sepia
photo-lineart photo.jpg --tint blueprint

# Thicken or thin the lines
photo-lineart photo.jpg --weight thick

# Single style (skips scoring, one output per image)
photo-lineart photo.jpg --style ink --detail high
photo-lineart photo.jpg --style pencil --darken --weight thick --tint sepia
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--style` / `-s` | *(none)* | `pencil`, `ink`, `canny`, `outline`, `xdog` — omit for default mode |
| `--detail` / `-d` | `medium` | `low`, `medium`, `high` — controls texture vs. cleanliness |
| `--output` / `-o` | `compare/` | Output directory |
| `--top` / `-n` | `5` | Number of top-ranked winners to save |
| `--tint` / `-t` | `none` | `sepia`, `blueprint`, `warm`, `cool` |
| `--weight` / `-w` | `normal` | `thin`, `normal`, `thick` |
| `--darken` | | Push pencil lines darker via gamma curve |
| `--invert` | | White lines on black background |

### Styles

| Style | Description |
|-------|-------------|
| `pencil` | Soft dodge-blend sketch — closest to a hand-drawn pencil look |
| `ink` | Bold adaptive threshold — pen or marker look |
| `canny` | Precise minimal edges — good for architecture and objects |
| `outline` | Thick clean object boundaries via bilateral filter + Sobel |
| `xdog` | Extended Difference of Gaussians — bold illustration strokes |

### Default mode output

Each image gets its own subfolder with up to 5 files ranked by score:

```
compare/
  photo/
    photo-top01-0.943-pencil-dark+canny.png
    photo-top02-0.849-canny.png
    photo-top03-0.715-pencil+canny.png
    photo-top04-0.633-pencil.png
    photo-top05-0.633-pencil+pencil-dark.png
```

Scores reflect useful line density (target ~15% of pixels as lines). The full ranked table of all 21 candidates is printed to the terminal.

### No API key required

`photo-lineart` runs entirely locally using OpenCV — no Anthropic API calls, no network access.

---

## image-describe

Walks a folder of images (or scrapes a URL) and writes a markdown file with a 2-3 sentence description of each one — subject, color palette, mood/style. Runs entirely locally via [Ollama](https://ollama.com).

### Setup (one-time)

```bash
# Install Ollama
open /Applications/Ollama.app        # if already downloaded
# — or —
brew install ollama                  # if Homebrew is available

# Pull a vision model (~1.7 GB, low RAM)
ollama pull moondream
```

Ollama must be running before you call the tool. The app starts automatically on login once installed.

### Usage

```bash
# Describe all images in a folder
image-describe ~/Desktop/inspo/

# Write to a specific file
image-describe ~/Desktop/art-staging/ready/ --output ~/Desktop/descriptions.md

# Walk subdirectories
image-describe ~/art/ --recursive

# Scrape images from a URL
image-describe https://myerman.art/prints/ -o gallery.md

# Use a different vision model
image-describe ~/art/ --model llava
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--output` / `-o` | `image-descriptions.md` next to source | Output markdown file |
| `--recursive` / `-r` | off | Walk subdirectories |
| `--model` / `-m` | `moondream` | Ollama vision model to use |

### Output

A markdown file with one section per image:

```markdown
## crow-nation.jpg

A silhouetted crow perches on a bare branch against a deep amber sky at dusk.
The palette is dominated by burnt orange and ochre with near-black shadows.
The mood is contemplative and elemental, evoking stillness at the edge of night.
```

### No API key required

`image-describe` talks only to Ollama on `localhost:11434` — nothing leaves the machine.

---

## Requirements

- Python 3.10+
- macOS (uses `sips` for image processing — no ImageMagick needed)
- `ANTHROPIC_API_KEY` for AI features (`publish-print`, `extract-palette`, `next-painting`, `patreon-plan`)
- [Ollama](https://ollama.com) with `llava-llama3` pulled for `image-describe`

---

## Development

```bash
pip install -e .
python -m pytest tests/ -v
```
