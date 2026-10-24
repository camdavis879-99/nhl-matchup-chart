# NHL Matchup Chart (auto-refreshing)

A daily NHL matchup chart that rebuilds itself every morning and
publishes to GitHub Pages. One card per game, in puck-drop order:
offense vs. defense bar pairs with league ranks, starting goalies
with BACKUP flags, stars-out lines, and FanDuel spreads and totals
(lines only, no prices).

## How it updates

The `daily` workflow runs every day at 15:00 UTC (8:00 AM Phoenix
time, before the day's games). It runs `nhl_daily.py` to fetch that
day's slate, renders `index.html` with `render.py`, and deploys it
to GitHub Pages. The published link then shows the new slate with
no manual step. Scheduled GitHub runs can lag a little, and the
workflow can also be run by hand from the Actions tab.

## Files

- `nhl_daily.py`: fetches the day's games, team scoring averages and
  ranks, starting goalies, star injuries, and FanDuel lines, then
  prints the text report and writes `today.json`. Python standard
  library only. This is a copy of the script used for the daily
  chat report; keep the two copies in sync when either changes.
- `render.py`: turns `today.json` into a self-contained `index.html`.
- `.github/workflows/daily.yml`: the schedule, build, and deploy.

## One-time setup

1. Create a GitHub repository and upload these files to it, keeping
   the `.github/workflows/daily.yml` path exactly.
2. In the repository, go to Settings, then Secrets and variables,
   then Actions, and add a repository secret named
   `PARLAY_API_KEY` holding your ParlayAPI key. The key is only
   ever used by the workflow run; it never appears in the page.
   Without it, the script falls back to Action Network articles
   for the games they cover, so some games would show no lines.
3. In Settings, then Pages, set Source to GitHub Actions.
4. Open the Actions tab, run the `daily` workflow once by hand,
   and open the Pages link it reports. Share that link, and pin
   it to a phone home screen from Safari with Share, then Add to
   Home Screen.

## Notes

- The page is public to anyone with the link, same as any
  published page. That is the point: it is meant to be shared.
- Lines move during the day. The page shows the morning lines
  from the scheduled run, not live moves.
- If a morning looks wrong, re-run the workflow from the
  Actions tab and check its log.
