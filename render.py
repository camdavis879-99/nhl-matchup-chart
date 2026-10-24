#!/usr/bin/env python3
"""Render today.json (from nhl_daily.py) into a self-contained index.html.

Usage: python3 render.py [today.json] [dist/index.html]
Defaults: today.json in the current directory, dist/index.html.
Only lines are shown for odds (spreads + total); prices are never rendered.
"""
import html
import json
import os
import sys


SCALE = 5.0
OFFENSE = "#f97316"
DEFENSE = "#0d9488"


def fmt(v):
    return f"{float(v):.1f}"


def bar(label, value, rank, color):
    pct = max(0.0, min(100.0, float(value) / SCALE * 100.0))
    return (
        f'<div class="bar-row"><span class="bar-label">{html.escape(label)}</span>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.0f}%;background:{color}"></div></div>'
        f'<span class="bar-value">{fmt(value)} &middot; {html.escape(str(rank))}</span></div>'
    )


def goalie(g):
    badge = ""
    if "BACKUP" in g:
        badge = ' <span class="backup">BACKUP</span>'
        g = g.replace(", BACKUP", "")
    return f"{html.escape(g)}{badge}"


def card(g):
    a, h = g["away_abbr"], g["home_abbr"]
    parts = ["<section class=\"card\">"]
    parts.append(
        f'<div class="matchup"><h2>{html.escape(g["away_name"])} at {html.escape(g["home_name"])}</h2>'
        f'<span class="time">{html.escape(g["time"])}</span></div>'
    )
    parts.append('<div class="pair-label">Away offense vs home defense</div>')
    parts.append(bar(f"{a} offense", g["away_gf"], g["away_gf_rank"], OFFENSE))
    parts.append(bar(f"{h} defense", g["home_ga"], g["home_ga_rank"], DEFENSE))
    parts.append('<div class="pair-label">Home offense vs away defense</div>')
    parts.append(bar(f"{h} offense", g["home_gf"], g["home_gf_rank"], OFFENSE))
    parts.append(bar(f"{a} defense", g["away_ga"], g["away_ga_rank"], DEFENSE))
    parts.append(
        f'<div class="goalies">Goalies: {goalie(g["away_goalie"])} vs {goalie(g["home_goalie"])}</div>'
    )
    o = g.get("odds")
    if o:
        parts.append(
            f'<div class="odds">FanDuel: {html.escape(a)} {html.escape(o["away_spread"])} &middot; '
            f'{html.escape(h)} {html.escape(o["home_spread"])} &middot; '
            f'O/U {html.escape(o["total"])}</div>'
        )
    stars = g.get("stars_out") or []
    if stars:
        items = "".join(f"<div>{html.escape(s)}</div>" for s in stars)
        parts.append(f'<div class="stars"><div class="stars-title">Stars out</div>{items}</div>')
    parts.append("</section>")
    return "\n".join(parts)


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NHL Matchup Chart — {date}</title>
<style>
:root {{ --bg: #f4f4f5; --card: #ffffff; --text: #18181b; --muted: #71717a; --border: #e4e4e7; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #09090b; --card: #18181b; --text: #fafafa; --muted: #a1a1aa; --border: #27272a; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }}
main {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }}
h1 {{ margin: 0 0 4px; font-size: 28px; }}
.subtitle {{ color: var(--muted); margin: 0 0 20px; }}
.guide {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 20px; margin-bottom: 24px; line-height: 1.5; }}
.guide h2 {{ margin: 0 0 8px; font-size: 16px; }}
.guide p {{ margin: 4px 0; color: var(--muted); }}
.grid {{ display: grid; grid-template-columns: 1fr; gap: 16px; }}
@media (min-width: 900px) {{ .grid {{ grid-template-columns: 1fr 1fr; }} }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }}
.matchup {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 14px; }}
.matchup h2 {{ margin: 0; font-size: 19px; }}
.time {{ color: var(--muted); font-size: 14px; white-space: nowrap; }}
.pair-label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); margin: 12px 0 6px; }}
.bar-row {{ display: flex; align-items: center; gap: 10px; margin: 6px 0; }}
.bar-label {{ width: 110px; flex-shrink: 0; font-size: 14px; }}
.bar-track {{ flex: 1; height: 14px; background: var(--bg); border-radius: 7px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 7px; }}
.bar-value {{ width: 92px; flex-shrink: 0; text-align: right; font-size: 14px; font-weight: 600; }}
.goalies {{ margin-top: 14px; font-size: 14px; }}
.backup {{ display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: #fef3c7; color: #92400e; margin-left: 4px; }}
.odds {{ margin-top: 10px; display: inline-block; font-size: 14px; font-weight: 600; padding: 6px 10px; border-radius: 999px; border: 1px solid var(--border); }}
.stars {{ margin-top: 12px; font-size: 13px; color: var(--muted); line-height: 1.5; }}
.stars-title {{ font-weight: 600; color: var(--muted); }}
footer {{ margin-top: 28px; color: var(--muted); font-size: 13px; line-height: 1.5; }}
@media (max-width: 520px) {{
  .bar-label {{ width: 86px; font-size: 13px; }}
  .bar-value {{ width: 78px; font-size: 13px; }}
}}
</style>
</head>
<body>
<main>
<h1>NHL Matchup Chart</h1>
<p class="subtitle">{date} &middot; rebuilt every morning</p>
<div class="guide">
<h2>How to read it</h2>
<p>Each card pairs offense against the opposing defense on a common 0 to 5 scale. Orange bars are goals scored per game, teal bars are goals allowed per game, with each team's league rank.</p>
<p>GF rank 1st means the most goals scored per game. GA rank 1st means the fewest goals allowed per game.</p>
<p>Goalie labels come from DailyFaceoff: confirmed or projected is their call, reported means listed without a flag, and BACKUP means the starter is not the team's usual No. 1.</p>
<p>The FanDuel row on each card shows the spread, the puck line, and O/U, the total goals line. Lines only, no prices.</p>
</div>
<div class="grid">
{cards}
</div>
<footer>
<p>Snapshot of today's slate, rebuilt every morning with that day's games. Goalie labels: confirmed/projected is DailyFaceoff's call, reported means listed without a flag, BACKUP means not the team's usual No. 1. Ranks: GF 1st is the most goals scored per game, GA 1st is the fewest goals allowed per game.</p>
</footer>
</main>
</body>
</html>
"""


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "today.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "dist/index.html"
    with open(src) as f:
        data = json.load(f)
    cards = "\n".join(card(g) for g in data["games"])
    out = PAGE.format(date=html.escape(data["date"]), cards=cards)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w") as f:
        f.write(out)
    print(f"Wrote {dst} with {len(data['games'])} games.")


if __name__ == "__main__":
    main()
