"""Dedupe POIs, build candidates, compute features and score them."""
from __future__ import annotations

import json
import math
import uuid
from collections import defaultdict

import h3
import pandas as pd

from porpea.common import H3_RES, haversine_m, now_utc, ring_k


# ---------- POI dedupe across sources ----------

def active_pois(con, cfg: dict) -> pd.DataFrame:
    """POIs minus closed places and cross-source duplicates (higher-priority source wins)."""
    df = con.execute(
        "SELECT * FROM poi WHERE coalesce(status, '') NOT LIKE 'CLOSED%'"
    ).df()
    if df.empty:
        return df
    priority = {s: i for i, s in enumerate(cfg["source_priority"])}
    df["_prio"] = df["source"].map(priority).fillna(len(priority))
    df = df.sort_values("_prio")
    keep = []
    seen: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    radius = cfg["dedupe_m"]
    for row in df.itertuples():
        near = h3.grid_disk(row.h3_r9, 1)
        dup = any(
            haversine_m(row.lat, row.lon, lat, lon) <= radius
            for cell in near for lat, lon in seen[(row.category, cell)]
        )
        if not dup:
            seen[(row.category, row.h3_r9)].append((row.lat, row.lon))
        keep.append(not dup)
    return df[keep].drop(columns="_prio").reset_index(drop=True)


# ---------- candidates ----------

def build_candidates(con, cfg: dict) -> int:
    pois = active_pois(con, cfg)
    anchors = pois[pois.category.isin(cfg["candidates"]["anchor_categories"])]
    cand = pd.DataFrame({
        "candidate_id": anchors["poi_uid"],
        "anchor_poi_uid": anchors["poi_uid"],
        "anchor_category": anchors["category"],
        "name": anchors["name"],
        "lat": anchors["lat"],
        "lon": anchors["lon"],
        "h3_r9": anchors["h3_r9"],
    })
    con.execute("DELETE FROM candidate")
    con.register("_cand", cand)
    con.execute("INSERT INTO candidate SELECT * FROM _cand")
    con.unregister("_cand")
    print(f"[candidates] {len(cand)} anchors")
    return len(cand)


# ---------- features ----------

class PointIndex:
    """Points bucketed by H3 r9 cell for fast radius queries."""

    def __init__(self):
        self.cells: dict[str, list[tuple]] = defaultdict(list)

    def add(self, cell: str, lat: float, lon: float, value: float, uid: str = ""):
        self.cells[cell].append((lat, lon, value, uid))

    def items_within(self, lat, lon, radius_m, exclude_uid=None):
        """Yield (distance_m, value, uid) for points within radius_m."""
        center = h3.latlng_to_cell(lat, lon, H3_RES)
        for cell in h3.grid_disk(center, ring_k(radius_m)):
            for plat, plon, val, uid in self.cells.get(cell, ()):
                if uid and uid == exclude_uid:
                    continue
                d = haversine_m(lat, lon, plat, plon)
                if d <= radius_m:
                    yield d, val, uid

    def within(self, lat, lon, radius_m, exclude_uid=None):
        for d, val, _ in self.items_within(lat, lon, radius_m, exclude_uid):
            yield d, val


def _population_index(con) -> PointIndex:
    idx = PointIndex()
    for cell, res, pop in con.execute("SELECT h3, res, population FROM population_hex").fetchall():
        if res < H3_RES:
            children = h3.cell_to_children(cell, H3_RES)
            share = pop / len(children)
            for ch in children:
                idx.add(ch, *h3.cell_to_latlng(ch), share, ch)
        else:
            parent = h3.cell_to_parent(cell, H3_RES) if res > H3_RES else cell
            idx.add(parent, *h3.cell_to_latlng(cell), pop, cell)
    return idx


def _factory_index(con) -> PointIndex:
    idx = PointIndex()
    for fid, cell, lat, lon, workers in con.execute(
            "SELECT factory_id, h3_r9, lat, lon, coalesce(workers, 0) FROM factory").fetchall():
        idx.add(cell, lat, lon, workers, fid)
    return idx


def _transform(value: float, how: str | None) -> float:
    if how == "log1p":
        return math.log1p(max(value, 0))
    return value


