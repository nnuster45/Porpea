"""Shared helpers: config, database, geo math, raw-response storage."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import h3
import pandas as pd
import yaml

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
H3_RES = 9

POI_COLUMNS = [
    "poi_uid", "source", "source_id", "category", "name", "brand", "lat", "lon",
    "h3_r9", "rating", "rating_count", "status", "extra", "fetched_at",
]


def load_config(path: str | Path = "config/settings.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def connect(cfg: dict) -> duckdb.DuckDBPyConnection:
    db_path = Path(cfg["db_path"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    return con


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_h3(lat: float, lon: float, res: int = H3_RES) -> str:
    return h3.latlng_to_cell(lat, lon, res)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def ring_k(radius_m: float, res: int = H3_RES) -> int:
    """Smallest k such that grid_disk(cell, k) covers a circle of radius_m."""
    spacing = math.sqrt(3) * h3.average_hexagon_edge_length(res, "m")
    return math.ceil(radius_m / spacing) + 1


def save_raw(cfg: dict, source: str, slug: str, payload) -> str:
    day = now_utc().strftime("%Y%m%d")
    out = Path(cfg["raw_dir"]) / source / day / f"{slug}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(out)


def log_fetch(con, source: str, query: str, n_items: int, raw_path: str) -> None:
    con.execute(
        "INSERT INTO fetch_log VALUES (?, ?, ?, ?, ?)",
        [source, query, now_utc(), n_items, raw_path],
    )


def upsert_pois(con, rows: list[dict]) -> int:
    if not rows:
        return 0
    df = pd.DataFrame(rows).reindex(columns=POI_COLUMNS)
    df = df.drop_duplicates("poi_uid", keep="last")
    con.register("_poi_in", df)
    cols = ", ".join(POI_COLUMNS)
    con.execute(f"INSERT OR REPLACE INTO poi ({cols}) SELECT {cols} FROM _poi_in")
    con.unregister("_poi_in")
    return len(df)
