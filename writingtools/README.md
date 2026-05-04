# daily-spark

Generates daily writing prompts via GitHub Models (free with a GitHub account). The default experience is three **mashup prompts** — each one collides two random genres through a randomly chosen voice style and a single author or film influence as the creative lens.

Fully configurable: swap in your own genres, influences, and voice styles via a YAML file.

---

## Quick start

```bash
# Install
pip install .

# Run (requires GITHUB_TOKEN in your environment)
export GITHUB_TOKEN=your_token_here
daily-spark
```

Each run produces 3 mashup prompts by default. Each mashup picks two genres, one voice, and one influence at random — independently, so every card is a different collision.

---

## Getting a GitHub token

1. Go to **github.com → Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Create a token with **Models: Read** permission (no repo access needed)
3. `export GITHUB_TOKEN=ghp_...` in your shell, or add it to your shell profile

---

## Configuration

Everything — genres, influences, voice styles — lives in a single YAML file. Copy the bundled `config.yaml` and point the tool at it:

```bash
cp $(python -c "import writingtools; import pathlib; print(pathlib.Path(writingtools.__file__).parent / 'config.yaml')") ~/my-spark.yaml

daily-spark --config ~/my-spark.yaml

# Or set permanently:
export SPARK_CONFIG=~/my-spark.yaml
```

### Genres

Add, remove, or rename genres freely. The tool discovers them dynamically.

```yaml
genres:
  sf:
    label: Science Fiction
    icon: "🚀"
    color: "#1a3a5c"
    preferences: >
      Space opera, alternate histories, dystopias...
    influences:
      - Ursula K. Le Guin (anthropological depth, quiet moral weight)
      - Brian Daley (pulpy space opera energy)
    screen_influences:
      - Firefly (found family on the margins, lived-in future)
      - Battlestar Galactica reboot (moral collapse under pressure)
```

### Writer profile

Cross-genre influences that inflect every prompt:

```yaml
writer_profile:
  influences:
    - Albert Camus (absurdism, defiance as the only honest response)
    - Kurt Vonnegut (dark humor, humanity under pressure)
    - Viking Sagas (terse prose, fate, honour-debt)
```

### Voice styles

Twenty-two built-in voices. Edit or add your own:

```yaml
voices:
  campfire: >
    Write in the style of an oral storytelling tradition...
  tarantino: >
    Nonlinear energy, pop culture mid-scene, dialogue as tension...
```

The mashup engine picks one voice per card at random from the full pool.

---

## CLI options

```
daily-spark [OPTIONS]

Options:
  --config FILE        Path to your YAML config (or set SPARK_CONFIG env var)
  --mashups INTEGER    Number of mashup prompts to generate (default: 3)
  --genres INTEGER     Add this many single-genre prompts after the mashups (default: 0)
  --genre TEXT         Generate one specific genre only (no mashups)
  --voice TEXT         Voice for single-genre prompts: vanilla, trailer, bestseller,
                       xfiles, trashy, campfire, kenburns, pulp, academic, satiric,
                       telegram, gothic, broadsheet, bard, goldman, tarantino, beat,
                       dispatch, southern_gothic, magic_realism, fairy_tale, manifesto,
                       or 'random' (default)
  --model TEXT         GitHub Models model ID (default: gpt-4o-mini)
  --output FILE        Write HTML to a file instead of terminal
  --print-html         Print rendered HTML to stdout
  --email              Send via SMTP (requires EMAIL_* env vars)
```

### Examples

```bash
daily-spark                          # 3 mashups
daily-spark --mashups 5              # 5 mashups
daily-spark --mashups 3 --genres 3   # 3 mashups + 3 single-genre prompts
daily-spark --genre sf               # one specific genre, no mashups
daily-spark --genre sf --voice campfire
```

---

## Publishing to GitHub Pages

The included workflow (`.github/workflows/daily-spark.yml`) runs three times a day and publishes fresh prompts to `docs/index.html`.

**Setup:**
1. Enable GitHub Pages in your repo settings: **Source → Deploy from branch → main → /docs**
2. Push — the workflow creates `docs/index.html` on first run

Your page will be at `https://yourusername.github.io/your-repo/`.

---

## SMTP email delivery (optional)

```bash
daily-spark --email
```

Required environment variables:

| Variable | Example |
|----------|---------|
| `EMAIL_SMTP_HOST` | `smtp.gmail.com` |
| `EMAIL_SMTP_USER` | `you@gmail.com` |
| `EMAIL_SMTP_PASSWORD` | your app password |
| `EMAIL_FROM` | `you@gmail.com` |
| `EMAIL_TO` | `you@gmail.com` |

For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833) rather than your account password.
