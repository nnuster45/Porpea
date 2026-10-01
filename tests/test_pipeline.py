import json


from porpea import analysis, demo, export
from porpea.collectors import osm
from porpea.common import connect, load_config, upsert_pois


def _cfg(tmp_path):
    cfg = load_config("config/settings.yaml")
    cfg["db_path"] = str(tmp_path / "t.duckdb")
    cfg["raw_dir"] = str(tmp_path / "raw")
    cfg["out_dir"] = str(tmp_path / "out")
    return cfg


def test_demo_pipeline_end_to_end(tmp_path):
    cfg = _cfg(tmp_path)
    con = connect(cfg)
    demo.seed(con, cfg)
    n = analysis.build_candidates(con, cfg)
    assert n == 80  # only markets are pins
    analysis.compute_features(con, cfg)
    run_id = analysis.score(con, cfg)
    scores = con.execute(
        "SELECT min(score), max(score), count(*) FROM candidate_score WHERE run_id = ?",
        [run_id]).fetchone()
    assert 0 <= scores[0] < scores[1] <= 100 and scores[2] == n
    n_zones = analysis.build_zones(con, cfg, run_id)
    assert 1 <= n_zones < n
    assert con.execute("SELECT count(*) FROM zone_member WHERE run_id = ?",
                       [run_id]).fetchone()[0] == n
    top = con.execute("SELECT summary FROM zone WHERE run_id = ? AND rank = 1",
                      [run_id]).fetchone()[0]
    assert {"markets", "convenience_711", "cj_more", "mall", "office"} <= set(json.loads(top))
    out = export.export(con, cfg, run_id, 10)
    geo = json.loads((out / "markets.geojson").read_text(encoding="utf-8"))
    assert len(geo["features"]) == n
    assert all(f["properties"]["zone_id"] for f in geo["features"])
    assert (out / "zones.csv").exists()
    html = (out / "map.html").read_text(encoding="utf-8")
    assert "__ENV__" not in html and '["convenience_711",' in html


def test_dedupe_prefers_google_and_excludes_anchor(tmp_path):
    cfg = _cfg(tmp_path)
    con = connect(cfg)
    base = {"category": "convenience_711", "brand": None, "rating": None, "status": None,
            "extra": "{}", "fetched_at": "2026-01-01", "h3_r9": None}
    from porpea.common import to_h3
    rows = []
    for src, sid, lat, lon, cnt in [("osm", "n1", 13.36100, 100.98400, None),
                                    ("google", "g1", 13.36110, 100.98410, 500),
                                    ("google", "g2", 13.36300, 100.98400, 50)]:
        rows.append({**base, "poi_uid": f"{src}:convenience_711:{sid}", "source": src,
                     "source_id": sid, "name": sid, "lat": lat, "lon": lon,
                     "h3_r9": to_h3(lat, lon), "rating_count": cnt})
    upsert_pois(con, rows)
    active = analysis.active_pois(con, cfg)
    assert sorted(active.source_id) == ["g1", "g2"]

    cfg["features"] = [{"name": "n_711_500", "type": "count",
                        "categories": ["convenience_711"], "radius_m": 500}]
    cfg["weights"] = {"n_711_500": 1.0}
    cfg["candidates"]["anchor_categories"] = ["convenience_711"]
    analysis.build_candidates(con, cfg)
    analysis.compute_features(con, cfg)
    vals = dict(con.execute("SELECT candidate_id, value FROM candidate_feature").fetchall())
    assert vals == {"google:convenience_711:g1": 1.0, "google:convenience_711:g2": 1.0}


def test_overpass_query_and_parse():
    q = osm.build_query(['nwr["amenity"="marketplace"]'], "TH-20", 60)
    assert 'area["ISO3166-2"="TH-20"]->.a;' in q and "(area.a);" in q
    rows = osm.parse_elements([
        {"type": "node", "id": 1, "lat": 13.3, "lon": 100.9, "tags": {"name": "ตลาดหนองมน"}},
        {"type": "way", "id": 2, "center": {"lat": 13.2, "lon": 100.95}, "tags": {}},
        {"type": "relation", "id": 3, "tags": {}},
    ], "market")
    assert [r["poi_uid"] for r in rows] == ["osm:market:node/1", "osm:market:way/2"]
    assert rows[0]["name"] == "ตลาดหนองมน"


def test_zones_link_chained_markets():
    import pandas as pd
    from porpea.common import to_h3
    # A-B 1.1 km, B-C 1.1 km (chain -> one zone), D far away
    pts = [(13.0000, 100.9), (13.0100, 100.9), (13.0200, 100.9), (13.2000, 100.9)]
    df = pd.DataFrame([{"lat": a, "lon": b, "h3_r9": to_h3(a, b)} for a, b in pts])
    groups = sorted(sorted(g) for g in analysis._cluster(df, 1500))
    assert groups == [[0, 1, 2], [3]]
    assert analysis._zone_score([90, 80, 70, 10], "top3_mean") == 80


def test_export_builds_zones_for_runs_scored_without_them(tmp_path):
    cfg = _cfg(tmp_path)
    con = connect(cfg)
    demo.seed(con, cfg)
    analysis.build_candidates(con, cfg)
    analysis.compute_features(con, cfg)
    run_id = analysis.score(con, cfg)  # no build_zones, like an older run
    out = export.export(con, cfg, run_id)
    assert con.execute("SELECT count(*) FROM zone WHERE run_id = ?", [run_id]).fetchone()[0] > 0
    assert (out / "zones.csv").exists()
