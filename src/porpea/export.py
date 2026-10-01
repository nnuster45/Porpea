"""Export the latest score run: zones.csv, top_markets.csv (Google My Maps), GeoJSON and a Leaflet map."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from porpea.analysis import PointIndex, active_pois, build_zones

MAP_TEMPLATE = """<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Porpea zones</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html,body{height:100%;margin:0;font:14px/1.4 -apple-system,"Segoe UI",sans-serif}
  #wrap{display:flex;height:100%}
  #side{width:340px;overflow:auto;border-right:1px solid #ddd;background:#fafafa}
  #side h2{font-size:15px;margin:10px 12px}
  .z{padding:8px 12px;border-top:1px solid #eee;cursor:pointer}
  .z:hover,.item:hover{background:#eef4ff}
  .z b{display:inline-block;min-width:44px}
  .chip{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}
  .small{color:#555;font-size:12px}
  .back{margin:10px 12px;padding:4px 10px;cursor:pointer}
  .head{padding:0 12px 8px}
  .cat{border-top:1px solid #e5e5e5}
  .cat summary{padding:6px 12px;cursor:pointer;font-weight:600;list-style:none}
  .cat summary .n{float:right;font-weight:400;color:#555}
  .cat input{margin-right:6px}
  .item{padding:3px 12px 3px 34px;cursor:pointer;font-size:13px;display:flex;justify-content:space-between;gap:8px}
  .item span:last-child{color:#666;white-space:nowrap}
  .env-icon{font-size:18px;line-height:22px;text-align:center;filter:drop-shadow(0 0 2px #fff)}
  #map{flex:1}
  table{border-collapse:collapse;font-size:12px}td{padding:0 6px 0 0}
  @media (max-width:700px){#wrap{flex-direction:column}#side{width:auto;height:40%}}
</style>
</head><body><div id="wrap"><div id="side"></div><div id="map"></div></div><script>
const zones = __ZONES__, markets = __MARKETS__, ENV = __ENV__, ENV_R = __ENV_R__;
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
// [label, icon] per environment category; order = order in the side panel
const CATS = {
  convenience_711: ['7-11', '🏪'], cj_more: ['CJ More / CJ Express', '🛍️'],
  convenience_other: ['ร้านสะดวกซื้ออื่น', '🏬'], mall: ['ห้าง / ไฮเปอร์มาร์เก็ต', '🛒'],
  office: ['สถานที่ทำงาน', '🏢'], factory: ['โรงงาน', '🏭'], industrial: ['พื้นที่อุตสาหกรรม', '🏗️'],
  school: ['โรงเรียน', '🏫'], university: ['มหาวิทยาลัย / วิทยาลัย', '🎓'], hospital: ['โรงพยาบาล', '🏥'],
  dormitory: ['หอพัก', '🏠'], bus_stop: ['ป้ายรถเมล์', '🚌'], food: ['ร้านอาหาร', '🍜'],
  competitor: ['คู่แข่ง (เปาะเปี๊ยะ)', '⚠️'],
};
const LABELS = {markets: 'ตลาด', population: 'ประชากร', factory_workers: 'คนงานโรงงาน'};
const label = k => (CATS[k] || [LABELS[k] || k])[0];
const icon = k => (CATS[k] || ['', '📍'])[1];
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const fmt = v => typeof v === 'number' ? v.toLocaleString() : v;
const summaryTable = s => '<table>' + Object.entries(s).map(([k, v]) =>
  `<tr><td>${label(k)}</td><td>${fmt(v)}</td></tr>`).join('') + '</table>';
const distM = (a, b, c, d) => {
  const r = Math.PI / 180, x = (d - b) * r * Math.cos((a + c) / 2 * r), y = (c - a) * r;
  return Math.round(Math.sqrt(x * x + y * y) * 6371000);
};

const side = document.getElementById('side');
const byZone = {};
markets.forEach(m => (byZone[m.zone_id] ||= []).push(m));
const zoneLayer = L.layerGroup().addTo(map), marketLayer = L.layerGroup().addTo(map);
const envLayer = L.layerGroup().addTo(map);
const zoneBounds = {};

zones.slice().reverse().forEach(z => {
  const ms = byZone[z.zone_id] || [];
  const popup = `<b>${z.zone_id} · อันดับ ${z.rank}</b><br>คะแนนโซน ${z.score}
    (ตลาดดีสุด ${esc(z.best_name)} ${z.best_score})<br><span class="small">ในรัศมี ${ENV_R} ม. ของตลาดในโซน</span>
    ${summaryTable(z.summary)}`;
  ms.forEach(m => L.circle([m.lat, m.lon], {radius: ENV_R, stroke: false,
    fillColor: color(z.score), fillOpacity: 0.15}).bindPopup(popup).addTo(zoneLayer));
  const b = L.latLngBounds([]);
  ms.forEach(m => b.extend(L.latLng(m.lat, m.lon).toBounds(ENV_R * 2)));
  zoneBounds[z.zone_id] = b;
});

markets.forEach(m => {
  m.marker = L.circleMarker([m.lat, m.lon], {radius: 8, color: '#222', weight: 1.5,
    fillColor: color(m.score), fillOpacity: 1}).addTo(marketLayer)
    .bindTooltip(`${esc(m.name || 'ตลาด')} · ${m.score}`)
    .on('click', () => showMarket(m));
});

function showZones() {
  envLayer.clearLayers();
  map.addLayer(zoneLayer);
  side.innerHTML = '<h2>โซนเรียงตามคะแนน</h2><div class="small" style="margin:0 12px 8px">คลิกหมุดตลาดบนแผนที่เพื่อดูสภาพแวดล้อมรอบตลาด</div>' +
    zones.map(z => {
      const s = z.summary;
      return `<div class="z" data-z="${z.zone_id}"><span class="chip" style="background:${color(z.score)}"></span>
        <b>${z.zone_id}</b> คะแนน ${z.score}<div class="small">${s.markets} ตลาด · 7-11 ${s.convenience_711 ?? '-'}
        · CJ ${s.cj_more ?? '-'} · ห้าง ${s.mall ?? '-'} · ที่ทำงาน ${s.office ?? '-'}<br>ดีสุด: ${esc(z.best_name) || '-'}</div></div>`;
    }).join('');
  side.querySelectorAll('.z').forEach(el => el.onclick = () =>
    map.fitBounds(zoneBounds[el.dataset.z], {maxZoom: 15}));
}

function showMarket(m) {
  envLayer.clearLayers();
  map.removeLayer(zoneLayer);
  [500, ENV_R].forEach((r, i) => L.circle([m.lat, m.lon], {radius: r, color: '#1f6feb', weight: 1.5,
    dashArray: i ? '6 6' : null, fill: !i, fillOpacity: 0.05, interactive: false}).addTo(envLayer));

  const near = ENV.map(([cat, name, lat, lon, info]) => ({cat, name, lat, lon, info, d: distM(m.lat, m.lon, lat, lon)}))
    .filter(p => p.d <= ENV_R).sort((a, b) => a.d - b.d);
  const groups = {};
  near.forEach(p => {
    p.marker = L.marker([p.lat, p.lon], {icon: L.divIcon({className: 'env-icon', html: icon(p.cat),
      iconSize: [22, 22]})}).bindPopup(`${icon(p.cat)} <b>${esc(p.name) || label(p.cat)}</b><br>${label(p.cat)}
      · ห่างตลาด ${p.d} ม.${p.info ? `<br>${p.cat === 'factory' ? 'คนงาน' : 'รีวิว'} ${fmt(p.info)}` : ''}`);
    (groups[p.cat] ||= []).push(p);
  });
  const cats = Object.keys(CATS).filter(c => groups[c]);
  const shown = new Set(cats.filter(c => c !== 'food' && c !== 'bus_stop' || groups[c].length <= 30));
  const draw = () => near.forEach(p => shown.has(p.cat) ? p.marker.addTo(envLayer) : envLayer.removeLayer(p.marker));
  draw();

  const feats = Object.entries(m.features).map(([k, v]) => `<tr><td>${k}</td><td>${v ?? '-'}</td></tr>`).join('');
  side.innerHTML = `<button class="back">← กลับไปดูโซน</button>
    <div class="head"><h2 style="margin:0 0 4px">${esc(m.name) || 'ตลาด'}</h2>
    <span class="chip" style="background:${color(m.score)}"></span>คะแนน <b>${m.score}</b> (อันดับ ${m.rank})
    · โซน ${m.zone_id}${m.flags ? `<br>⚠ ${esc(m.flags)}` : ''}
    <br><a href="${m.gmaps}" target="_blank">เปิดใน Google Maps</a>
    <div class="small" style="margin-top:6px">วงทึบ 500 ม. · วงประ ${ENV_R} ม. · ตัวเลขขวา = จำนวนใน 500 ม. / ใน ${ENV_R} ม. · ติ๊กเพื่อแสดง/ซ่อนหมุด</div></div>` +
    cats.map(c => {
      const g = groups[c], in500 = g.filter(p => p.d <= 500).length;
      return `<details class="cat"${c === 'competitor' || g.length <= 8 ? ' open' : ''}><summary>
        <input type="checkbox" data-c="${c}"${shown.has(c) ? ' checked' : ''}>${icon(c)} ${label(c)}
        <span class="n">${in500} / ${g.length}</span></summary>` +
        g.map((p, i) => `<div class="item" data-c="${c}" data-i="${i}"><span>${esc(p.name) || '(ไม่มีชื่อ)'}</span><span>${p.d} ม.</span></div>`).join('') +
        '</details>';
    }).join('') +
    (cats.length ? '' : '<div class="head small">ไม่พบสถานที่รอบตลาดในข้อมูล</div>') +
    `<details class="cat"><summary>คะแนนย่อย (feature)</summary><div class="head">${'<table>' + feats + '</table>'}</div></details>`;
  side.querySelector('.back').onclick = showZones;
  side.querySelectorAll('input[data-c]').forEach(cb => {
    cb.onclick = e => e.stopPropagation();
    cb.onchange = () => { cb.checked ? shown.add(cb.dataset.c) : shown.delete(cb.dataset.c); draw(); };
  });
  side.querySelectorAll('.item').forEach(el => el.onclick = () => {
    const p = groups[el.dataset.c][+el.dataset.i];
    if (!shown.has(p.cat)) { shown.add(p.cat); side.querySelector(`input[data-c="${p.cat}"]`).checked = true; draw(); }
    map.setView([p.lat, p.lon], Math.max(map.getZoom(), 17));
    p.marker.openPopup();
  });
  map.fitBounds(L.latLng(m.lat, m.lon).toBounds(ENV_R * 2.2));
}

L.control.layers(null, {'โซน': zoneLayer, 'ตลาด': marketLayer, 'รอบตลาด': envLayer}).addTo(map);
showZones();
const all = L.latLngBounds([]);
Object.values(zoneBounds).forEach(b => all.extend(b));
map.fitBounds(all);
</script></body></html>
"""


def environment_points(con, cfg: dict, markets: pd.DataFrame, radius_m: float) -> list[list]:
    """POIs and factories within radius_m of any market, as [category, name, lat, lon, info]."""
    idx = PointIndex()
    for r in markets.itertuples():
        idx.add(r.h3_r9, r.lat, r.lon, 1.0)

    def near_market(lat, lon):
        return next(idx.within(lat, lon, radius_m), None) is not None

    anchors = set(cfg["candidates"]["anchor_categories"])
    pois = active_pois(con, cfg)
    out = []
    for r in pois.itertuples():
        if r.category in anchors or not near_market(r.lat, r.lon):
            continue
        info = None if pd.isna(r.rating_count) else int(r.rating_count)
        out.append([r.category, r.name if isinstance(r.name, str) else None,
                    round(r.lat, 6), round(r.lon, 6), info])
    for name, lat, lon, workers in con.execute(
            "SELECT name, lat, lon, workers FROM factory").fetchall():
        if near_market(lat, lon):
            out.append(["factory", name, round(lat, 6), round(lon, 6), workers])
    return out


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
    # Runs scored before zones existed (or via an older version) have no zones yet.
    if not con.execute("SELECT count(*) FROM zone WHERE run_id = ?", [run_id]).fetchone()[0]:
        build_zones(con, cfg, run_id)
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
        pd.DataFrame([json.loads(s) for s in zones.summary]).drop(columns="markets", errors="ignore").add_prefix("env_"))
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
    env = environment_points(con, cfg, markets, cfg["zones"]["env_radius_m"])
    html = (MAP_TEMPLATE
            .replace("__ENV__", json.dumps(env, ensure_ascii=False))
            .replace("__ZONES__", json.dumps(zone_js, ensure_ascii=False))
            .replace("__MARKETS__", json.dumps(market_js, ensure_ascii=False))
            .replace("__ENV_R__", str(cfg["zones"]["env_radius_m"])))
    (out_dir / "map.html").write_text(html, encoding="utf-8")
    print(f"[export] {len(zones)} zones, {len(markets)} markets -> {out_dir}")
    return out_dir
