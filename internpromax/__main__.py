"""CLI: `python -m internpromax [serve|sync|import FILE|tailor JOB_ID]`."""

from __future__ import annotations

import argparse
import json
import logging
import webbrowser

from . import config


def main() -> None:
    parser = argparse.ArgumentParser(prog="internpromax", description="Internship finder, resume tailor and application tracker")
    sub = parser.add_subparsers(dest="cmd")
    serve = sub.add_parser("serve", help="run the dashboard + API (default)")
    serve.add_argument("--port", type=int, default=config.PORT)
    serve.add_argument("--host", default=config.HOST, help="address to listen on (default 127.0.0.1; use your Tailscale IP on a server)")
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--log-file", help="write logs to this file (used when it runs in the background)")
    auto = sub.add_parser("autostart", help="start InternProMax automatically when you log in")
    auto.add_argument("--off", action="store_true", help="stop starting it automatically")
    auto.add_argument("--status", action="store_true", help="show whether it's set up and running")
    sync = sub.add_parser("sync", help="pull the latest listings now")
    sync.add_argument("--force", action="store_true", help="ignore the cached ETag")
    imp = sub.add_parser("import", help="import a listings.json file from disk")
    imp.add_argument("file")
    lp = sub.add_parser("load-profile", help="replace your profile with a JSON file (a profile or an export)")
    lp.add_argument("file")
    an = sub.add_parser("analyze", help="fetch + analyze one job posting and print the result")
    an.add_argument("job_id")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "sync":
        from . import ingest

        print(json.dumps(ingest.sync_all(force=args.force), indent=2))
    elif args.cmd == "import":
        from . import ingest

        print(json.dumps(ingest.import_file(args.file), indent=2))
    elif args.cmd == "load-profile":
        from . import db, profile

        with open(args.file, encoding="utf-8") as fh:
            data = json.load(fh)
        if "profile" in data and "personal" not in data:
            data = data["profile"]
        with db.session() as conn:
            saved = profile.save(conn, data)
            done = profile.completeness(saved)
        res = saved["resume"]
        print(f"Loaded profile for {saved['personal'].get('first_name', '')} {saved['personal'].get('last_name', '')}: "
              f"{len(res['experience'])} experiences, {len(res['projects'])} projects, {len(res['activities'])} activities, "
              f"{sum(len(g['items']) for g in res['skills'])} skills ({done['score']}% complete)")
    elif args.cmd == "autostart":
        from . import autostart

        if args.status:
            st = autostart.status()
            print(f"Starts when you log in: {'yes' if st['installed'] else 'no'}")
            print(f"Running now: {'yes, ' + st['url'] if st['running'] else 'no'}")
            for entry in st["entries"]:
                print(f"  startup entry: {entry}")
            print(f"  log file: {st['log']}")
        else:
            for line in (autostart.uninstall() if args.off else autostart.install()):
                print(line)
    elif args.cmd == "analyze":
        from . import pipeline

        print(json.dumps(pipeline.analyze_job(args.job_id, force=True), indent=2, default=str))
    else:
        import sys

        import uvicorn

        port = getattr(args, "port", config.PORT)
        host = getattr(args, "host", config.HOST)
        log_file = getattr(args, "log_file", None)
        if log_file:
            stream = open(log_file, "a", buffering=1, encoding="utf-8")
            sys.stdout = sys.stderr = stream
            logging.getLogger().handlers.clear()
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=stream)
        from . import autostart

        if autostart.running(port):
            # Already running (e.g. it started when you logged in): just open the dashboard.
            print(f"\n  InternProMax is already running: http://127.0.0.1:{port}\n")
            if not getattr(args, "no_browser", False):
                webbrowser.open(f"http://127.0.0.1:{port}")
            return
        from . import auth

        if host not in ("127.0.0.1", "localhost", "::1") and not auth.password():
            sys.exit(f"Refusing to listen on {host} without a password. Set IPM_PASSWORD or IPM_PASSWORD_FILE (see docs/DEPLOY.md).")
        url = f"http://{host if host not in ('0.0.0.0', '::') else '127.0.0.1'}:{port}"
        print(f"\n  InternProMax dashboard: {url}\n")
        if not getattr(args, "no_browser", False):
            try:
                webbrowser.open(url)
            except Exception:
                pass
        uvicorn.run("internpromax.server:app", host=host, port=port, log_level="info", proxy_headers=True)


if __name__ == "__main__":
    main()
