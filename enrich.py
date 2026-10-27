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
- Model block (per game, under key "model"): expected goals for/against
  (MoneyPuck, all situations, per game), power play % and penalty kill %
  (NHL stats API, season to date), a rest flag (back-to-back, days of
  rest, or season opener, from the club schedule), a goalie edge (the
  starter's save % minus the opposing starter's save %, in percentage
  points), and a Poisson model win % with its edge against the
  FanDuel moneyline after removing the vig. See model_prob() for the
  full formula. Any metric whose source failed is None, never guessed;
  a game with no FanDuel moneyline gets no market edge ("no line").

Stdlib only. Sources are all public api-web.nhle.com endpoints, the
same ones nhl_daily.py uses (urllib follows the /now redirects), plus
the keyless NHL stats API (api.nhle.com) and MoneyPuck's public
team CSV. Never fails the build: every fetch is guarded, and the
script always exits 0, leaving today.json usable even if enrichment
is partial.
"""
import csv
import io
import json
import math
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta, timezone

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
    # NFKD + strip combining marks so accented names (Meriläinen)
    # match their unaccented spellings (Merilainen) from other sources.
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def full_name(place, common):
    place = (place or "").strip()
    common = (common or "").strip()
    if place and common:
        return f"{place} {common}"
    return place or common or ""


def team_analytics(abbr, date_s):
    """Return (last10_record, last10_gp, home_gf, home_ga, away_gf, away_ga,
    rest_days, back_to_back, three_in_four).

    Regular-season finals only (gameType 2, gameState FINAL/OFF).
    A loss in OT/SO counts as an overtime loss.
    Rest is measured against the slate date: rest_days is the number of
    days since the team's last completed game before the slate date
    (None when the team has not played yet, i.e. a season opener);
    back_to_back is True when the team played yesterday; three_in_four
    is True when the team played at least 3 games in the 3 days before
    the slate date (today would be its 3rd game in 4 nights).
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
    rest_days = None
    back_to_back = False
    three_in_four = False
    try:
        slate = date.fromisoformat(date_s)
        prev = []
        for g in games:
            gd = g.get("gameDate", "")
            if gd and gd < date_s:
                prev.append(g)
        if prev:
            last_date = date.fromisoformat(prev[-1].get("gameDate", ""))
            rest_days = (slate - last_date).days
            back_to_back = rest_days == 1
            recent = 0
            for g in prev:
                try:
                    if (slate - date.fromisoformat(g.get("gameDate", ""))).days <= 3:
                        recent += 1
                except ValueError:
                    continue
            three_in_four = recent >= 3
    except ValueError:
        pass
    return (
        f"{w}-{l}-{otl}",
        len(last),
        round(home_gf / home_gp, 1) if home_gp else None,
        round(home_ga / home_gp, 1) if home_gp else None,
        round(away_gf / away_gp, 1) if away_gp else None,
        round(away_ga / away_gp, 1) if away_gp else None,
        rest_days,
        back_to_back,
        three_in_four,
    )


def goalie_stats(abbr):
    """Return (lines, save_pcts).

    lines maps normalized goalie name -> 'SV% .925 · 1-1-0' season line;
    save_pcts maps the same keys -> numeric save percentage (0.925).
    Both fall back to last name only when it is unique on the team.
    """
    data = fetch_json(f"{NHL}/club-stats/{abbr}/now")
    out = {}
    svs = {}
    last_names = {}
    last_svs = {}
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
            if isinstance(sv, (int, float)):
                svs[norm(name)] = sv
                last_svs.setdefault(norm(ln), []).append(sv)
    # Fall back to last name only when it is unique on the team.
    for ln, lines in last_names.items():
        if len(lines) == 1 and ln not in out:
            out[ln] = lines[0]
    for ln, vals in last_svs.items():
        if len(vals) == 1 and ln not in svs:
            svs[ln] = vals[0]
    return out, svs


def goalie_name(line):
    """Extract the starter's name from a goalie_line string.

    'Jake Oettinger (confirmed)' -> 'Jake Oettinger'.
    'unconfirmed ...' -> None (no verified starter, so no stat line).
    """
    if not line or line.startswith("unconfirmed"):
        return None
    return line.split(" (")[0].strip() or None


def season_ids(date_s):
    """Return (nhl_season_id, moneypuck_season_year) for a slate date.

    The NHL season runs October-June: October-December dates belong to
    the season starting that year, January-June dates to the season
    started the previous year. E.g. 2026-10-27 -> (20262027, 2026).
    """
    try:
        y, m, _d = (int(x) for x in date_s.split("-"))
    except (ValueError, AttributeError):
        return None, None
    if m >= 10:
        return y * 10000 + (y + 1), y
    return (y - 1) * 10000 + y, y - 1


