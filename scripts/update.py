#!/usr/bin/env python3
"""Rebuild data/data.json from Plano Político (polls + model) and Polymarket.

Stdlib only. Run: python3 scripts/update.py
Any source that fails to fetch or parse aborts the run (non-zero exit) so a bad
day never overwrites good data with empty data.
"""
import csv, datetime as dt, json, re, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = {"User-Agent": "brazil-runoff-tracker/1.0 (+https://github.com/mmuzzi/brazil-runoff-tracker)"}
PP_AGG = "https://planopolitico.com.br/agregador/"
PP_MODEL = "https://planopolitico.com.br/modelos-eleitorais/presidencial/"
PM_EVENT = "https://gamma-api.polymarket.com/events?slug=brazil-presidential-election"
PM_HIST = "https://clob.polymarket.com/prices-history?market={}&interval=max&fidelity=1440"
ROUND1 = "2026-10-04"
RUNOFF = "2026-10-25"
START = "2026-04-01"
WINDOW_DAYS = {"pre": 30, "runoff": 14}  # pre-round polls are sparse
MIN_HOUSES = 3
# 2022 runoff (Lula × Bolsonaro), for comparison aligned on days before the runoff
ROUND1_2022 = "2022-10-02"
RUNOFF_2022 = "2022-10-30"
RESULT_2022 = {"bolsonaro": 49.10, "lula": 50.90}  # TSE final, valid votes

NAMES = {
    "NEXUS": "Nexus", "PALVER": "Palver", "INDEXA PESQUISAS": "Indexa",
    "ALFA INTELIGENCIA": "Alfa", "AMERICAN ANALYTICS": "American Analytics",
    "COLECTTA INSTITUTO DE PESQUISA E ESTATISTICA LTDA": "Colectta",
    "Boas Ideias": "Ideia", "MDA": "CNT/MDA", "Ipespe": "Ipespe/Abrapel",
}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
        return r.read().decode("utf-8")


def scripts(html):
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)


def find_json(html, must_have):
    for s in scripts(html):
        s = s.strip()
        if s.startswith("{") and must_have in s[:2000]:
            return json.loads(s)
    raise RuntimeError(f"no embedded JSON containing {must_have!r}")


