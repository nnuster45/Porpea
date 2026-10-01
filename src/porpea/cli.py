"""Command line entry point: `python -m porpea <command>`."""
from __future__ import annotations

import argparse
from pathlib import Path

from porpea import analysis, demo, export
from porpea.collectors import factories, google_places, osm, population
from porpea.common import connect, load_config


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="porpea")
    ap.add_argument("--config", default="config/settings.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="create tables")
    p = sub.add_parser("collect-osm", help="POIs from OpenStreetMap (Overpass)")
    p.add_argument("--only", nargs="*")
    p = sub.add_parser("collect-google", help="POIs from Google Places API (New)")
    p.add_argument("--only", nargs="*")
    p.add_argument("--dry-run", action="store_true", help="only print request estimate")
    p = sub.add_parser("load-population", help="Kontur .gpkg(.gz) or h3,population CSV")
    p.add_argument("path")
    p.add_argument("--source", default="kontur")
    p = sub.add_parser("load-factories", help="factory CSV with column mapping")
    p.add_argument("path")
    p.add_argument("--map", nargs="+", required=True, metavar="FIELD=COLUMN")
    sub.add_parser("candidates", help="build candidate list from anchor POIs")
    sub.add_parser("features", help="compute features around candidates")
    sub.add_parser("score", help="score markets and group them into zones")
    p = sub.add_parser("export", help="CSV/GeoJSON/map of top candidates")
    p.add_argument("--run-id")
    p.add_argument("--top", type=int)
    p = sub.add_parser("serve", help="open the latest map.html via http://localhost")
    p.add_argument("--run-id")
    p.add_argument("--port", type=int, default=8765)
    sub.add_parser("analyze", help="candidates + features + score + zones + export")
    sub.add_parser("demo-seed", help="insert synthetic Chonburi data for a dry run")

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    con = connect(cfg)

    if args.cmd == "collect-osm":
        osm.collect(con, cfg, args.only)
    elif args.cmd == "collect-google":
        google_places.collect(con, cfg, args.only, args.dry_run)
    elif args.cmd == "load-population":
        population.load(con, cfg, args.path, args.source)
    elif args.cmd == "load-factories":
        mapping = dict(m.split("=", 1) for m in args.map)
        factories.load(con, cfg, args.path, mapping)
    elif args.cmd == "candidates":
        analysis.build_candidates(con, cfg)
    elif args.cmd == "features":
        analysis.compute_features(con, cfg)
    elif args.cmd == "score":
        run_id = analysis.score(con, cfg)
        analysis.build_zones(con, cfg, run_id)
    elif args.cmd == "export":
        export.export(con, cfg, args.run_id, args.top)
    elif args.cmd == "serve":
        out = Path(cfg["out_dir"]) / args.run_id if args.run_id else export.latest_run_dir(con, cfg)
        con.close()
        export.serve(out, args.port)
        return
    elif args.cmd == "analyze":
        analysis.build_candidates(con, cfg)
        analysis.compute_features(con, cfg)
        run_id = analysis.score(con, cfg)
        analysis.build_zones(con, cfg, run_id)
        export.export(con, cfg, run_id)
    elif args.cmd == "demo-seed":
        demo.seed(con, cfg)
    con.close()


if __name__ == "__main__":
    main()
