"""Import REAL Upwork job postings from Kaggle CSVs in data/raw/.

Produces:
  data/processed/market_stats.json  hourly/fixed price quantiles per category (pricing statistics)
  gigsim/data/market_jobs.json      ~1,500 historical + a live stream of real postings for GigSim

Columns are auto-detected because the Kaggle datasets differ. Every row keeps
"source": "kaggle:<file>" so real data is never confused with synthetic data.
Licences and attribution: see docs/DATA_CARD.md.

Run:  uv run python -m data.generators.import_kaggle
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from data.generators.skills import CATEGORIES, SKILLS  # noqa: E402

CANDIDATES = {
    "title": ["title", "job_title", "jobtitle", "name"],
    "description": ["description", "job_description", "desc", "details", "summary"],
    "hourly_low": ["hourly_low", "min_hourly", "hourly_min", "hourlyrate_min", "rate_min"],
    "hourly_high": ["hourly_high", "max_hourly", "hourly_max", "hourlyrate_max", "rate_max"],
    "budget": ["budget", "fixed_price", "fixed_budget", "price", "amount"],
    "is_hourly": ["is_hourly", "hourly", "job_type", "type"],
    "country": ["country", "client_country", "location"],
    "date": ["published_date", "date", "posted", "created_at", "publish_time"],
    "skills": ["skills", "tags", "required_skills", "skill"],
}


def pick(cols: list[str], names: list[str]) -> str | None:
    low = {c.lower().strip(): c for c in cols}
    for n in names:
        if n in low:
            return low[n]
    return None


def to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(r"[^0-9.]", "", regex=True), errors="coerce")


def categorise(text: str) -> str:
    text = text.lower()
    best, score = "Other", 0
    for cat, skills in CATEGORIES.items():
        sc = sum(1 for s in skills for n in SKILLS[s]["names"] if re.search(r"\b" + re.escape(n.lower()) + r"\b", text))
        if sc > score:
            best, score = cat, sc
    return best


def load_all(raw: Path) -> pd.DataFrame:
    frames = []
    for f in sorted(raw.glob("*.csv")):
        df = pd.read_csv(f, low_memory=False, on_bad_lines="skip")
        cols = list(df.columns)
        m = {k: pick(cols, v) for k, v in CANDIDATES.items()}
        if not m["title"]:
            print(f"skip {f.name}: no title column ({cols[:8]})")
            continue
        out = pd.DataFrame({"title": df[m["title"]].astype(str)})
        out["description"] = df[m["description"]].astype(str) if m["description"] else ""
        out["hourly_low"] = to_num(df[m["hourly_low"]]) if m["hourly_low"] else np.nan
        out["hourly_high"] = to_num(df[m["hourly_high"]]) if m["hourly_high"] else np.nan
        out["budget"] = to_num(df[m["budget"]]) if m["budget"] else np.nan
        if m["is_hourly"]:
            v = df[m["is_hourly"]].astype(str).str.lower()
            out["is_hourly"] = v.isin(["true", "1", "hourly", "yes"])
        else:
            out["is_hourly"] = out["hourly_low"].notna()
        out["country"] = df[m["country"]].astype(str) if m["country"] else ""
        out["date"] = df[m["date"]].astype(str) if m["date"] else ""
        out["skills_raw"] = df[m["skills"]].astype(str) if m["skills"] else ""
        out["source"] = f"kaggle:{f.stem}"
        frames.append(out)
        print(f"loaded {f.name}: {len(out)} rows, mapped={ {k: v for k, v in m.items() if v} }")
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["title", "description"])
    df["category"] = (df["title"] + " " + df["description"].str[:600] + " " + df["skills_raw"]).map(categorise)
    return df


def main() -> None:
    raw = ROOT / "data" / "raw"
    df = load_all(raw)
    if df.empty:
        print("No Kaggle CSVs found in data/raw/ — download them first (see docs/DATA_CARD.md).")
        return
    stats = {}
    for cat, g in df.groupby("category"):
        hourly = pd.concat([g["hourly_low"], g["hourly_high"]]).dropna()
        hourly = hourly[(hourly >= 3) & (hourly <= 300)]
        fixed = g.loc[~g["is_hourly"], "budget"].dropna()
        fixed = fixed[(fixed >= 5) & (fixed <= 100000)]
        if len(hourly) < 20:
            continue
        stats[cat] = {"hourly_p25": float(hourly.quantile(.25)), "hourly_p50": float(hourly.quantile(.5)),
                      "hourly_p75": float(hourly.quantile(.75)), "fixed_p25": float(fixed.quantile(.25)) if len(fixed) else None,
                      "fixed_p50": float(fixed.quantile(.5)) if len(fixed) else None,
                      "fixed_p75": float(fixed.quantile(.75)) if len(fixed) else None,
                      "n_jobs": int(len(g)), "source": "kaggle"}
    all_h = pd.concat([df["hourly_low"], df["hourly_high"]]).dropna()
    all_h = all_h[(all_h >= 3) & (all_h <= 300)]
    stats["_default"] = {"hourly_p25": float(all_h.quantile(.25)), "hourly_p50": float(all_h.quantile(.5)),
                         "hourly_p75": float(all_h.quantile(.75)), "n_jobs": int(len(df)), "source": "kaggle"}
    out = ROOT / "data" / "processed"
    out.mkdir(parents=True, exist_ok=True)
    (out / "market_stats.json").write_text(json.dumps(stats, indent=1))

    # sample real postings for GigSim: 1,500 historical + 300 live stream (relevant categories only)
    rng = random.Random(11)
    rel = df[(df["category"] != "Other") & (df["description"].str.len() > 80)]
    if len(rel) < 300:
        rel = df[df["category"] != "Other"]
    rel = rel.sample(n=min(1800, len(rel)), random_state=11)
    clients = json.loads((ROOT / "gigsim" / "data" / "clients.json").read_text())
    legit = [c["id"] for c in clients if not c["is_scam"]]
    jobs = []
    for i, r in enumerate(rel.itertuples()):
        hourly = bool(r.is_hourly) and not np.isnan(r.hourly_low if r.hourly_low == r.hourly_low else np.nan)
        if hourly:
            hi = r.hourly_high if r.hourly_high == r.hourly_high else r.hourly_low * 1.5
            budget = {"type": "hourly", "min": float(r.hourly_low), "max": float(hi)}
        else:
            amt = r.budget if r.budget == r.budget else 500.0
            budget = {"type": "fixed", "amount": float(amt)}
        jobs.append({"id": f"k-{i:05d}", "title": r.title[:200], "description": (r.description or "")[:4000],
                     "category": r.category, "budget": budget, "client_id": rng.choice(legit),
                     "screening_questions": [], "connects_cost": 4,
                     "posted_at_offset_min": (-rng.randint(1, 60 * 24 * 90)) if i < 1500 else rng.randint(0, 60 * 24 * 14),
                     "source": r.source, "country": r.country})
    (ROOT / "gigsim" / "data" / "market_jobs.json").write_text(json.dumps(jobs))
    print(f"market_stats categories={list(stats)}; market_jobs={len(jobs)} (real)")


if __name__ == "__main__":
    main()
