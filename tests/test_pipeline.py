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
    assert n == 160  # 120 x 7-11 + 40 markets
    analysis.compute_features(con, cfg)
    run_id = analysis.score(con, cfg)
    scores = con.execute(
        "SELECT min(score), max(score), count(*) FROM candidate_score WHERE run_id = ?",
        [run_id]).fetchone()
    assert 0 <= scores[0] < scores[1] <= 100 and scores[2] == n
    out = export.export(con, cfg, run_id, 10)
    geo = json.loads((out / "top_candidates.geojson").read_text(encoding="utf-8"))
    assert len(geo["features"]) == 10
    assert geo["features"][0]["properties"]["rank"] == 1


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