def compute_features(con, cfg: dict) -> int:
    pois = active_pois(con, cfg)
    cands = con.execute("SELECT * FROM candidate").df()
    pop_idx = _population_index(con)
    fac_idx = _factory_index(con)

    by_field: dict[tuple[str, str], PointIndex] = {}

    def poi_index(category: str, field: str | None) -> PointIndex:
        key = (category, field or "")
        if key not in by_field:
            idx = PointIndex()
            sub = pois[pois.category == category]
            for r in sub.itertuples():
                val = getattr(r, field) if field else 1
                val = 0 if val is None or (isinstance(val, float) and math.isnan(val)) else val
                idx.add(r.h3_r9, r.lat, r.lon, float(val), r.poi_uid)
            by_field[key] = idx
        return by_field[key]

    anchor_lookup = pois.set_index("poi_uid")
    rows = []
    for c in cands.itertuples():
        for f in cfg["features"]:
            t = f["type"]
            if t == "population":
                v = sum(val for _, val in pop_idx.within(c.lat, c.lon, f["radius_m"]))
            elif t == "factory_workers":
                v = sum(val for _, val in fac_idx.within(c.lat, c.lon, f["radius_m"]))
            elif t in ("count", "sum"):
                field = f.get("field") if t == "sum" else None
                v = sum(
                    val
                    for cat in f["categories"]
                    for _, val in poi_index(cat, field).within(
                        c.lat, c.lon, f["radius_m"], exclude_uid=c.anchor_poi_uid)
                )
            elif t == "nearest":
                cap = f["cap_m"]
                dists = [
                    d
                    for cat in f["categories"]
                    for d, _ in poi_index(cat, None).within(
                        c.lat, c.lon, cap, exclude_uid=c.anchor_poi_uid)
                ]
                v = min(dists, default=cap)
            elif t == "anchor":
                raw = anchor_lookup.at[c.anchor_poi_uid, f["field"]] \
                    if c.anchor_poi_uid in anchor_lookup.index else None
                v = 0.0 if raw is None or pd.isna(raw) else float(raw)
            else:
                raise ValueError(f"unknown feature type {t!r}")
            rows.append((c.candidate_id, f["name"], _transform(float(v), f.get("transform"))))

    df = pd.DataFrame(rows, columns=["candidate_id", "feature", "value"])
    con.execute("DELETE FROM candidate_feature")
    con.register("_feat", df)
    con.execute("INSERT INTO candidate_feature SELECT * FROM _feat")
    con.unregister("_feat")
    print(f"[features] {len(cands)} candidates x {len(cfg['features'])} features")
    return len(df)


# ---------- scoring ----------

def score(con, cfg: dict) -> str:
    weights: dict[str, float] = cfg["weights"]
    feats = con.execute("SELECT * FROM candidate_feature").df()
    if feats.empty:
        raise SystemExit("no features; run `features` first")
    wide = feats.pivot(index="candidate_id", columns="feature", values="value")
    pct = wide.rank(pct=True, method="average")

    pos = sum(w for w in weights.values() if w > 0)
    neg = sum(w for w in weights.values() if w < 0)
    contrib = pd.DataFrame({f: pct[f] * w for f, w in weights.items() if f in pct})
    raw = contrib.sum(axis=1)
    scaled = 100 * (raw - neg) / (pos - neg)

    flag_cfg = cfg.get("flags", {})
    flags = pd.Series("", index=wide.index)
    if "competitor_within_m" in flag_cfg and "dist_competitor" in wide:
        hit = wide["dist_competitor"] <= flag_cfg["competitor_within_m"]
        flags[hit] += "competitor_close;"
    if "min_pop_1000" in flag_cfg and "pop_1000" in wide:
        flags[wide["pop_1000"] < flag_cfg["min_pop_1000"]] += "low_population;"

    run_id = now_utc().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    out = pd.DataFrame({
        "run_id": run_id,
        "candidate_id": wide.index,
        "score": scaled.round(2).values,
        "rank": scaled.rank(ascending=False, method="min").astype(int).values,
        "breakdown": [json.dumps({k: round(v, 4) for k, v in row.items()})
                      for row in contrib.round(4).to_dict("records")],
        "flags": flags.values,
    })
    con.execute("INSERT INTO score_run VALUES (?, ?, ?)", [
        run_id, now_utc(), json.dumps({"weights": weights, "flags": flag_cfg})])
    con.register("_score", out)
    con.execute("INSERT INTO candidate_score SELECT * FROM _score")
    con.unregister("_score")
    print(f"[score] run {run_id}: scored {len(out)} candidates")
    return run_id