def find_key(obj, key):
    """Depth-first search for a dict key (PP nests recent_polls oddly)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_key(v, key)
            if r is not None:
                return r
    return None


# ---------------------------------------------------------------- polls
def pp_polls_and_average():
    agg = find_json(get(PP_AGG), '"presidente_t1"')
    recent = find_key(agg, "recent_polls")
    if not recent or "t2" not in recent:
        raise RuntimeError("Plano Político: recent_polls.t2 missing")
    polls = []
    for p in recent["t2"]:
        if p.get("scope") != "BR":
            continue
        sh = p["shares"]
        lula, flavio = sh.get("Lula"), sh.get("Flávio Bolsonaro")
        if lula is None or flavio is None:
            continue
        polls.append({
            "end": p["dt_fim"], "start": p.get("dt_inicio"), "released": p.get("dt_divulgacao"),
            "pollster": NAMES.get(p["instituto"], p["instituto"]), "n": p.get("n"),
            "mode": p.get("method"), "reg": p.get("registro"), "url": p.get("url"),
            "lula": lula, "flavio": flavio, "source": "Plano Político",
        })
    if len(polls) < 100:
        raise RuntimeError(f"Plano Político: only {len(polls)} national polls parsed")

    t2 = agg["presidente_t2"]
    pre = t2["national_only"]["trajectory"]
    post = t2["post_first_round"]["national_only"]["trajectory"]
    avg = []
    for row, phase in [(r, "pre") for r in pre if r["week_end"] <= ROUND1] + [(r, "runoff") for r in post]:
        avg.append({"d": row["week_end"], "phase": phase,
                    "flavio": row["Flávio Bolsonaro"], "lula": row["Lula"],
                    "lo": row.get("Flávio Bolsonaro_lo"), "hi": row.get("Flávio Bolsonaro_hi")})
    return polls, avg


def extra_polls():
    out = []
    with open(DATA / "polls_extra.csv", newline="") as f:
        for r in csv.DictReader(f):
            out.append({"end": r["field_end"], "start": None, "released": None,
                        "pollster": r["pollster"], "n": int(r["sample"]), "mode": None,
                        "reg": r["registration"] or None, "url": None,
                        "lula": float(r["lula"]), "flavio": float(r["flavio"]), "source": r["source"]})
    return out


def house_average(polls, start, end, round1):
    """Day T = mean two-way share of each house's latest poll in (T-window, T].
    Pre- and post-first-round regimes are computed separately. Yields (T, phase, mean, houses)."""
    d = start
    while d <= end:
        T = d.isoformat()
        phase = "pre" if T <= round1 else "runoff"
        lo = (d - dt.timedelta(days=WINDOW_DAYS[phase])).isoformat()
        latest = {}
        for p in polls:
            if p["phase"] != phase or not (lo < p["end"] <= T):
                continue
            if p["pollster"] not in latest or p["end"] > latest[p["pollster"]]["end"]:
                latest[p["pollster"]] = p
        if len(latest) >= MIN_HOUSES:
            yield T, phase, sum(p["two_way"] for p in latest.values()) / len(latest), len(latest)
        d += dt.timedelta(days=1)


def our_average(polls, today):
    end = min(today, dt.date.fromisoformat(RUNOFF))
    return [{"d": T, "phase": ph, "flavio": round(v, 2), "lula": round(100 - v, 2), "houses": n}
            for T, ph, v, n in house_average(polls, dt.date.fromisoformat(START), end, ROUND1)]


def avg_2022():
    """2022 runoff average, same method, with each day shifted so RUNOFF_2022 lands on RUNOFF."""
    polls = []
    with open(DATA / "archive" / "polls_2022_runoff.csv", newline="") as f:
        for r in csv.DictReader(f):
            lula, bolso = float(r["lula"]), float(r["bolsonaro"])
            polls.append({"end": r["field_end"], "pollster": r["pollster"], "phase": "runoff",
                          "two_way": 100 * bolso / (bolso + lula)})
    r1, ro = dt.date.fromisoformat(ROUND1_2022), dt.date.fromisoformat(RUNOFF_2022)
    shift = dt.date.fromisoformat(RUNOFF) - ro
    out = [{"d": (dt.date.fromisoformat(T) + shift).isoformat(), "d22": T,
            "bolsonaro": round(v, 2), "lula": round(100 - v, 2), "houses": n}
           for T, _, v, n in house_average(polls, r1 + dt.timedelta(days=1), ro, ROUND1_2022)]
    if not out:
        raise RuntimeError("2022 average: no days with enough houses")
    return {"round1": ROUND1_2022, "runoff": RUNOFF_2022, "result": RESULT_2022, "avg": out}


# ---------------------------------------------------------------- model
def pp_model():
    html = get(PP_MODEL)
    i = html.find("Trajetória da previsão")
    j = html.find("</svg>", i)
    if i < 0 or j < 0:
        raise RuntimeError("Plano Político model: trajectory chart not found")
    seg = html[i:j]
    # Plot area: y=274 is 0%, y=34 is 100% (2.4px per point). Verified against p_wins.
    lines = {"lula": [], "flavio": []}
    for d, cand in re.findall(r'<path class="hist-line" d="([^"]+)"[^>]*stroke="var\(--cand-(\w+)\)"', seg):
        ys = [float(y) for _, y in re.findall(r"([\d.]+),([\d.]+)", d)]
        lines[cand].extend((274 - y) / 2.4 for y in ys)
    dates = [dt.datetime.strptime(x, "%d/%m/%Y").date().isoformat()
             for x in re.findall(r'class="hist-readout-date">([\d/]+)<', seg)]
    if not dates or len(dates) != len(lines["lula"]) or len(dates) != len(lines["flavio"]):
        raise RuntimeError(f"Plano Político model: {len(dates)} dates vs "
                           f"{len(lines['lula'])}/{len(lines['flavio'])} points")
    series = [{"d": d, "flavio": round(f, 1), "lula": round(l, 1)}
              for d, l, f in zip(dates, lines["lula"], lines["flavio"])]
    # The SVG is rounded to the pixel; use the exact headline for the latest day.
    meta = find_json(html, '"p_wins"')
    as_of = meta["meta"]["as_of"]
    pw = meta["p_wins"]
    exact = {"d": as_of, "flavio": pw["Flávio"], "lula": pw["Lula"]}
    series = [r for r in series if r["d"] != as_of] + [exact]
    # Keep history we already have for days the page no longer shows.
    hist_path = DATA / "model_history.json"
    old = json.loads(hist_path.read_text()) if hist_path.exists() else []
    merged = {r["d"]: r for r in old}
    merged.update({r["d"]: r for r in series})
    out = sorted(merged.values(), key=lambda r: r["d"])
    hist_path.write_text(json.dumps(out, ensure_ascii=False, indent=0))
    return out, {"t2": meta.get("t2"), "as_of": as_of}


# ---------------------------------------------------------------- market
def polymarket():
    ev = json.loads(get(PM_EVENT))[0]
    tokens = {}
    for m in ev["markets"]:
        q = m.get("question", "")
        if "Flávio Bolsonaro win" in q:
            tokens["flavio"] = (json.loads(m["clobTokenIds"])[0], float(json.loads(m["outcomePrices"])[0]))
        elif "Lula da Silva win" in q:
            tokens["lula"] = (json.loads(m["clobTokenIds"])[0], float(json.loads(m["outcomePrices"])[0]))
    if set(tokens) != {"flavio", "lula"}:
        raise RuntimeError(f"Polymarket: markets found {list(tokens)}")
    by_day = {}
    for cand, (tok, _) in tokens.items():
        hist = json.loads(get(PM_HIST.format(tok)))["history"]
        if not hist:
            raise RuntimeError(f"Polymarket: empty history for {cand}")
        for x in hist:
            d = dt.datetime.fromtimestamp(x["t"], dt.timezone.utc).date().isoformat()
            by_day.setdefault(d, {})[cand] = round(x["p"] * 100, 1)
    now = dt.datetime.now(dt.timezone.utc).date().isoformat()
    by_day.setdefault(now, {}).update({c: round(p * 100, 1) for c, (_, p) in tokens.items()})
    series = [{"d": d, **v} for d, v in sorted(by_day.items()) if d >= "2026-01-01"]
    return series, {"volume": ev.get("volume"), "url": "https://polymarket.com/event/brazil-presidential-election"}


def main():
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).date()  # Brasília
    pp, pp_avg = pp_polls_and_average()
    regs = {p["reg"] for p in pp if p["reg"]}
    polls = pp + [p for p in extra_polls() if p["reg"] not in regs]
    for p in polls:
        p["phase"] = "pre" if p["end"] <= ROUND1 else "runoff"
        p["two_way"] = round(100 * p["flavio"] / (p["flavio"] + p["lula"]), 2)
    polls.sort(key=lambda p: (p["end"], p["pollster"]))
    model, model_meta = pp_model()
    market, market_meta = polymarket()
    out = {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "round1": ROUND1, "runoff": RUNOFF, "start": START,
        "polls": polls,
        "avg_ours": our_average(polls, today),
        "avg_pp": [r for r in pp_avg if r["d"] >= START],
        "y2022": avg_2022(),
        "model": [r for r in model if r["d"] >= START],
        "model_meta": model_meta,
        "market": [r for r in market if r["d"] >= START],
        "market_meta": market_meta,
    }
    (DATA / "data.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    last = lambda s: s[-1]
    print(f"polls {len(polls)} (runoff {sum(p['phase']=='runoff' for p in polls)}), "
          f"ours {last(out['avg_ours'])['flavio']} Flávio, PP avg {last(out['avg_pp'])['flavio']}, "
          f"model {last(out['model'])['flavio']}%, market {last(out['market'])['flavio']}%")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # surface the failure, never write partial data
        print(f"update failed: {e}", file=sys.stderr)
        sys.exit(1)
