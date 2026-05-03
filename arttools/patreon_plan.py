"""patreon-plan CLI — generate a Patreon content calendar from recent artwork."""
import json
import urllib.request
from pathlib import Path
from datetime import date, timedelta

import click

from .ai_writer import _client
from .config import SEARCH_JSON, SITE_BASE_URL


@click.command()
@click.option("--weeks", "-w", default=4, show_default=True, help="Number of weeks to plan")
@click.option("--posts-per-week", "-p", default=2, show_default=True,
              help="Number of posts per week")
@click.option("--source", "-s", default=None,
              help="Path to search.json or site URL (defaults to local myerman-art search.json)")
@click.option("--tiers", "-t", default="all",
              type=click.Choice(["free", "paid", "all"]), show_default=True,
              help="Which tier posts to plan")
@click.option("--format", "-f", "fmt",
              type=click.Choice(["markdown", "json"]), default="markdown", show_default=True)
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Write plan to file instead of stdout")
def cli(weeks, posts_per_week, source, tiers, fmt, output):
    """Generate a Patreon content calendar based on your recent artwork.

    Analyzes your catalog and creates a week-by-week posting plan with
    suggested post types, themes, and copy prompts.

    Examples:\n
      patreon-plan\n
      patreon-plan --weeks 8 --posts-per-week 3\n
      patreon-plan --source https://myerman.art --format markdown --output plan.md
    """
    click.echo("\n  Loading catalog...", err=True)
    works = _load_works(source)

    if not works:
        click.echo("No works found. Check your source.", err=True)
        raise SystemExit(1)

    click.echo(f"  Found {len(works)} works. Generating {weeks}-week plan...\n", err=True)

    plan = _generate_plan(works, weeks, posts_per_week, tiers)

    if fmt == "json":
        result = json.dumps(plan, indent=2)
    else:
        result = _render_markdown(plan)

    if output:
        Path(output).write_text(result, encoding="utf-8")
        click.echo(f"  Saved to {output}", err=True)
    else:
        click.echo(result)


def _load_works(source: str | None) -> list[dict]:
    if source is None:
        data = json.loads(SEARCH_JSON.read_text(encoding="utf-8"))
    elif source.startswith("http"):
        url = source.rstrip("/") + "/search.json"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    else:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    return data[:30]  # most recent 30


def _generate_plan(works: list[dict], weeks: int, posts_per_week: int, tiers: str) -> dict:
    total_posts = weeks * posts_per_week
    works_text = json.dumps([
        {"title": w.get("title"), "tags": w.get("tags", [])[:5], "story_snippet": (w.get("story", "")[:80] + "…")}
        for w in works[:20]
    ], indent=2)

    tier_note = {
        "free":  "All posts are free / public.",
        "paid":  "All posts are for paid patrons only ($3+ tier).",
        "all":   "Mix free teaser posts with paid early-access and behind-the-scenes content.",
    }[tiers]

    start_date = date.today()

    prompt = (
        "You are a content strategist for Tom Myer, a Hodinǫ̱hsǫ́:nih and Ngäbe-Buglé "
        "Indigenous digital artist based in Colorado. He runs a Patreon at patreon.com/myerman.\n\n"
        f"Plan {total_posts} Patreon posts spread over {weeks} weeks ({posts_per_week}/week). "
        f"Tier strategy: {tier_note}\n\n"
        "Post types to mix in:\n"
        "- Early access / new print reveal\n"
        "- Process video or timelapse teaser\n"
        "- Behind-the-scenes / story behind the art\n"
        "- High-res download for patrons\n"
        "- Personal update / what's coming next\n"
        "- Q&A or patron request shoutout\n\n"
        f"His recent work includes:\n{works_text}\n\n"
        f"Start date: {start_date.isoformat()}\n\n"
        "Respond with a JSON array of posts. Each post:\n"
        '{"week": 1, "day": "Monday", "date": "YYYY-MM-DD", "tier": "free|paid", '
        '"type": "post type", "title": "post title", "description": "2-3 sentence post description", '
        '"copy_prompt": "one sentence prompt Tom can use to write the actual post copy"}'
    )

    msg = _client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()

    try:
        posts = json.loads(raw)
    except Exception:
        # Fallback: return raw text as a single item
        posts = [{"week": 1, "raw": raw}]

    return {"weeks": weeks, "posts_per_week": posts_per_week, "tiers": tiers, "posts": posts}


def _render_markdown(plan: dict) -> str:
    today = date.today()
    lines = [
        f"# Patreon Content Plan",
        f"Generated: {today.isoformat()} · {plan['weeks']} weeks · {plan['posts_per_week']} posts/week\n",
    ]

    current_week = 0
    for post in plan.get("posts", []):
        week = post.get("week", 1)
        if week != current_week:
            current_week = week
            lines.append(f"\n## Week {week}\n")

        tier_badge = "🔓 Free" if post.get("tier") == "free" else "🔒 Paid"
        lines.append(f"### {post.get('day', '')} {post.get('date', '')} — {tier_badge}")
        lines.append(f"**{post.get('title', '')}** _{post.get('type', '')}_\n")
        lines.append(post.get("description", ""))
        if post.get("copy_prompt"):
            lines.append(f"\n> **Write prompt:** {post['copy_prompt']}\n")

    return "\n".join(lines)
