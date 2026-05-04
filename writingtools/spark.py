"""daily-spark CLI — generate a set of genre writing prompts via GitHub Models."""
import json
import os
import random
import sys
from pathlib import Path

import click
import yaml

from .render import render_email
from .mailer import send


def _load_config(config_path: str | None) -> dict:
    """Load config from path, SPARK_CONFIG env var, or bundled default."""
    path = config_path or os.environ.get("SPARK_CONFIG")
    if path:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    bundled = Path(__file__).parent / "config.yaml"
    return yaml.safe_load(bundled.read_text(encoding="utf-8"))


def _build_genres(config: dict) -> dict:
    """Convert config genres section into the runtime GENRES dict."""
    genres = {}
    for key, g in config.get("genres", {}).items():
        influences = g.get("influences", [])
        screen = g.get("screen_influences", [])
        prefs = g.get("preferences", "").strip()
        if influences:
            prefs = f"{prefs} Literary influences: {', '.join(influences)}."
        if screen:
            prefs = f"{prefs} Screen influences: {', '.join(screen)}."
        genres[key] = {
            "label": g["label"],
            "icon": g["icon"],
            "color": g["color"],
            "preferences": prefs,
        }
    return genres


def _collect_all_influences(config: dict) -> list[str]:
    """Collect every named influence across writer profile and all genres."""
    influences = []
    influences.extend(config.get("writer_profile", {}).get("influences", []))
    for g in config.get("genres", {}).values():
        influences.extend(g.get("influences", []))
        influences.extend(g.get("screen_influences", []))
    return influences


def _build_mashup(config: dict, genres: dict, voices: dict) -> dict:
    """Pick two random genres, one voice, one influence."""
    genre_keys = random.sample(list(genres.keys()), 2)
    g1, g2 = genres[genre_keys[0]], genres[genre_keys[1]]
    voice_name = random.choice(list(voices.keys()))
    influence = random.choice(_collect_all_influences(config))
    return {
        "genre_keys": genre_keys,
        "genre_labels": [g1["label"], g2["label"]],
        "genre_icons": [g1["icon"], g2["icon"]],
        "genre_prefs": [g1["preferences"], g2["preferences"]],
        "voice_name": voice_name,
        "voice_instruction": voices[voice_name],
        "influence": influence,
    }


def _assign_voices(genres: dict, voice: str, voices: dict) -> dict[str, str]:
    """Return {genre_key: voice_instruction}. 'random' assigns each voice at most once per run."""
    if voice == "random":
        voice_names = list(voices.keys())
        if len(genres) <= len(voice_names):
            chosen = random.sample(voice_names, len(genres))
        else:
            chosen = []
            while len(chosen) < len(genres):
                chunk = voice_names[:]
                random.shuffle(chunk)
                chosen.extend(chunk)
            chosen = chosen[:len(genres)]
        return {key: voices[name] for key, name in zip(genres, chosen)}
    instruction = voices.get(voice, voices.get("vanilla", ""))
    return {key: instruction for key in genres}


@click.command()
@click.option("--config", "config_path", default=None, metavar="FILE",
              help="Path to a YAML config file (default: bundled config.yaml)")
@click.option("--email", is_flag=True, default=False,
              help="Generate prompts and send via email")
@click.option("--mashups", default=3, show_default=True,
              help="Number of genre-mashup prompts to generate")
@click.option("--genres", "genre_count", default=0, show_default=True,
              help="Number of single-genre prompts to add after the mashups")
@click.option("--genre", type=str, default=None,
              help="Generate a single specific genre only (overrides --mashups and --genres)")
@click.option("--model", default="gpt-4o-mini", show_default=True,
              help="GitHub Models model ID to use")
@click.option("--voice", default="random", show_default=True,
              help="Voice style for single-genre prompts: vanilla, trailer, bestseller, xfiles, "
                   "trashy, campfire, kenburns, pulp, academic, satiric, telegram, gothic, "
                   "broadsheet, bard, goldman, tarantino, beat, dispatch, southern_gothic, "
                   "magic_realism, fairy_tale, manifesto, or 'random' (default)")
