"""Collect POIs from OpenStreetMap through the Overpass API (free, no key)."""
from __future__ import annotations

import json
import time

import requests

from porpea.common import log_fetch, now_utc, save_raw, to_h3, upsert_pois


def build_query(selectors: list[str], iso: str, timeout_s: int) -> str:
    body = "".join(f"  {s}(area.a);\n" for s in selectors)
    return (
        f"[out:json][timeout:{timeout_s}];\n"
        f'area["ISO3166-2"="{iso}"]->.a;\n'
        f"(\n{body});\n"
        "out center tags;"
    )


def parse_elements(elements: list[dict], category: str) -> list[dict]:
    fetched = now_utc()
    rows = []
    for el in elements:
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        source_id = f"{el['type']}/{el['id']}"
        rows.append({
            "poi_uid": f"osm:{category}:{source_id}",
            "source": "osm",
            "source_id": source_id,
            "category": category,
            "name": tags.get("name:th") or tags.get("name") or tags.get("name:en"),
            "brand": tags.get("brand"),
            "lat": lat,
            "lon": lon,
            "h3_r9": to_h3(lat, lon),
            "rating": None,
            "rating_count": None,
            "status": None,
            "extra": json.dumps(tags, ensure_ascii=False),
            "fetched_at": fetched,
        })
    return rows


def collect(con, cfg: dict, only: list[str] | None = None) -> None:
    osm = cfg["osm"]
    iso = cfg["area"]["iso3166_2"]
    for category, selectors in osm["categories"].items():
        if only and category not in only:
            continue
        query = build_query(selectors, iso, osm["timeout_s"])
        resp = requests.post(osm["endpoint"], data={"data": query}, timeout=osm["timeout_s"] + 30)
        resp.raise_for_status()
        payload = resp.json()
        raw_path = save_raw(cfg, "osm", category, payload)
        rows = parse_elements(payload.get("elements", []), category)
        n = upsert_pois(con, rows)
        log_fetch(con, "osm", category, n, raw_path)
        print(f"[osm] {category}: {n} POIs")
        time.sleep(osm["pause_s"])
