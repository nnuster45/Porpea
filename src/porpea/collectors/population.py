"""Load gridded population into population_hex.

Supported inputs:
  * Kontur Population GeoPackage (H3 res 8, from HDX "Kontur Population: Thailand").
    A .gpkg is SQLite, so we read the h3/population columns without GDAL.
  * CSV with columns h3,population (any H3 resolution).
Only cells whose centre falls inside the configured bbox are kept.
"""
from __future__ import annotations

import gzip
import shutil
import sqlite3
import tempfile
from pathlib import Path

import h3
import pandas as pd


def _read_gpkg(path: Path) -> pd.DataFrame:
    if path.suffix == ".gz":
        tmp = Path(tempfile.mkdtemp()) / path.stem
        with gzip.open(path, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        path = tmp
    con = sqlite3.connect(path)
    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type = 'features'")]
    for table in tables:
        cols = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        if {"h3", "population"} <= cols:
            return pd.read_sql(f'SELECT h3, population FROM "{table}"', con)
    raise ValueError(f"no table with h3/population columns in {path}")


def load(con, cfg: dict, path: str, source: str = "kontur") -> int:
    p = Path(path)
    df = pd.read_csv(p) if p.suffix == ".csv" else _read_gpkg(p)
    south, west, north, east = cfg["area"]["bbox"]
    centers = df["h3"].map(h3.cell_to_latlng)
    inside = centers.map(lambda c: south <= c[0] <= north and west <= c[1] <= east)
    df = df[inside].copy()
    df["res"] = df["h3"].map(h3.get_resolution)
    df["source"] = source
    df = df[["h3", "res", "population", "source"]]
    con.execute("DELETE FROM population_hex WHERE source = ?", [source])
    con.register("_pop_in", df)
    con.execute("INSERT INTO population_hex SELECT * FROM _pop_in")
    con.unregister("_pop_in")
    print(f"[population] {len(df)} cells, total {df['population'].sum():,.0f} people")
    return len(df)
