#!/usr/bin/env python3
"""Render today.json (from nhl_daily.py) into a self-contained index.html.

Usage: python3 render.py [today.json] [dist/index.html] [nfl.json]
Defaults: today.json in the current directory, dist/index.html, and
nfl.json in the current directory when present (NFL section omitted
when it is absent). NHL FanDuel odds show lines only, never prices.
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


def goalie_stat(g, stats):
    base = goalie(g)
    if stats:
        return f"{base} <span class=\"gstat\">{html.escape(stats)}</span>"
    return base


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
        f'<div class="goalies">Goalies: {goalie_stat(g["away_goalie"], g.get("away_goalie_stats"))} '
        f'vs {goalie_stat(g["home_goalie"], g.get("home_goalie_stats"))}</div>'
    )
    analytics = []
    if g.get("away_last10"):
        gp = g.get("away_last10_gp") or 10
        line = f'{g["away_name"]} — Last {gp}: {g["away_last10"]}'
        if g.get("away_away_gf") is not None:
            line += f' · Away: {g["away_away_gf"]:.1f} GF / {g["away_away_ga"]:.1f} GA'
        analytics.append(line)
    if g.get("home_last10"):
        gp = g.get("home_last10_gp") or 10
        line = f'{g["home_name"]} — Last {gp}: {g["home_last10"]}'
        if g.get("home_home_gf") is not None:
            line += f' · Home: {g["home_home_gf"]:.1f} GF / {g["home_home_ga"]:.1f} GA'
        analytics.append(line)
    if analytics:
        items = "".join(f"<div>{html.escape(s)}</div>" for s in analytics)
        parts.append(f'<div class="analytics">{items}</div>')
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


def nfl_card(g):
    parts = ["<section class=\"card nfl-card\">"]
    parts.append(
        f'<div class="matchup"><h2>{html.escape(g["away_name"])} at {html.escape(g["home_name"])}</h2>'
        f'<span class="time">{html.escape(g.get("time", ""))}</span></div>'
    )
    recs = []
    if g.get("away_record"):
        recs.append(f'{html.escape(g["away_name"])} {html.escape(g["away_record"])}')
    if g.get("home_record"):
        recs.append(f'{html.escape(g["home_name"])} {html.escape(g["home_record"])}')
    if recs:
        parts.append(f'<div class="nfl-records">{" · ".join(recs)}</div>')
    if g.get("state") == "post" and g.get("away_score") is not None:
        parts.append(
            f'<div class="nfl-score">Final: {html.escape(str(g["away_score"]))}–{html.escape(str(g["home_score"]))}</div>'
        )
    o = g.get("odds")
    if o:
        bits = []
        if o.get("details"):
            bits.append(html.escape(o["details"]))
        if o.get("total") is not None:
            bits.append(f'O/U {html.escape(str(o["total"]))}')
        if o.get("away_ml") and o.get("home_ml"):
            bits.append(
                f'ML: {html.escape(g["away_abbr"])} {html.escape(o["away_ml"])} / '
                f'{html.escape(g["home_abbr"])} {html.escape(o["home_ml"])}'
            )
        provider = html.escape(o.get("provider", "ESPN"))
        parts.append(f'<div class="odds">Odds via ESPN ({provider}): {" · ".join(bits)}</div>')
    else:
        parts.append('<div class="odds-note">Odds not posted yet</div>')
    parts.append("</section>")
    return "\n".join(parts)


def nfl_section(nfl):
    if not nfl or not nfl.get("games"):
        return ""
    cards = "\n".join(nfl_card(g) for g in nfl["games"])
    week = f'Week {nfl["week"]}' if nfl.get("week") else "This week"
    bye = ""
    if nfl.get("bye"):
        bye = f'<p class="nfl-bye">On bye: {html.escape(", ".join(nfl["bye"]))}</p>'
    return (
        f'<h2 class="section-title">NFL — {html.escape(str(week))}</h2>'
        '<p class="section-note">Full team names throughout. Odds come from ESPN\'s listed '
        "provider, not FanDuel, and are the morning snapshot, not live moves.</p>"
        f"{bye}"
        f'<div class="grid">\n{cards}\n</div>'
    )


BET_TYPES = """<h2 class="section-title">Which bets pay the book the most?</h2>
<div class="bet-types">
<p>Sportsbooks keep a cut of every dollar wagered, called the hold. On straight bets (one team, one total, one spread) the hold runs roughly 4 to 6 percent. On parlays it runs roughly 18 to 30 percent. Parlays are about a third of the money wagered but roughly 60 to 65 percent of sportsbook revenue.</p>
<p>State regulator reports make the gap concrete. Illinois in 2023: parlays held 18.2 percent versus 4.9 percent for straight bets. New Jersey in September 2024: parlays held 24.2 percent versus 4.4 percent for everything else.</p>
<p>Why the gap? A parlay multiplies the book's margin across every leg, and parlay payouts are set below the true odds of all legs hitting. Each added leg costs more than it pays.</p>
<p class="honest">Honest limit: no public source splits hold by sport AND bet type. These figures are all sports by bet type; state reports split by sport separately, so there is no verified "NHL parlay hold" or "NFL straight hold" number to show here.</p>
</div>"""


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NHL + NFL Matchup Chart — {date}</title>
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
.gstat {{ color: var(--muted); font-size: 13px; }}
.analytics {{ margin-top: 12px; font-size: 13px; color: var(--muted); line-height: 1.6; }}
.section-title {{ margin: 32px 0 6px; font-size: 22px; }}
.section-note {{ color: var(--muted); margin: 0 0 16px; line-height: 1.5; }}
.nfl-records {{ font-size: 14px; color: var(--muted); margin: 6px 0; }}
.nfl-score {{ margin-top: 10px; font-size: 14px; font-weight: 600; }}
.odds-note {{ margin-top: 10px; font-size: 13px; color: var(--muted); }}
.nfl-bye {{ color: var(--muted); margin: 0 0 16px; }}
.bet-types {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 20px; line-height: 1.6; }}
.bet-types p {{ margin: 8px 0; color: var(--muted); }}
.bet-types p.honest {{ color: var(--text); }}
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
<h1>NHL + NFL Matchup Chart</h1>
<p class="subtitle">{date} &middot; NHL today, NFL this week &middot; rebuilt every morning</p>
<div class="guide">
<h2>How to read it</h2>
<p>Each card pairs offense against the opposing defense on a common 0 to 5 scale. Orange bars are goals scored per game, teal bars are goals allowed per game, with each team's league rank.</p>
<p>GF rank 1st means the most goals scored per game. GA rank 1st means the fewest goals allowed per game.</p>
<p>Goalie labels come from DailyFaceoff: confirmed or projected is their call, reported means listed without a flag, and BACKUP means the starter is not the team's usual No. 1.</p>
<p>The FanDuel row on each card shows the spread, the puck line, and O/U, the total goals line. Lines only, no prices.</p>
<p>Last 10 is the regular-season record over the last 10 finals. Away and Home splits are season-to-date goals per game in that venue. Goalie SV% and record are season totals.</p>
</div>
<div class="grid">
{cards}
</div>
{nfl_section}
{bet_types}
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
    nfl_src = sys.argv[3] if len(sys.argv) > 3 else "nfl.json"
    with open(src) as f:
        data = json.load(f)
    cards = "\n".join(card(g) for g in data["games"])
    nfl = None
    if os.path.exists(nfl_src):
        try:
            with open(nfl_src) as f:
                nfl = json.load(f)
        except Exception:
            nfl = None
    out = PAGE.format(
        date=html.escape(data["date"]),
        cards=cards,
        nfl_section=nfl_section(nfl),
        bet_types=BET_TYPES,
    )
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w") as f:
        f.write(out)
    print(f"Wrote {dst} with {len(data['games'])} NHL games"
          f" and {len(nfl['games']) if nfl else 0} NFL games.")


if __name__ == "__main__":
    main()
