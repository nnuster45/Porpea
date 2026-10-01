"""Export the latest score run: zones.csv, top_markets.csv (Google My Maps), GeoJSON and a Leaflet map."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

MAP_TEMPLATE = """<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Porpea zones</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body{height:100%;margin:0;font:14px/1.4 -apple-system,"Segoe UI",sans-serif}
  #wrap{display:flex;height:100%}
  #side{width:300px;overflow:auto;border-right:1px solid #ddd;background:#fafafa}
  #side h2{font-size:15px;margin:10px 12px}
  .z{padding:8px 12px;border-top:1px solid #eee;cursor:pointer}
  .z:hover{background:#eef4ff}
  .z b{display:inline-block;min-width:44px}
  .chip{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}
  .small{color:#555;font-size:12px}
  #map{flex:1}
  table{border-collapse:collapse;font-size:12px}td{padding:0 6px 0 0}
  @media (max-width:700px){#wrap{flex-direction:column}#side{width:auto;height:35%}}
</style>
</head><body><div id="wrap"><div id="side"><h2>โซนเรียงตามคะแนน</h2><div id="list"></div></div>
<div id="map"></div></div><script>
const zones = __ZONES__, markets = __MARKETS__, ENV_R = __ENV_R__;
const map = L.map('map');
// Tile servers reject pages opened as file:// (no Referer) -- open via `porpea serve`.
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
if (location.protocol === 'file:') {
  const note = L.control({position: 'topright'});
  note.onAdd = () => Object.assign(document.createElement('div'), {
    style: 'background:#fff3cd;padding:6px 10px;border:1px solid #c9a227',
    textContent: 'แผนที่พื้นหลังไม่ขึ้นเมื่อเปิดไฟล์ตรง ให้รัน: porpea serve'});
  note.addTo(map);
}
const color = s => s >= 70 ? '#1a9850' : s >= 55 ? '#91cf60' : s >= 40 ? '#fee08b' : '#d73027';
const LABELS = {markets:'ตลาด', convenience_711:'7-11', cj_more:'CJ', convenience_other:'สะดวกซื้ออื่น',
  mall:'ห้าง', office:'ที่ทำงาน', school:'โรงเรียน', university:'มหาลัย', hospital:'รพ.',
  dormitory:'หอพัก', food:'ร้านอาหาร', competitor:'คู่แข่ง', population:'ประชากร',
  factory_workers:'คนงานโรงงาน'};
const fmt = v => typeof v === 'number' ? v.toLocaleString() : v;
const summaryTable = s => '<table>' + Object.entries(s).map(([k, v]) =>
  `<tr><td>${LABELS[k] || k}</td><td>${fmt(v)}</td></tr>`).join('') + '</table>';

const byZone = {};
markets.forEach(m => (byZone[m.zone_id] ||= []).push(m));
const zoneLayer = L.layerGroup().addTo(map), marketLayer = L.layerGroup().addTo(map);
const zoneBounds = {};
zones.slice().reverse().forEach(z => {
  const ms = byZone[z.zone_id] || [];
  const popup = `<b>${z.zone_id} · อันดับ ${z.rank}</b><br>คะแนนโซน ${z.score}
    (ตลาดดีสุด ${z.best_name || ''} ${z.best_score})<br><span class="small">ในรัศมี ${ENV_R} ม. ของตลาดในโซน</span>
    ${summaryTable(z.summary)}`;
  const circles = ms.map(m => L.circle([m.lat, m.lon], {radius: ENV_R, stroke: false,
    fillColor: color(z.score), fillOpacity: 0.18}).bindPopup(popup));
  circles.forEach(c => c.addTo(zoneLayer));
  const b = L.latLngBounds([]);
  ms.forEach(m => b.extend(L.latLng(m.lat, m.lon).toBounds(ENV_R * 2)));
  zoneBounds[z.zone_id] = b;
});
markets.forEach(m => {
  const rows = Object.entries(m.features).map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
  L.circleMarker([m.lat, m.lon], {radius: 6, color: '#222', weight: 1,
    fillColor: color(m.score), fillOpacity: 1}).addTo(marketLayer)
    .bindPopup(`<b>${m.name || 'ตลาด'}</b><br>คะแนนตลาด ${m.score} (อันดับ ${m.rank}) · โซน ${m.zone_id}
      ${m.flags ? '<br>⚠ ' + m.flags : ''}<br><a href="${m.gmaps}" target="_blank">เปิด Google Maps</a>
      <table>${rows}</table>`);
});
L.control.layers(null, {'โซน': zoneLayer, 'ตลาด': marketLayer}).addTo(map);
document.getElementById('list').innerHTML = zones.map(z => {
  const s = z.summary;
  return `<div class="z" data-z="${z.zone_id}"><span class="chip" style="background:${color(z.score)}"></span>
    <b>${z.zone_id}</b> คะแนน ${z.score}<div class="small">${s.markets} ตลาด · 7-11 ${s.convenience_711 ?? '-'}
    · CJ ${s.cj_more ?? '-'} · ห้าง ${s.mall ?? '-'} · ที่ทำงาน ${s.office ?? '-'}<br>ดีสุด: ${z.best_name || '-'}</div></div>`;
}).join('');
document.querySelectorAll('.z').forEach(el => el.onclick = () =>
  map.fitBounds(zoneBounds[el.dataset.z], {maxZoom: 15}));
const all = L.latLngBounds([]);
Object.values(zoneBounds).forEach(b => all.extend(b));
map.fitBounds(all);
</script></body></html>
"""


def latest_run_dir(con, cfg: dict) -> Path:
    run_id = con.execute(
        "SELECT run_id FROM score_run ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    return Path(cfg["out_dir"]) / run_id


def serve(directory: Path, port: int = 8765) -> None:
    """Serve map.html over http://127.0.0.1 so tile servers receive a Referer.

    Uses 127.0.0.1 rather than "localhost": on macOS localhost may resolve to ::1,
    where another local app could be listening on the same port.
    """
    import functools
    import webbrowser
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    if not (directory / "map.html").exists():
        raise SystemExit(f"{directory / 'map.html'} not found; run `porpea export` first")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(directory))
    for candidate in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", candidate), handler)
            break
        except OSError:
            continue
    else:
        raise SystemExit(f"no free port in {port}-{port + 19}; try --port")
    with httpd:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/map.html"
        print(f"[serve] {directory}")
        print(f"[serve] {url}  (Ctrl+C to stop)")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def export(con, cfg: dict, run_id: str | None = None, top_n: int | None = None) -> Path:
    run_id = run_id or con.execute(
        "SELECT run_id FROM score_run ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    top_n = top_n or cfg["export"]["top_n"]
    markets = con.execute("""
        SELECT s.rank, s.score, s.flags, zm.zone_id, z.rank AS zone_rank, z.score AS zone_score, c.*
        FROM candidate_score s
        JOIN candidate c USING (candidate_id)
        LEFT JOIN zone_member zm ON zm.run_id = s.run_id AND zm.candidate_id = s.candidate_id
        LEFT JOIN zone z ON z.run_id = s.run_id AND z.zone_id = zm.zone_id
        WHERE s.run_id = ? ORDER BY s.rank
    """, [run_id]).df()
    feats = con.execute("SELECT * FROM candidate_feature").df()
    wide = feats.pivot(index="candidate_id", columns="feature", values="value").round(1)
    markets = markets.join(wide, on="candidate_id")
    markets["gmaps"] = [f"https://www.google.com/maps/search/?api=1&query={a},{b}"
                        for a, b in zip(markets.lat, markets.lon)]
    zones = con.execute("""
        SELECT z.*, c.name AS best_name FROM zone z
        LEFT JOIN candidate c ON c.candidate_id = z.best_candidate_id
        WHERE z.run_id = ? ORDER BY z.rank
    """, [run_id]).df()

    out_dir = Path(cfg["out_dir"]) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    markets.head(top_n).to_csv(out_dir / "top_markets.csv", index=False, encoding="utf-8-sig")
    zone_csv = zones.drop(columns="summary").join(
        pd.DataFrame([json.loads(s) for s in zones.summary]).drop(columns="markets").add_prefix("env_"))
    zone_csv.to_csv(out_dir / "zones.csv", index=False, encoding="utf-8-sig")

    feature_cols = list(wide.columns)

    def clean(v):
        return None if pd.isna(v) else v

    market_js = [{
        "candidate_id": r.candidate_id, "name": clean(r.name), "lat": r.lat, "lon": r.lon,
        "rank": int(r.rank), "score": float(r.score), "flags": r.flags, "gmaps": r.gmaps,
        "zone_id": clean(r.zone_id),
        "features": {k: clean(getattr(r, k)) for k in feature_cols},
    } for r in markets.itertuples()]
    zone_js = [{
        "zone_id": z.zone_id, "rank": int(z.rank), "score": float(z.score),
        "best_name": clean(z.best_name), "best_score": float(z.best_score),
        "summary": json.loads(z.summary),
    } for z in zones.itertuples()]

    geo = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [m["lon"], m["lat"]]},
        "properties": {k: v for k, v in m.items() if k not in ("lat", "lon")},
    } for m in market_js]}
    (out_dir / "markets.geojson").write_text(json.dumps(geo, ensure_ascii=False), encoding="utf-8")
    html = (MAP_TEMPLATE
            .replace("__ZONES__", json.dumps(zone_js, ensure_ascii=False))
            .replace("__MARKETS__", json.dumps(market_js, ensure_ascii=False))
            .replace("__ENV_R__", str(cfg["zones"]["env_radius_m"])))
    (out_dir / "map.html").write_text(html, encoding="utf-8")
    print(f"[export] {len(zones)} zones, {len(markets)} markets -> {out_dir}")
    return out_dir
