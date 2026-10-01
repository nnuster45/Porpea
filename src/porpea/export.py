"""Export the latest score run as CSV (importable to Google My Maps), GeoJSON and a Leaflet map."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

MAP_TEMPLATE = """<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Porpea candidates</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{height:100%;margin:0}</style>
</head><body><div id="map"></div><script>
const data = __DATA__;
const map = L.map('map');
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
const color = s => s >= 75 ? '#1a9850' : s >= 60 ? '#91cf60' : s >= 45 ? '#fee08b' : '#d73027';
const layer = L.geoJSON(data, {
  pointToLayer: (f, ll) => L.circleMarker(ll, {radius: 7, color: '#333', weight: 1,
    fillColor: color(f.properties.score), fillOpacity: 0.9}),
  onEachFeature: (f, l) => {
    const p = f.properties;
    const rows = Object.entries(p.features).map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
    l.bindPopup(`<b>#${p.rank} ${p.name || ''}</b><br>score ${p.score} · ${p.anchor_category}
      ${p.flags ? '<br>⚠ ' + p.flags : ''}<br><a href="${p.gmaps}" target="_blank">Google Maps</a>
      <table>${rows}</table>`);
  }
}).addTo(map);
map.fitBounds(layer.getBounds(), {padding: [20, 20]});
</script></body></html>
"""


def export(con, cfg: dict, run_id: str | None = None, top_n: int | None = None) -> Path:
    run_id = run_id or con.execute(
        "SELECT run_id FROM score_run ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    top_n = top_n or cfg["export"]["top_n"]
    df = con.execute("""
        SELECT s.rank, s.score, s.flags, c.*
        FROM candidate_score s JOIN candidate c USING (candidate_id)
        WHERE s.run_id = ? ORDER BY s.rank LIMIT ?
    """, [run_id, top_n]).df()
    feats = con.execute("SELECT * FROM candidate_feature").df()
    wide = feats.pivot(index="candidate_id", columns="feature", values="value").round(1)
    df = df.join(wide, on="candidate_id")
    df["gmaps"] = [f"https://www.google.com/maps/search/?api=1&query={a},{b}"
                   for a, b in zip(df.lat, df.lon)]

    out_dir = Path(cfg["out_dir"]) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "top_candidates.csv", index=False, encoding="utf-8-sig")

    feature_cols = list(wide.columns)
    geo = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
        "properties": {
            "rank": int(r.rank), "score": float(r.score), "name": r.name,
            "anchor_category": r.anchor_category, "flags": r.flags, "gmaps": r.gmaps,
            "features": {k: (None if pd.isna(getattr(r, k)) else float(getattr(r, k)))
                         for k in feature_cols},
        },
    } for r in df.itertuples()]}
    (out_dir / "top_candidates.geojson").write_text(
        json.dumps(geo, ensure_ascii=False), encoding="utf-8")
    (out_dir / "map.html").write_text(
        MAP_TEMPLATE.replace("__DATA__", json.dumps(geo, ensure_ascii=False)), encoding="utf-8")
    print(f"[export] {len(df)} rows -> {out_dir}")
    return out_dir
