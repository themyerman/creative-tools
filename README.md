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

## Requirements

- Python 3.10+
- macOS (uses `sips` for image processing — no ImageMagick needed)
- `ANTHROPIC_API_KEY` for AI features

---

## Development

```bash
pip install -e .
python -m pytest tests/ -v
```
