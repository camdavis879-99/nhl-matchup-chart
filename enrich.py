#!/usr/bin/env python3
"""Enrich today.json (from nhl_daily.py) with extra NHL analytics, in place.

Usage: python3 enrich.py [today.json] [YYYY-MM-DD]
Defaults: today.json in the current directory, today's date in Phoenix
(America/Phoenix is UTC-7 year-round, so a fixed offset is safe).

Adds, per game:
- Full team names: nickname-only away_name/home_name (e.g. "Stars") are
  replaced with placeName + commonName from the NHL schedule (e.g.
  "Dallas Stars"). Full names are used on every card, never city-only,
  because several cities have both NHL and NFL teams.
- Last-10 form: regular-season W-L-OTL over the last 10 finals.
- Home/away splits: season-to-date goals for/against per game in that
  venue (away team's away splits, home team's home splits).
- Starting-goalie season line: save % and W-L-OTL, matched by name
  against club-stats. Unmatched or unconfirmed goalies get no line
  rather than a guessed one.

Stdlib only. Sources are all public api-web.nhle.com endpoints, the
same ones nhl_daily.py uses (urllib follows the /now redirects).
Never fails the build: every fetch is guarded, and the script always
exits 0, leaving today.json usable even if enrichment is partial.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

NHL = "https://api-web.nhle.com/v1"
PHOENIX = timezone(timedelta(hours=-7))


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        print(f"enrich: fetch failed {url}: {type(e).__name__}", file=sys.stderr)
        return None


def norm(name):
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def full_name(place, common):
    place = (place or "").strip()
    common = (common or "").strip()
    if place and common:
        return f"{place} {common}"
    return place or common or ""


def team_analytics(abbr):
    """Return (last10_record, last10_gp, home_gf, home_ga, away_gf, away_ga).

    Regular-season finals only (gameType 2, gameState FINAL/OFF).
    A loss in OT/SO counts as an overtime loss.
    """
    data = fetch_json(f"{NHL}/club-schedule-season/{abbr}/now")
    games = []
    if data:
        for g in data.get("games", []):
            if g.get("gameType") != 2:
                continue
            if g.get("gameState") not in ("FINAL", "OFF"):
                continue
            games.append(g)
    games.sort(key=lambda g: (g.get("gameDate", ""), g.get("id", 0)))
    last = games[-10:]
    w = l = otl = 0
    home_gf = home_ga = home_gp = 0
    away_gf = away_ga = away_gp = 0
    for g in games:
        away, home = g.get("awayTeam", {}), g.get("homeTeam", {})
        if away.get("abbrev") == abbr:
            mine, opp, is_home = away.get("score", 0), home.get("score", 0), False
        elif home.get("abbrev") == abbr:
            mine, opp, is_home = home.get("score", 0), away.get("score", 0), True
        else:
            continue
        if is_home:
            home_gf += mine
            home_ga += opp
            home_gp += 1
        else:
            away_gf += mine
            away_ga += opp
            away_gp += 1
    for g in last:
        away, home = g.get("awayTeam", {}), g.get("homeTeam", {})
        if away.get("abbrev") == abbr:
            mine, opp = away.get("score", 0), home.get("score", 0)
        else:
            mine, opp = home.get("score", 0), away.get("score", 0)
        if mine > opp:
            w += 1
        else:
            pd = g.get("periodDescriptor") or {}
            go = g.get("gameOutcome") or {}
            if go.get("lastPeriodType") in ("OT", "SO") or (pd.get("number") or 3) > 3:
                otl += 1
            else:
                l += 1
    return (
        f"{w}-{l}-{otl}",
        len(last),
        round(home_gf / home_gp, 1) if home_gp else None,
        round(home_ga / home_gp, 1) if home_gp else None,
        round(away_gf / away_gp, 1) if away_gp else None,
        round(away_ga / away_gp, 1) if away_gp else None,
    )


def goalie_stats(abbr):
    """Map normalized goalie name -> 'SV% .925 · 1-1-0' season line."""
    data = fetch_json(f"{NHL}/club-stats/{abbr}/now")
    out = {}
    last_names = {}
    if data:
        for gl in data.get("goalies", []):
            fn = (gl.get("firstName") or {}).get("default", "")
            ln = (gl.get("lastName") or {}).get("default", "")
            name = f"{fn} {ln}".strip()
            if not name:
                continue
            sv = gl.get("savePercentage")
            sv_txt = f".{round(sv * 1000):03d}" if isinstance(sv, (int, float)) else None
            rec = f"{gl.get('wins', 0)}-{gl.get('losses', 0)}-{gl.get('overtimeLosses', 0)}"
            line = " · ".join(x for x in (f"{sv_txt} SV%" if sv_txt else None, rec) if x)
            out[norm(name)] = line
            last_names.setdefault(norm(ln), []).append(line)
    # Fall back to last name only when it is unique on the team.
    for ln, lines in last_names.items():
        if len(lines) == 1 and ln not in out:
            out[ln] = lines[0]
    return out


def goalie_name(line):
    """Extract the starter's name from a goalie_line string.

    'Jake Oettinger (confirmed)' -> 'Jake Oettinger'.
    'unconfirmed ...' -> None (no verified starter, so no stat line).
    """
    if not line or line.startswith("unconfirmed"):
        return None
    return line.split(" (")[0].strip() or None


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "today.json"
    if len(sys.argv) > 2:
        date_s = sys.argv[2]
    else:
        date_s = datetime.now(PHOENIX).date().isoformat()
    try:
        with open(src) as f:
            data = json.load(f)
    except Exception as e:
        print(f"enrich: cannot read {src}: {e}", file=sys.stderr)
        return 0
    games = data.get("games", [])

    # Full names from the schedule for the slate date.
    full = {}
    sched = fetch_json(f"{NHL}/schedule/{date_s}")
    if sched:
        for day in sched.get("gameWeek", []):
            if day.get("date") != date_s:
                continue
            for g in day.get("games", []):
                for side in ("awayTeam", "homeTeam"):
                    t = g.get(side, {})
                    abbr = t.get("abbrev", "")
                    place = (t.get("placeName") or {}).get("default", "")
                    common = (t.get("commonName") or {}).get("default", "")
                    name = full_name(place, common)
                    if abbr and name:
                        full[abbr] = name

    teams = []
    for g in games:
        for abbr in (g.get("away_abbr", ""), g.get("home_abbr", "")):
            if abbr and abbr not in teams:
                teams.append(abbr)
    analytics = {}
    stats = {}
    for abbr in teams:
        try:
            analytics[abbr] = team_analytics(abbr)
        except Exception as e:
            print(f"enrich: analytics failed for {abbr}: {e}", file=sys.stderr)
        try:
            stats[abbr] = goalie_stats(abbr)
        except Exception as e:
            print(f"enrich: goalie stats failed for {abbr}: {e}", file=sys.stderr)

    for g in games:
        a, h = g.get("away_abbr", ""), g.get("home_abbr", "")
        if a in full:
            g["away_name"] = full[a]
        if h in full:
            g["home_name"] = full[h]
        if a in analytics:
            rec, gp, _hgf, _hga, agf, aga = analytics[a]
            g["away_last10"] = rec
            g["away_last10_gp"] = gp
            g["away_away_gf"] = agf
            g["away_away_ga"] = aga
        if h in analytics:
            rec, gp, hgf, hga, _agf, _aga = analytics[h]
            g["home_last10"] = rec
            g["home_last10_gp"] = gp
            g["home_home_gf"] = hgf
            g["home_home_ga"] = hga
        for side, abbr, key in (("away", a, "away_goalie"), ("home", h, "home_goalie")):
            name = goalie_name(g.get(key, ""))
            line = None
            if name and abbr in stats:
                line = stats[abbr].get(norm(name))
            g[f"{side}_goalie_stats"] = line

    tmp = src + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, src)
    print(f"Enriched {src} with {len(games)} games (full names, form, splits, goalie stats).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
