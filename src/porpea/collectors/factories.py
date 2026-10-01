"""Load a factory list CSV (e.g. กรมโรงงานอุตสาหกรรม open data from data.go.th).

Column names differ between exports, so pass a mapping, e.g.
  --map id=เลขทะเบียนโรงงาน name=ชื่อโรงงาน lat=ละติจูด lon=ลองจิจูด workers=คนงานรวม
"""
from __future__ import annotations

import pandas as pd

from porpea.common import now_utc, to_h3

FIELDS = ["id", "name", "lat", "lon", "workers", "industry"]


def load(con, cfg: dict, path: str, mapping: dict[str, str], source: str = "diw") -> int:
    raw = pd.read_csv(path, dtype=str)
    df = pd.DataFrame({f: raw[mapping[f]] if f in mapping else None for f in FIELDS})
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["workers"] = pd.to_numeric(df["workers"], errors="coerce").fillna(0).astype(int)
    south, west, north, east = cfg["area"]["bbox"]
    df = df.dropna(subset=["lat", "lon"])
    df = df[df.lat.between(south, north) & df.lon.between(west, east)].copy()
    if df["id"].isna().all():
        df["id"] = [f"row{i}" for i in range(len(df))]
    out = pd.DataFrame({
        "factory_id": source + ":" + df["id"].astype(str),
        "name": df["name"],
        "lat": df["lat"],
        "lon": df["lon"],
        "h3_r9": [to_h3(a, b) for a, b in zip(df.lat, df.lon)],
        "workers": df["workers"],
        "industry": df["industry"],
        "source": source,
        "fetched_at": now_utc(),
    }).drop_duplicates("factory_id")
    con.register("_fac_in", out)
    con.execute("INSERT OR REPLACE INTO factory SELECT * FROM _fac_in")
    con.unregister("_fac_in")
    print(f"[factory] {len(out)} factories, {out['workers'].sum():,} workers")
    return len(out)