@click.option("--print-html", is_flag=True, default=False,
              help="Print the rendered HTML to stdout instead of sending")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write HTML to a file (e.g. docs/index.html)")
def cli(config_path, email, mashups, genre_count, genre, model, voice, print_html, output):
    """Generate daily writing sparks via GitHub Models.

    Default: 3 genre-mashup prompts (two genres × one voice × one influence).
    Add single-genre prompts with --genres N.

    Requires GITHUB_TOKEN in the environment.

    Examples:\n
      daily-spark\n
      daily-spark --mashups 5\n
      daily-spark --mashups 3 --genres 3\n
      daily-spark --genre sf --voice campfire\n
      daily-spark --config ~/my-spark.yaml
    """
    config = _load_config(config_path)
    all_genres = _build_genres(config)
    writer_profile = config.get("writer_profile", {})
    voices = config.get("voices", {})

    # Single-genre mode
    if genre:
        if genre not in all_genres:
            click.echo(f"Unknown genre '{genre}'. Available: {', '.join(all_genres)}", err=True)
            sys.exit(1)
        single_genres = {genre: all_genres[genre]}
        voice_map = _assign_voices(single_genres, voice, voices)
        voice_name_map = {v: n for n, v in voices.items()}
        assigned_voice_names = {k: voice_name_map.get(voice_map[k], voice) for k in single_genres}
        click.echo(f"  Generating 1 prompt via GitHub Models ({model})...\n", err=True)
        result = _generate_single_genres(single_genres, model, writer_profile, voice_map)
        prompts = result
        mashup_metas = []
        mashup_prompts = []
    else:
        # Build mashups
        mashup_metas = [_build_mashup(config, all_genres, voices) for _ in range(mashups)]

        # Build single-genre prompts if requested
        if genre_count > 0:
            n = min(genre_count, len(all_genres))
            sampled_keys = random.sample(list(all_genres.keys()), n)
            single_genres = {k: all_genres[k] for k in sampled_keys}
            voice_map = _assign_voices(single_genres, voice, voices)
            voice_name_map = {v: n for n, v in voices.items()}
            assigned_voice_names = {k: voice_name_map.get(voice_map[k], voice) for k in single_genres}
        else:
            single_genres = {}
            voice_map = {}
            assigned_voice_names = {}

        total = mashups + len(single_genres)
        click.echo(f"  Generating {total} prompt(s) via GitHub Models ({model})...\n", err=True)

        mashup_prompts, prompts = _generate_all(
            mashup_metas, single_genres, model, writer_profile, voice_map
        )

    if not mashup_prompts and not prompts:
        click.echo("No prompts generated. Check your GITHUB_TOKEN.", err=True)
        sys.exit(1)

    html = render_email(prompts, single_genres if not genre else {genre: all_genres[genre]},
                        assigned_voice_names if not genre else assigned_voice_names,
                        mashup_metas, mashup_prompts)

    if print_html:
        click.echo(html)
        return

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(html, encoding="utf-8")
        click.echo(f"  Written to {output}", err=True)
        return

    for meta, prompt in zip(mashup_metas, mashup_prompts):
        labels = " × ".join(meta["genre_labels"])
        icons = " ".join(meta["genre_icons"])
        click.echo(f"  ⚡  {icons}  {labels}  [{meta['voice_name']}]")
        click.echo(f"  via: {meta['influence']}")
        click.echo(f"  {prompt}\n")

    for key, p in prompts.items():
        g = (single_genres if not genre else {genre: all_genres[genre]}).get(key, {})
        vname = assigned_voice_names.get(key, voice)
        click.echo(f"  {g.get('icon','✦')}  {g.get('label', key)}  [{vname}]")
        click.echo(f"  {p}\n")

    if email:
        click.echo("  Sending email...", err=True)
        send(html)
        click.echo("  Done.", err=True)


