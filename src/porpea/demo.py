"""Seed synthetic data around Chonburi so the pipeline can be tried without network/API keys."""
from __future__ import annotations

import random

import h3

from porpea.common import now_utc, to_h3, upsert_pois

# (lat, lon, weight): เมืองชลบุรี, ศรีราชา, พัทยา, อมตะนคร, บ้านบึง
CENTERS = [(13.361, 100.984, 1.0), (13.174, 100.931, 0.8), (12.927, 100.877, 1.0),
           (13.417, 101.032, 0.6), (13.312, 101.105, 0.4)]
COUNTS = {"convenience_711": 120, "cj_more": 50, "convenience_other": 60, "market": 80,
          "mall": 12, "office": 90, "school": 60,
          "university": 6, "hospital": 10, "bus_stop": 150, "dormitory": 80,
          "food": 300, "competitor": 15}


def _point(rng: random.Random, spread: float = 0.03):
    lat, lon, _ = rng.choices(CENTERS, weights=[c[2] for c in CENTERS])[0]
    return lat + rng.gauss(0, spread), lon + rng.gauss(0, spread)


def seed(con, cfg: dict, seed_value: int = 7) -> None:
    rng = random.Random(seed_value)
    fetched = now_utc()
    rows = []
    for category, n in COUNTS.items():
        for i in range(n):
            lat, lon = _point(rng)
            rated = category in ("convenience_711", "cj_more", "mall", "market", "food")
            rows.append({
                "poi_uid": f"demo:{category}:{i}", "source": "demo", "source_id": str(i),
                "category": category, "name": f"{category} #{i}", "brand": None,
                "lat": lat, "lon": lon, "h3_r9": to_h3(lat, lon),
                "rating": round(rng.uniform(3.5, 4.8), 1) if rated else None,
                "rating_count": int(rng.lognormvariate(5, 1.2)) if rated else None,
                "status": "OPERATIONAL", "extra": "{}", "fetched_at": fetched,
            })
    upsert_pois(con, rows)

    pop: dict[str, float] = {}
    for _ in range(20000):
        lat, lon = _point(rng, 0.05)
        cell = h3.latlng_to_cell(lat, lon, 8)
        pop[cell] = pop.get(cell, 0) + 40
    con.execute("DELETE FROM population_hex WHERE source = 'demo'")
    con.executemany("INSERT INTO population_hex VALUES (?, 8, ?, 'demo')", list(pop.items()))

    fac = []
    for i in range(80):
        lat, lon = 13.417 + rng.gauss(0, 0.02), 101.032 + rng.gauss(0, 0.02)
        fac.append((f"demo:{i}", f"factory #{i}", lat, lon, to_h3(lat, lon),
                    rng.randint(20, 2000), "demo", "demo", fetched))
    con.executemany("INSERT OR REPLACE INTO factory VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", fac)
    print(f"[demo] {len(rows)} POIs, {len(pop)} population cells, {len(fac)} factories")
