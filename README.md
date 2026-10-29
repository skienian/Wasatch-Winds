# Wasatch Winds

Wind observations for Grantsville (GV), Deer Creek (DC), and Jordanelle (JV): 12 stations, about the last 3 hours, times in Mountain Time.

Site: https://skienian.github.io/Wasatch-Winds/ (after Pages is turned on; see below).

## The page

`index.html` is a self-contained static page. It loads `data.json` when that file is present, then also fetches live data in the browser:

- **api.weather.gov** for the 10 NWS, UDOT, and PacifiCorp stations (CORS `*`, so it works on any static host).
- **Ambient Weather** public dashboard for Grantsville Reservoir. That endpoint allows CORS, but it returns the **latest reading only**.

The page redraws every 5 minutes and when the tab regains focus. The newest row is highlighted. A station is marked STALE when its newest observation is older than 45 minutes. Gaps in the NWS feed are marked and linked to the weather.gov timeseries page.

With no `data.json`, the page still works: the 10 NWS stations show a full 3 hours, Grantsville shows the latest observation only, and Barbed Wire Beach shows a link-only card.

## Automatic refresh

`.github/workflows/refresh.yml` checks out this repo and runs `python3 fetch.py` on a schedule set in Mountain Time (America/Denver, so MDT and MST are both handled):

- **05:00–16:59 MT**: about every 5 minutes. Each run fetches every 5 minutes for about 28 minutes, then queues the next run itself (`workflow_dispatch`), so the daytime cadence does not depend on GitHub's cron, which GitHub often delays or thins out.
- **17:00–04:59 MT**: about once an hour. The cron (minutes 7 and 37) fires every 30 minutes, and a night run fetches only when `data.json` is at least 50 minutes old.

It also runs on manual dispatch and on every push to `main`. The script is Python 3.9+, standard library only, and uses public endpoints — no API keys or tokens.

`fetch.py` reads the station list from `index.html` and rewrites `data.json` with a rolling 3-hour history. It keeps the previous `data.json` and merges new readings into it. That matters for:

- **Barbed Wire Beach (Tempest)**: scraped from http://65.130.222.29/fastDC.htm (plain HTTP, no CORS, so a browser on this HTTPS site cannot read it).
- **Grantsville Reservoir history**: Ambient’s public endpoint only gives the current observation, so each run appends the new reading.

If `data.json` changed, the workflow commits only that file as `github-actions[bot]`. The message includes `[skip ci]`, so the commit does not start another run.

## GitHub Pages

The repo is set up for **Deploy from a branch** (no extra deploy workflow):

1. Open the repo **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
3. Set **Branch** to `main` and the folder to **`/ (root)`**.
4. Click **Save**.

The site is then at https://skienian.github.io/Wasatch-Winds/. `.nojekyll` is in the root so Pages serves the files as-is.

## Not used (by design)

- weather.gov/wrh/timeseries pulls from api.synopticdata.com with a token, so it is not used. The page links to it instead.
- Ambient’s history endpoint needs the device MAC, so it is not used. Only public weather fields (time, direction, speed, gust) are read.
- The Tempest API needs a token, so it is not used.
