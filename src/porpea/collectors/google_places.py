"""Collect POIs from Google Places API (New) Text Search, tiled over the area.

Text Search returns at most 60 results (3 pages x 20) per query, so the area is
split into tiles; a tile that hits the cap is split into 4 and searched again.
"""
from __future__ import annotations

import json
import math
import os
import re
import time

import h3
import requests

from porpea.common import log_fetch, now_utc, save_raw, to_h3, upsert_pois

URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.location", "places.primaryType",
    "places.types", "places.rating", "places.userRatingCount",
    "places.businessStatus", "places.formattedAddress", "nextPageToken",
])
MAX_RESULTS = 60


def make_tiles(bbox: list[float], tile_km: float) -> list[tuple[float, float, float, float]]:
    south, west, north, east = bbox
    dlat = tile_km / 111.32
    dlon = tile_km / (111.32 * math.cos(math.radians((south + north) / 2)))
    tiles = []
    lat = south
    while lat < north:
        lon = west
        while lon < east:
            tiles.append((lat, lon, min(lat + dlat, north), min(lon + dlon, east)))
            lon += dlon
        lat += dlat
    return tiles


def split(tile):
    s, w, n, e = tile
    mlat, mlon = (s + n) / 2, (w + e) / 2
    return [(s, w, mlat, mlon), (s, mlon, mlat, e), (mlat, w, n, mlon), (mlat, mlon, n, e)]


def tile_population(pop_points: list[tuple[float, float, float]], tile) -> float:
    s, w, n, e = tile
    return sum(pop for lat, lon, pop in pop_points if s <= lat < n and w <= lon < e)


def search_tile(session: requests.Session, query: str, tile) -> list[dict]:
    s, w, n, e = tile
    body = {
        "textQuery": query,
        "pageSize": 20,
        "languageCode": "th",
        "regionCode": "TH",
        "locationRestriction": {"rectangle": {
            "low": {"latitude": s, "longitude": w},
            "high": {"latitude": n, "longitude": e},
        }},
    }
    places: list[dict] = []
    while True:
        resp = session.post(URL, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        places.extend(data.get("places", []))
        token = data.get("nextPageToken")
        if not token or len(places) >= MAX_RESULTS:
            return places
        body["pageToken"] = token
        time.sleep(1)


def crawl(session, query, tile, depth, max_depth, pause_s) -> list[dict]:
    places = search_tile(session, query, tile)
    time.sleep(pause_s)
    if len(places) >= MAX_RESULTS and depth < max_depth:
        out: list[dict] = []
        for sub in split(tile):
            out.extend(crawl(session, query, sub, depth + 1, max_depth, pause_s))
        return out
    return places


def to_rows(places: list[dict], category: str, name_regex: str | None) -> list[dict]:
    pattern = re.compile(name_regex, re.I) if name_regex else None
    fetched = now_utc()
    rows = []
    for p in places:
        name = (p.get("displayName") or {}).get("text")
        if pattern and not (name and pattern.search(name)):
            continue
        loc = p.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if lat is None or lon is None:
            continue
        rows.append({
            "poi_uid": f"google:{category}:{p['id']}",
            "source": "google",
            "source_id": p["id"],
            "category": category,
            "name": name,
            "brand": None,
            "lat": lat,
            "lon": lon,
            "h3_r9": to_h3(lat, lon),
            "rating": p.get("rating"),
            "rating_count": p.get("userRatingCount"),
            "status": p.get("businessStatus"),
            "extra": json.dumps({
                "primaryType": p.get("primaryType"),
                "types": p.get("types"),
                "address": p.get("formattedAddress"),
            }, ensure_ascii=False),
            "fetched_at": fetched,
        })
    return rows


def collect(con, cfg: dict, only: list[str] | None = None, dry_run: bool = False) -> None:
    gp = cfg["google_places"]
    tiles = make_tiles(cfg["area"]["bbox"], gp["tile_km"])
    pop_points = [(*h3.cell_to_latlng(c), p)
                  for c, p in con.execute("SELECT h3, population FROM population_hex").fetchall()]
    if pop_points:
        tiles = [t for t in tiles if tile_population(pop_points, t) >= gp["min_tile_population"]]
    else:
        print("[google] no population data loaded; searching every tile (costly)")
    queries = {k: v for k, v in gp["queries"].items() if not only or k in only}
    print(f"[google] {len(tiles)} tiles x {len(queries)} queries "
          f"= >= {len(tiles) * len(queries)} requests (before paging/splitting)")
    if dry_run:
        return

    key = os.environ.get(gp["api_key_env"])
    if not key:
        raise SystemExit(f"set {gp['api_key_env']} to call Google Places")
    session = requests.Session()
    session.headers.update({"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK})

    for category, q in queries.items():
        places: list[dict] = []
        for tile in tiles:
            places.extend(crawl(session, q["text"], tile, 0, gp["max_depth"], gp["pause_s"]))
        raw_path = save_raw(cfg, "google", category, places)
        n = upsert_pois(con, to_rows(places, category, q.get("name_regex")))
        log_fetch(con, "google", q["text"], n, raw_path)
        print(f"[google] {category}: {n} POIs ({len(places)} raw results)")