def _generate_all(
    mashup_metas: list[dict],
    single_genres: dict,
    model: str,
    writer_profile: dict | None = None,
    voice_map: dict | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Generate all mashup and single-genre prompts in one API call."""
    client = _github_client()

    entries = []
    keys = []

    for i, m in enumerate(mashup_metas):
        key = f"__mashup_{i}__"
        keys.append(("mashup", key))
        g1_label, g2_label = m["genre_labels"]
        g1_prefs, g2_prefs = m["genre_prefs"]
        entries.append(
            f'- "{key}": MASHUP — Collide {g1_label} with {g2_label}. '
            f'{g1_label} preferences: {g1_prefs} '
            f'{g2_label} preferences: {g2_prefs} '
            f'Channel: {m["influence"]}. '
            f'Voice style: {m["voice_instruction"]} '
            f'The two genres must genuinely collide — not coexist.'
        )

    for key, g in single_genres.items():
        keys.append(("genre", key))
        voice_note = f" Voice style: {voice_map.get(key, '')}" if voice_map else ""
        entries.append(f'- "{key}": {g["label"]} — {g["preferences"]}{voice_note}')

    profile_block = _profile_block(writer_profile)
    response_shape = (
        "{\n"
        + ",\n".join(f'  "{k}": "prompt text here"' for _, k in keys)
        + "\n}"
    )

    prompt = (
        "You are a creative writing spark generator. Produce specific, evocative prompts — "
        "not themes, but *situations*. A character in a moment of tension or discovery, "
        "a vivid setting detail, space for the writer to go anywhere. "
        "2-3 sentences max. Just the spark. "
        "For MASHUP entries, the two genres must genuinely collide in surprising ways. "
        "Apply voice style instructions exactly."
        f"{profile_block}\n\n"
        f"Generate one prompt per entry:\n" + "\n".join(entries) + "\n\n"
        "Respond with JSON only — no explanation, no markdown:\n"
        f"{response_shape}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=2500,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        data = json.loads(raw)
        mashup_prompts = [data.get(f"__mashup_{i}__", "") for i in range(len(mashup_metas))]
        genre_prompts = {k: data.get(k, "") for _, k in keys if _ == "genre"}
        return mashup_prompts, genre_prompts
    except Exception as e:
        click.echo(f"Generation error: {e}", err=True)
        return [], {}


def _generate_single_genres(
    genres: dict,
    model: str,
    writer_profile: dict | None = None,
    voice_map: dict | None = None,
) -> dict[str, str]:
    """Generate single-genre prompts only (used in --genre mode)."""
    client = _github_client()
    entries = []
    for key, g in genres.items():
        voice_note = f" Voice style: {voice_map.get(key, '')}" if voice_map else ""
        entries.append(f'- "{key}": {g["label"]} — {g["preferences"]}{voice_note}')
    profile_block = _profile_block(writer_profile)
    response_shape = (
        "{\n"
        + ",\n".join(f'  "{k}": "prompt text here"' for k in genres)
        + "\n}"
    )
    prompt = (
        "You are a creative writing spark generator. Produce specific, evocative prompts — "
        "a character in a moment of tension or discovery, vivid setting, open space for the writer. "
        "2-3 sentences max. Just the spark. Apply voice style instructions exactly."
        f"{profile_block}\n\n"
        f"Generate one prompt per entry:\n" + "\n".join(entries) + "\n\n"
        "Respond with JSON only — no explanation, no markdown:\n"
        f"{response_shape}"
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=600,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception as e:
        click.echo(f"Generation error: {e}", err=True)
        return {}


def _profile_block(writer_profile: dict | None) -> str:
    if not writer_profile:
        return ""
    parts = []
    background = writer_profile.get("background", "").strip()
    influences = writer_profile.get("influences", [])
    if background:
        parts.append(f"Writer background: {background}")
    if influences:
        parts.append("Cross-genre touchstones: " + "; ".join(influences))
    return ("\n\n" + " ".join(parts)) if parts else ""


def _collect_all_influences(config: dict) -> list[str]:
    """Collect every named influence across writer profile and all genres."""
    influences = []
    influences.extend(config.get("writer_profile", {}).get("influences", []))
    for g in config.get("genres", {}).values():
        influences.extend(g.get("influences", []))
        influences.extend(g.get("screen_influences", []))
    return influences


def _github_client():
    """Return an OpenAI client pointed at GitHub Models."""
    from openai import OpenAI
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set.")
    return OpenAI(base_url="https://models.inference.ai.azure.com", api_key=token)
