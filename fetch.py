#!/usr/bin/env python3
"""Fetch the last ~3 h of wind obs for every station in index.html's config and write data.json.

Stdlib only (Python 3.9+). Run every 5 min from cron, e.g.
  */5 * * * * cd /path/to/site && /usr/bin/python3 fetch.py >> fetch.log 2>&1
data.json keeps a rolling history, so Ambient Weather (latest-only) and the Tempest copy
(~10 rows) build up a full 3 h table over time. No API keys or tokens are used.
"""
import datetime as dt, html, json, os, re, sys, urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "bossman-windbot (ian.noack@mail.grokbot.com)"
KT = {"km_h-1": 0.539957, "m_s-1": 1.94384, "mph": 0.868976, "kt": 1.0}
MT = ZoneInfo("America/Denver")
PTS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()


def get(url, accept="*/*", timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rnd(x):
    return None if x is None else int(round(x))


def load_config():
    t = open(os.path.join(HERE, "index.html"), encoding="utf-8").read()
    m = re.search(r'<script type="application/json" id="config">(.*?)</script>', t, re.S)
    return json.loads(m.group(1))


def fetch_nws(s, start):
    d = json.loads(get(f"https://api.weather.gov/stations/{s['id']}/observations?start={iso(start)}",
                       "application/geo+json"))
    out = []
    for f in d.get("features", []):
        p = f["properties"]
        ws, wg, wd = p.get("windSpeed") or {}, p.get("windGust") or {}, p.get("windDirection") or {}
        if ws.get("value") is None:
            continue  # skip obs with no wind (e.g. UTDCD's newest)
        fs = KT.get((ws.get("unitCode") or "").split(":")[-1])
        fg = KT.get((wg.get("unitCode") or "").split(":")[-1]) or fs
        if not fs:
            continue
        out.append({"t": iso(dt.datetime.fromisoformat(p["timestamp"])),
                    "dir": rnd(wd.get("value")), "kt": rnd(ws["value"] * fs),
                    "gkt": None if wg.get("value") is None else rnd(wg["value"] * fg)})
    return out


def fetch_awn(s):
    d = json.loads(get("https://lightning.ambientweather.net/devices?public.slug=" + s["slug"], "application/json"))
    ld = d["data"][0]["lastData"]
    # Only public weather fields are read; no device identifiers are stored.
    if ld.get("windspeedmph") is None:
        return []
    t = dt.datetime.fromtimestamp(ld["dateutc"] / 1000, dt.timezone.utc)
    return [{"t": iso(t), "dir": rnd(ld.get("winddir")), "kt": rnd(ld["windspeedmph"] * KT["mph"]),
             "gkt": None if ld.get("windgustmph") is None else rnd(ld["windgustmph"] * KT["mph"])}]


def parse_tempest(raw, section, now):
    t = raw.decode("utf-8", "ignore")
    tables = re.findall(r"(?is)<table>(.*?)</table>", t)
    tbl = next((x for x in tables if section.lower() in x.lower()), None)
    if tbl is None:
        raise ValueError(f"section '{section}' not found")
    out = []
    for row in re.findall(r"(?is)<tr>(.*?)</tr>", tbl):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)]
        if len(cells) < 4:
            continue
        m = re.match(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})\s*([AP]M)", cells[0], re.I)
        rng = re.match(r"(\d+)\s*-\s*(\d+)", cells[3])
        comp = cells[2].upper()
        if not m or comp not in PTS:
            continue
        mo, da, hh, mi, ap = int(m[1]), int(m[2]), int(m[3]) % 12, int(m[4]), m[5].upper()
        hh += 12 if ap == "PM" else 0
        year = now.astimezone(MT).year
        lt = dt.datetime(year, mo, da, hh, mi, tzinfo=MT)
        if lt > now + dt.timedelta(days=2):  # Dec/Jan rollover
            lt = lt.replace(year=year - 1)
        if rng:
            lo, hi = int(rng[1]), int(rng[2])
        elif cells[3].strip().isdigit():
            lo = hi = int(cells[3])
        else:
            continue
        out.append({"t": iso(lt), "dir": None, "compass": comp, "compass_only": True,
                    "lull": rnd(lo * KT["mph"]), "kt": rnd(lo * KT["mph"]), "gkt": rnd(hi * KT["mph"])})
    return out


def main():
    cfg = load_config()
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(hours=cfg["hours"])
    keep_after = start - dt.timedelta(minutes=10)
    path = os.path.join(HERE, "data.json")
    try:
        prev = json.load(open(path)).get("stations", {})
    except Exception:
        prev = {}
    result = {}
    for lake in cfg["lakes"]:
        for s in lake["stations"]:
            entry = {"ok": False, "error": None, "obs": []}
            try:
                if s["type"] == "nws":
                    new = fetch_nws(s, start)
                elif s["type"] == "awn":
                    new = fetch_awn(s)
                elif s["type"] == "tempest":
                    new = parse_tempest(get(s["copy_url"], "text/html", 20), s["section"], now)
                else:
                    new = []
                entry["ok"] = True
            except Exception as e:  # never invent data: record the failure
                new = []
                entry["error"] = f"{type(e).__name__}: {e}"[:200]
            merged = {o["t"]: o for o in prev.get(s["id"], {}).get("obs", [])}
            merged.update({o["t"]: o for o in new})
            entry["obs"] = sorted((o for o in merged.values()
                                   if dt.datetime.fromisoformat(o["t"].replace("Z", "+00:00")) >= keep_after),
                                  key=lambda o: o["t"], reverse=True)
            entry["fetched_new"] = len(new)
            result[s["id"]] = entry
            newest = entry["obs"][0] if entry["obs"] else None
            print(f"{s['id']:6} ok={entry['ok']} new={len(new):3} kept={len(entry['obs']):3} newest={newest}"
                  + (f" ERR {entry['error']}" if entry["error"] else ""))
    out = {"generated_utc": iso(now), "hours": cfg["hours"], "stations": result}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    os.replace(tmp, path)


if __name__ == "__main__":
    sys.exit(main())