def team_special_teams(name_to_abbr, nhl_season):
    """Return {abbr: (power_play_pct, penalty_kill_pct)} as 0-1 floats.

    One keyless call to the NHL stats API team summary for the given
    season id (e.g. 20262027). Rows carry teamFullName but no
    abbreviation, so they are matched to abbreviations through the
    schedule's full names. A failed fetch or an unmatched team yields
    no entry (None later), never a guessed number.
    """
    out = {}
    if not nhl_season:
        return out
    data = fetch_json(
        "https://api.nhle.com/stats/rest/en/team/summary"
        f"?cayenneExp=seasonId={nhl_season}"
    )
    if not data:
        return out
    for row in data.get("data", []):
        abbr = name_to_abbr.get(norm(row.get("teamFullName", "")))
        if not abbr:
            continue
        pp = row.get("powerPlayPct")
        pk = row.get("penaltyKillPct")
        out[abbr] = (
            pp if isinstance(pp, (int, float)) else None,
            pk if isinstance(pk, (int, float)) else None,
        )
    return out


def team_xg(mp_year):
    """Return {abbr: (xgf_per_game, xga_per_game)} from MoneyPuck.

    MoneyPuck's public team CSV, "all" situations rows only (5v5-only
    rows would understate scoring). xGoalsFor/xGoalsAgainst are season
    totals, so they are divided by games played. The CSV's team column
    uses standard NHL abbreviations. A failed fetch or parse yields no
    entries, never invented numbers.
    """
    out = {}
    if not mp_year:
        return out
    req = urllib.request.Request(
        f"https://moneypuck.com/moneypuck/playerData/seasonSummary/{mp_year}/regular/teams.csv",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"enrich: moneypuck fetch failed: {type(e).__name__}", file=sys.stderr)
        return out
    try:
        for row in csv.DictReader(io.StringIO(text)):
            if row.get("situation") != "all":
                continue
            abbr = (row.get("team") or "").strip()
            try:
                gp = float(row.get("games_played") or 0)
                xgf = float(row.get("xGoalsFor") or 0)
                xga = float(row.get("xGoalsAgainst") or 0)
            except (TypeError, ValueError):
                continue
            if abbr and gp:
                out[abbr] = (xgf / gp, xga / gp)
    except Exception as e:
        print(f"enrich: moneypuck parse failed: {type(e).__name__}", file=sys.stderr)
        return out
    return out


