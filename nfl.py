#!/usr/bin/env python3
"""Fetch the current NFL week from ESPN's public scoreboard API.

Usage: python3 nfl.py [nfl.json]
Writes {week, season, bye: [full team names], games: [...]}.
Each game carries full team names (never city-only), records, Phoenix
time, scores for finished games, and the listed odds if ESPN posts any.

Odds honesty: ESPN's scoreboard lists a provider (currently
DraftKings). These are NOT FanDuel lines, and the page labels them as
such. If ESPN posts no odds for a game, lines are shown as unavailable
rather than guessed. No NCAA content: this script covers the NFL only.

Stdlib only. Never fails the build: on any fetch error it writes an
empty games list and exits 0.
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
PHOENIX = timezone(timedelta(hours=-7))


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        print(f"nfl: fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def parse_time(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(PHOENIX).strftime("%a %-I:%M %p")
    except Exception:
        return ""


def record_of(competitor):
    for r in competitor.get("records", []) or []:
        if r.get("type") == "total":
            return r.get("summary", "")
    recs = competitor.get("records", []) or []
    return recs[0].get("summary", "") if recs else ""


def main():
    dst = sys.argv[1] if len(sys.argv) > 1 else "nfl.json"
    out = {"week": None, "season": None, "bye": [], "games": []}
    data = fetch_json(ESPN)
    if data:
        week = data.get("week", {}) or {}
        season = data.get("season", {}) or {}
        out["week"] = week.get("number")
        out["season"] = season.get("year")
        out["bye"] = [
            t.get("displayName", "")
            for t in week.get("teamsOnBye", []) or []
            if t.get("displayName")
        ]
        for ev in data.get("events", []) or []:
            comps = ev.get("competitions", []) or []
            if not comps:
                continue
            comp = comps[0]
            sides = {}
            for c in comp.get("competitors", []) or []:
                team = c.get("team", {}) or {}
                sides[c.get("homeAway")] = {
                    "name": team.get("displayName", ""),
                    "abbr": team.get("abbreviation", ""),
                    "record": record_of(c),
                    "score": c.get("score"),
                }
            if "away" not in sides or "home" not in sides:
                continue
            state = ((ev.get("status", {}) or {}).get("type", {}) or {}).get("state", "")
            odds = None
            odds_list = comp.get("odds") or []
            if odds_list:
                o = odds_list[0]
                ml = o.get("moneyline") or {}
                home_ml = ((ml.get("home") or {}).get("close") or {}).get("odds")
                away_ml = ((ml.get("away") or {}).get("close") or {}).get("odds")
                odds = {
                    "provider": ((o.get("provider") or {}).get("displayName")
                                 or (o.get("provider") or {}).get("name") or "ESPN"),
                    "details": o.get("details", ""),
                    "spread": o.get("spread"),
                    "total": o.get("overUnder"),
                    "away_ml": away_ml,
                    "home_ml": home_ml,
                }
            out["games"].append({
                "date_iso": ev.get("date", ""),
                "away_name": sides["away"]["name"],
                "home_name": sides["home"]["name"],
                "away_abbr": sides["away"]["abbr"],
                "home_abbr": sides["home"]["abbr"],
                "away_record": sides["away"]["record"],
                "home_record": sides["home"]["record"],
                "away_score": sides["away"]["score"],
                "home_score": sides["home"]["score"],
                "time": parse_time(ev.get("date", "")),
                "state": state,
                "odds": odds,
            })
        out["games"].sort(key=lambda g: g.get("date_iso", ""))
        for g in out["games"]:
            g.pop("date_iso", None)
    with open(dst, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {dst} with {len(out['games'])} NFL games (week {out['week']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