# ---------- zones ----------

def _cluster(points: pd.DataFrame, link_m: float) -> list[list[int]]:
    """Single-linkage clustering: points within link_m (directly or via a chain) share a zone."""
    parent = list(range(len(points)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    idx = PointIndex()
    for i, r in enumerate(points.itertuples()):
        idx.add(r.h3_r9, r.lat, r.lon, i)
    for i, r in enumerate(points.itertuples()):
        for _, j in idx.within(r.lat, r.lon, link_m):
            parent[find(i)] = find(int(j))
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(points)):
        groups[find(i)].append(i)
    return list(groups.values())


def _zone_score(scores: list[float], method: str) -> float:
    s = sorted(scores, reverse=True)
    if method == "max":
        return s[0]
    if method == "mean":
        return sum(s) / len(s)
    top = s[:3]
    return sum(top) / len(top)


def build_zones(con, cfg: dict, run_id: str) -> int:
    zcfg = cfg["zones"]
    cands = con.execute("""
        SELECT c.*, s.score FROM candidate c
        JOIN candidate_score s USING (candidate_id) WHERE s.run_id = ?
    """, [run_id]).df()
    pois = active_pois(con, cfg)
    cat_idx: dict[str, PointIndex] = {}
    for cat in zcfg["summary_categories"]:
        idx = PointIndex()
        for r in pois[pois.category == cat].itertuples():
            idx.add(r.h3_r9, r.lat, r.lon, 1.0, r.poi_uid)
        cat_idx[cat] = idx
    pop_idx = _population_index(con)
    fac_idx = _factory_index(con)
    radius = zcfg["env_radius_m"]

    zones, members = [], []
    for group in _cluster(cands, zcfg["link_m"]):
        g = cands.iloc[group]
        exclude = set(g.candidate_id)
        summary = {"markets": len(g)}
        for cat, idx in cat_idx.items():
            uids = {uid for r in g.itertuples()
                    for _, _, uid in idx.items_within(r.lat, r.lon, radius)}
            summary[cat] = len(uids - exclude)
        pop = {uid: v for r in g.itertuples() for _, v, uid in pop_idx.items_within(r.lat, r.lon, radius)}
        fac = {uid: v for r in g.itertuples() for _, v, uid in fac_idx.items_within(r.lat, r.lon, radius)}
        summary["population"] = round(sum(pop.values()))
        summary["factory_workers"] = int(sum(fac.values()))
        best = g.loc[g.score.idxmax()]
        zones.append({
            "score": round(_zone_score(list(g.score), zcfg["score_method"]), 2),
            "n_markets": len(g),
            "lat": g.lat.mean(),
            "lon": g.lon.mean(),
            "best_candidate_id": best.candidate_id,
            "best_score": best.score,
            "summary": json.dumps(summary, ensure_ascii=False),
            "_members": list(g.candidate_id),
        })

    # Blend in zone size so a cluster of good markets can outrank a lone one.
    size_w = zcfg.get("size_weight", 0.0)
    if size_w and zones:
        size_pct = pd.Series([z["n_markets"] for z in zones]).rank(pct=True)
        for z, pct in zip(zones, size_pct):
            z["score"] = round((1 - size_w) * z["score"] + size_w * 100 * pct, 2)
    zones.sort(key=lambda z: (-z["score"], -z["n_markets"]))
    for rank, z in enumerate(zones, 1):
        z["zone_id"] = f"Z{rank:03d}"
        z["rank"] = rank
        members += [(run_id, z["zone_id"], cid) for cid in z.pop("_members")]
    zdf = pd.DataFrame(zones)
    zdf.insert(0, "run_id", run_id)
    zdf = zdf[["run_id", "zone_id", "rank", "score", "n_markets", "lat", "lon",
               "best_candidate_id", "best_score", "summary"]]
    con.execute("DELETE FROM zone WHERE run_id = ?", [run_id])
    con.execute("DELETE FROM zone_member WHERE run_id = ?", [run_id])
    con.register("_zone", zdf)
    con.execute("INSERT INTO zone SELECT * FROM _zone")
    con.unregister("_zone")
    con.executemany("INSERT INTO zone_member VALUES (?, ?, ?)", members)
    print(f"[zones] {len(cands)} markets -> {len(zdf)} zones")
    return len(zdf)