def poisson_pmf(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def model_prob(lam_a, lam_h):
    """Model win probabilities from expected goals, fully transparent.

    FORMULA (auditable, no fitted parameters):
      lam_a = (away team's away GF/GP + home team's home GA/GP) / 2
      lam_h = (home team's home GF/GP + away team's away GA/GP) / 2
      where the venue splits come from team_analytics(); when a split is
      missing, the season overall GF/GA from today.json is used instead.
      Goals for each team are Poisson(lam). P(away wins) is the sum of
      P(i > j) over goal counts i, j (truncated at 12 goals and
      renormalized over the truncated grid, so the symmetric case is
      exactly 50/50), plus half of the regulation-tie probability: a
      tie game goes to overtime/shootout, treated as a coin flip.
      P(home wins) = 1 - P(away wins).
    Deliberate limits, by design: no home-ice factor beyond what the
    venue splits already capture (adding one would double-count it), no
    goalie adjustment (the goalie edge is displayed separately, not
    folded into the model, so the model stays checkable by hand), and
    no shrinkage for small early-season samples (early-season numbers
    are noisy and the card shows season-to-date inputs, so the reader
    can see that). Returns (p_away, p_home) summing to 1, or None when
    either lambda is missing or non-positive.
    """
    if lam_a is None or lam_h is None or lam_a <= 0 or lam_h <= 0:
        return None
    p_a = 0.0
    p_tie = 0.0
    sum_a = 0.0
    sum_h = 0.0
    for i in range(13):
        pa = poisson_pmf(i, lam_a)
        sum_a += pa
        for j in range(13):
            pb = poisson_pmf(j, lam_h)
            if i > j:
                p_a += pa * pb
            elif i == j:
                p_tie += pa * pb
    for j in range(13):
        sum_h += poisson_pmf(j, lam_h)
    grid = sum_a * sum_h
    if grid <= 0:
        return None
    p_a = (p_a + 0.5 * p_tie) / grid
    return p_a, 1.0 - p_a


def price_to_prob(price):
    """Odds string -> implied probability 0-1.

    Handles both forms: American integers ('-152', '+198') and decimal
    odds ('1.521', '2.58'). ParlayAPI returns decimal odds, so a value
    with a fractional part is decimal; a plain integer is American.
    (The two forms never collide: American odds are always integers.)
    """
    try:
        s = str(price).strip()
        if not s:
            return None
        if "." in s:
            d = float(s)
            if d > 1.0:
                return 1.0 / d
            return None
        p = int(s)
    except (TypeError, ValueError):
        return None
    if p == 0:
        return None
    if p > 0:
        return 100.0 / (p + 100.0)
    return (-p) / ((-p) + 100.0)


def rest_label(rest_days, back_to_back, three_in_four):
    """Human-readable rest flag for a team, or None when unknown."""
    if rest_days is None:
        return "Season opener"
    label = "Back-to-back" if back_to_back else f"{rest_days} days rest"
    if three_in_four:
        label += " · 3 in 4"
    return label


def build_model(g, a, h, analytics, special, xg, svs):
    """Build the per-game model dict consumed by render.py's Model block.

    Expected goals use venue splits when available (away team's away
    GF/GP vs home team's home GA/GP, and vice versa), falling back to
    season overall GF/GA from today.json when a split is missing.
    Market edge needs BOTH teams' FanDuel moneylines; with either
    missing, market/edge stay None and the card shows "no line".
    Nothing here raises: any missing input yields None for that field.
    """
    def avg(x, y):
        if x is None or y is None:
            return None
        return (x + y) / 2.0

    a_an = analytics.get(a)
    h_an = analytics.get(h)
    lam_a = avg(a_an[4] if a_an else None, h_an[3] if h_an else None)
    if lam_a is None:
        lam_a = avg(g.get("away_gf"), g.get("home_ga"))
    lam_h = avg(h_an[2] if h_an else None, a_an[5] if a_an else None)
    if lam_h is None:
        lam_h = avg(g.get("home_gf"), g.get("away_ga"))
    probs = model_prob(lam_a, lam_h)

    def starter_sv(side_key, abbr):
        name = goalie_name(g.get(side_key, ""))
        if name and abbr in svs:
            return svs[abbr].get(norm(name))
        return None

    sv_a = starter_sv("away_goalie", a)
    sv_h = starter_sv("home_goalie", h)
    edge_a = edge_h = None
    if sv_a is not None and sv_h is not None:
        edge_a = round((sv_a - sv_h) * 100, 1)
        edge_h = round((sv_h - sv_a) * 100, 1)

    def rest(an):
        if not an:
            return None
        return rest_label(an[6], an[7], an[8])

    a_x = xg.get(a)
    h_x = xg.get(h)
    a_sp = special.get(a)
    h_sp = special.get(h)

    odds = g.get("odds") or {}
    q_a = price_to_prob(odds.get("away_ml"))
    q_h = price_to_prob(odds.get("home_ml"))
    market_a = market_h = edge_ma = edge_mh = None
    if probs and q_a is not None and q_h is not None and (q_a + q_h) > 0:
        tot = q_a + q_h
        market_a = q_a / tot
        market_h = q_h / tot
        edge_ma = round((probs[0] - market_a) * 100, 1)
        edge_mh = round((probs[1] - market_h) * 100, 1)

    return {
        "away_xgf": a_x[0] if a_x else None,
        "away_xga": a_x[1] if a_x else None,
        "home_xgf": h_x[0] if h_x else None,
        "home_xga": h_x[1] if h_x else None,
        "away_pp": a_sp[0] if a_sp else None,
        "away_pk": a_sp[1] if a_sp else None,
        "home_pp": h_sp[0] if h_sp else None,
        "home_pk": h_sp[1] if h_sp else None,
        "away_rest": rest(a_an),
        "home_rest": rest(h_an),
        "away_goalie_edge": edge_a,
        "home_goalie_edge": edge_h,
        "away_lam": round(lam_a, 2) if lam_a is not None else None,
        "home_lam": round(lam_h, 2) if lam_h is not None else None,
        "away_prob": probs[0] if probs else None,
        "home_prob": probs[1] if probs else None,
        "away_market": market_a,
        "home_market": market_h,
        "away_edge": edge_ma,
        "home_edge": edge_mh,
    }


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
    svs = {}
    for abbr in teams:
        try:
            analytics[abbr] = team_analytics(abbr, date_s)
        except Exception as e:
            print(f"enrich: analytics failed for {abbr}: {e}", file=sys.stderr)
        try:
            stats[abbr], svs[abbr] = goalie_stats(abbr)
        except Exception as e:
            print(f"enrich: goalie stats failed for {abbr}: {e}", file=sys.stderr)

    # Model inputs from keyless sources, fetched once for the slate.
    # Any failure leaves that metric None for every game; nothing here
    # can fail the build.
    nhl_season, mp_year = season_ids(date_s)
    name_to_abbr = {norm(name): abbr for abbr, name in full.items()}
    try:
        special = team_special_teams(name_to_abbr, nhl_season)
    except Exception as e:
        print(f"enrich: special teams failed: {e}", file=sys.stderr)
        special = {}
    try:
        xg = team_xg(mp_year)
    except Exception as e:
        print(f"enrich: expected goals failed: {e}", file=sys.stderr)
        xg = {}

    for g in games:
        a, h = g.get("away_abbr", ""), g.get("home_abbr", "")
        if a in full:
            g["away_name"] = full[a]
        if h in full:
            g["home_name"] = full[h]
        if a in analytics:
            rec, gp, _hgf, _hga, agf, aga, _rd, _b2b, _tif = analytics[a]
            g["away_last10"] = rec
            g["away_last10_gp"] = gp
            g["away_away_gf"] = agf
            g["away_away_ga"] = aga
        if h in analytics:
            rec, gp, hgf, hga, _agf, _aga, _rd, _b2b, _tif = analytics[h]
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
        g["model"] = build_model(g, a, h, analytics, special, xg, svs)

    tmp = src + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, src)
    print(f"Enriched {src} with {len(games)} games (full names, form, splits, goalie stats).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
