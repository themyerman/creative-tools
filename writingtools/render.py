"""Render writing prompts as a beautiful HTML page."""
from datetime import date


_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #0f0f0f;
  font-family: Georgia, 'Times New Roman', serif;
  color: #e8e8e8;
  padding: 0;
}
.wrapper {
  max-width: 600px;
  margin: 0 auto;
  padding: 32px 24px;
}
.header {
  text-align: center;
  margin-bottom: 36px;
  padding-bottom: 24px;
  border-bottom: 1px solid #2a2a2a;
}
.header h1 {
  font-size: 1.1rem;
  font-weight: 400;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #888;
  margin-bottom: 6px;
}
.header .date {
  font-size: 0.85rem;
  color: #555;
  font-family: system-ui, sans-serif;
}

/* ── Wild Card ───────────────────────────────────────────────────────── */
.wildcard {
  margin-bottom: 32px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #3a2a5a;
  box-shadow: 0 0 32px rgba(120, 60, 220, 0.15);
}
.wildcard-banner {
  background: linear-gradient(135deg, #1a0a3a 0%, #0a1a3a 100%);
  padding: 8px 16px;
  font-family: system-ui, sans-serif;
  font-size: 0.65rem;
  font-weight: 800;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: #9966ff;
  display: flex;
  align-items: center;
  gap: 8px;
}
.wildcard-banner .wc-spacer { flex: 1; }
.wildcard-banner .wc-voice {
  font-weight: 400;
  letter-spacing: 0.05em;
  text-transform: none;
  color: #6644aa;
}
.wildcard-header {
  background: linear-gradient(135deg, #120820 0%, #080f1a 100%);
  padding: 16px 20px 14px;
  border-top: 1px solid #2a1a4a;
  border-bottom: 1px solid #1a1a2a;
}
.wildcard-genres {
  font-family: system-ui, sans-serif;
  font-size: 1.1rem;
  font-weight: 700;
  color: #ccaaff;
  letter-spacing: 0.02em;
  margin-bottom: 6px;
}
.wildcard-influence {
  font-family: system-ui, sans-serif;
  font-size: 0.75rem;
  color: #6644aa;
  font-style: italic;
}
.wildcard-body {
  background: #0d0818;
  padding: 22px 20px 24px;
  font-size: 1.15rem;
  line-height: 1.8;
  color: #ddd8ff;
}

/* ── Genre cards ─────────────────────────────────────────────────────── */
.card {
  margin-bottom: 24px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #222;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-family: system-ui, sans-serif;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #ccc;
}
.card-body {
  background: #161616;
  padding: 20px 20px 22px;
  font-size: 1.05rem;
  line-height: 1.75;
  color: #ddd;
}

/* ── Footer ──────────────────────────────────────────────────────────── */
.footer {
  margin-top: 36px;
  padding-top: 20px;
  border-top: 1px solid #1e1e1e;
  font-family: system-ui, sans-serif;
  font-size: 0.72rem;
  color: #444;
  text-align: center;
  line-height: 1.6;
}
"""


def _mashup_card(meta: dict, prompt: str) -> str:
    icons = " ".join(meta["genre_icons"])
    labels = " &times; ".join(meta["genre_labels"])
    return f"""
  <div class="wildcard">
    <div class="wildcard-banner">
      <span>⚡ Mashup</span>
      <span class="wc-spacer"></span>
      <span class="wc-voice">{meta["voice_name"]}</span>
    </div>
    <div class="wildcard-header">
      <div class="wildcard-genres">{icons} &nbsp;{labels}</div>
      <div class="wildcard-influence">via {meta["influence"]}</div>
    </div>
    <div class="wildcard-body">{prompt}</div>
  </div>"""


def render_email(
    prompts: dict[str, str],
    genres: dict,
    voice_names: dict | None = None,
    mashup_metas: list | None = None,
    mashup_prompts: list | None = None,
) -> str:
    today = date.today().strftime("%A, %B %-d, %Y")

    mashups_html = "\n".join(
        _mashup_card(meta, prompt)
        for meta, prompt in zip(mashup_metas or [], mashup_prompts or [])
        if prompt
    )

    cards = []

    for key, text in prompts.items():
        g = genres.get(key, {})
        icon = g.get("icon", "✦")
        label = g.get("label", key.title())
        color = g.get("color", "#1a1a1a")
        vname = (voice_names or {}).get(key)
        voice_badge = (
            f'<span style="margin-left: auto; font-weight: 400; opacity: 0.6; '
            f'text-transform: none; letter-spacing: 0;">{vname}</span>'
            if vname else ""
        )
        cards.append(f"""
  <div class="card">
    <div class="card-header" style="background: {color};">
      <span>{icon}</span>
      <span>{label}</span>
      {voice_badge}
    </div>
    <div class="card-body">{text}</div>
  </div>""")

    cards_html = "\n".join(cards)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Daily Writing Spark — {today}</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>✦ Daily Writing Spark</h1>
      <div class="date">{today}</div>
    </div>
    {mashups_html}
    {cards_html}
    <div class="footer">
      Generated by creative-tools &middot; GitHub Models &middot; {today}
    </div>
  </div>
</body>
</html>"""
