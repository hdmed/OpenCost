#!/usr/bin/env python3
"""Extrait l'usage des modèles AI depuis la base locale d'OpenCode.

Lecture 100%% READ-ONLY de opencode.db (SQLite, stdlib python).
Produit data/dataset.json (source du rapport visuel hors-ligne).
Coûts : par défaut la valeur calculée par OpenCode ; surchargés si le
modèle est présent dans config/pricing.json.

Usage :
  python extract.py                # extraction incrémentale (delta depuis dernier sync)
  python extract.py --full         # re-extraction complète de toutes les sessions
  python extract.py --db <chemin>  # base OpenCode personnalisée
  python extract.py --watch        # boucle : surveille opencode.db et re-extrait
  python extract.py --watch --build # et régénère aussi dist/report.html
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(os.path.expanduser("~"), ".local", "share", "opencode", "opencode.db")
DATASET_PATH = os.path.join(BASE_DIR, "data", "dataset.json")
STATE_PATH = os.path.join(BASE_DIR, "data", "sync_state.json")
PRICING_PATH = os.path.join(BASE_DIR, "config", "pricing.json")
BUDGETS_PATH = os.path.join(BASE_DIR, "config", "budgets.json")

SESSION_FIELDS = (
    "id", "project_id", "directory", "title", "agent", "model",
    "cost", "tokens_input", "tokens_output", "tokens_reasoning",
    "tokens_cache_read", "tokens_cache_write", "time_created", "time_updated",
)


def load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print("AVERTISSEMENT: {} JSON corrompu ({}), utilisation defaut".format(path, e), file=sys.stderr)
        try:
            os.replace(path, path + ".corrupt." + str(int(time.time())))
            # rotation: garder 3 derniers .corrupt
            d, b = os.path.dirname(path) or ".", os.path.basename(path)
            olds = sorted([os.path.join(d, f) for f in os.listdir(d) if f.startswith(b + ".corrupt.")])
            for old in olds[:-3]:
                try: os.remove(old)
                except OSError: pass
        except OSError:
            pass
        return default
    except OSError:
        return default


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def load_state() -> dict[str, Any]:
    return load_json(STATE_PATH, {"last_time_updated": 0})


def apply_pricing(sessions: list[dict[str, Any]], pricing: dict[str, Any] | None) -> tuple[float, list[dict[str, Any]]]:
    """Surcharge le coût des sessions quand un prix est déclaré pour le modèle.

    pricing = {"models": {"provider/model": {"input_per_1M":.., "output_per_1M":..,
              "cache_read_per_1M":.., "cache_write_per_1M":.., "reasoning_per_1M":..}}}
    """
    models_cfg = (pricing or {}).get("models") or {}
    # validation pricing: avertit si champ invalide
    for k, cfg in list(models_cfg.items()):
        if not isinstance(cfg, dict):
            print("AVERTISSEMENT: pricing '{}' ignore (pas un objet)".format(k), file=sys.stderr)
            models_cfg.pop(k, None)
            continue
        for field in ("input_per_1M", "output_per_1M", "cache_read_per_1M", "cache_write_per_1M", "reasoning_per_1M"):
            if field in cfg:
                try:
                    v = float(cfg[field])
                    if v < 0:
                        print("AVERTISSEMENT: pricing '{}' {} negatif, force 0".format(k, field), file=sys.stderr)
                        cfg[field] = 0
                except (TypeError, ValueError):
                    print("AVERTISSEMENT: pricing '{}' {}='{}' invalide, ignore".format(k, field, cfg[field]), file=sys.stderr)
                    cfg.pop(field, None)

    def _parse_model(raw):
        if not raw:
            return None
        try:
            m = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(m, dict):
            return None
        return (m.get("providerID") or "?", m.get("id") or m.get("modelID") or "?")

    total_cost = 0.0
    models_seen = {}
    for s in sessions:
        mid = _parse_model(s.get("model"))
        key = "{}/{}".format(*mid) if mid else "unknown"
        provider_id, model_id = (mid if mid else ("unknown", "unknown"))
        original = float(s.get("cost") or 0.0)
        s["cost_original"] = round(original, 6)
        cfg = models_cfg.get(key)
        if cfg:
            ti = float(s.get("tokens_input") or 0)
            to = float(s.get("tokens_output") or 0)
            tcr = float(s.get("tokens_cache_read") or 0)
            tcw = float(s.get("tokens_cache_write") or 0)
            tr = float(s.get("tokens_reasoning") or 0)
            cost = (
                ti / 1e6 * float(cfg.get("input_per_1M", 0))
                + to / 1e6 * float(cfg.get("output_per_1M", 0))
                + tcr / 1e6 * float(cfg.get("cache_read_per_1M", 0))
                + tcw / 1e6 * float(cfg.get("cache_write_per_1M", 0))
                + tr / 1e6 * float(cfg.get("reasoning_per_1M", 0))
            )
            s["cost"] = round(cost, 6)
            s["cost_source"] = "pricing"
        else:
            s["cost"] = round(original, 6)
            s["cost_source"] = "opencode"
        s["model_id"] = model_id
        s["provider_id"] = provider_id
        s["model_label"] = key
        total_cost += s["cost"]
        models_seen[key] = {
            "id": key,
            "provider": provider_id,
            "model": model_id,
            "override": key in models_cfg,
        }
    return total_cost, sorted(models_seen.values(), key=lambda m: m["id"])


def fetch_sessions(db_path: str, watermark: int, full: bool) -> list[dict[str, Any]]:
    """Retourne les sessions (delta si pas full). Lecture seule."""
    uri = "file:{}?mode=ro".format(db_path.replace("\\", "/"))
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        fields = ", ".join(SESSION_FIELDS)
        if full:
            rows = conn.execute(
                "SELECT {} FROM session".format(fields)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT {} FROM session WHERE COALESCE(time_updated, time_created, 0) > ?"
                .format(fields),
                (watermark,),
            ).fetchall()
        projects = {
            r["id"]: dict(r)
            for r in conn.execute("SELECT id, name, worktree FROM project").fetchall()
        }
        sessions = []
        for r in rows:
            d = dict(r)
            proj = projects.get(d.get("project_id"))
            if proj:
                d["project_name"] = proj.get("name") or os.path.basename(proj.get("worktree") or "") or d.get("project_id")
            else:
                d["project_name"] = d.get("project_id")
            sessions.append(d)
        return sessions
    finally:
        conn.close()


def extract(args: argparse.Namespace) -> bool:
    db_path = os.path.expanduser(args.db)
    if not os.path.exists(db_path):
        print("ERREUR: base OpenCode introuvable: {}".format(db_path))
        print("Passer --db <chemin> (defaut ~/.local/share/opencode/opencode.db)")
        sys.exit(1)

    pricing = load_json(PRICING_PATH, {"models": {}})

    if args.full:
        merged = {}
        watermark = 0
    else:
        state = load_state()
        watermark = int(state.get("last_time_updated", 0))
        prev = load_json(DATASET_PATH, {"sessions": []})
        merged = {s["id"]: s for s in prev.get("sessions", [])}

    print("[extract] source: {}".format(db_path))
    started = time.time()
    new_rows = fetch_sessions(db_path, watermark, args.full)
    if not args.full:
        # nettoyage : on retire les sessions supprimées/archivées (SELECT id seul, léger)
        uri = "file:{}?mode=ro".format(db_path.replace("\\", "/"))
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            alive = {r[0] for r in conn.execute("SELECT id FROM session").fetchall()}
        finally:
            conn.close()
        merged = {k: v for k, v in merged.items() if k in alive}

    for r in new_rows:
        merged[r["id"]] = r

    sessions = list(merged.values())
    print("[extract] {} session(s) nouvelle(s)/mise(s) a jour ({} au total)".format(
        len(new_rows), len(sessions)))

    total_cost, models = apply_pricing(sessions, pricing)

    # prochain watermark = max COALESCE(time_updated, time_created) des lignes lues
    next_wm = watermark
    for r in new_rows:
        ts = r.get("time_updated") or r.get("time_created")
        if ts:
            next_wm = max(next_wm, int(ts))
    if args.full:
        next_wm = max((int(r.get("time_updated") or r.get("time_created") or 0) for r in sessions), default=0)

    sessions.sort(key=lambda s: int(s.get("time_created") or 0))
    budgets = load_json(BUDGETS_PATH, {})
    dataset = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db_path": db_path,
        "pricing_config": pricing,
        "budgets": budgets,
        "models": models,
        "totals": {
            "cost": round(total_cost, 6),
            "sessions": len(sessions),
            "tokens_input": sum(int(s.get("tokens_input") or 0) for s in sessions),
            "tokens_output": sum(int(s.get("tokens_output") or 0) for s in sessions),
            "tokens_reasoning": sum(int(s.get("tokens_reasoning") or 0) for s in sessions),
            "tokens_cache_read": sum(int(s.get("tokens_cache_read") or 0) for s in sessions),
            "tokens_cache_write": sum(int(s.get("tokens_cache_write") or 0) for s in sessions),
        },
        "sessions": sessions,
    }
    save_json(DATASET_PATH, dataset)
    save_json(STATE_PATH, {"last_time_updated": next_wm})
    print("[extract] OK -> {}".format(DATASET_PATH))
    print("[extract] {} sessions, cout total {:.4f}, {}s".format(
        len(sessions), total_cost, round(time.time() - started, 2)))
    return True


def build_report() -> int:
    import subprocess
    return subprocess.call([sys.executable, os.path.join(BASE_DIR, "build_report.py")])


def _db_max_time(db_path: str) -> int:
    try:
        uri = "file:{}?mode=ro".format(db_path.replace("\\", "/"))
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            row = conn.execute("SELECT MAX(COALESCE(time_updated, time_created, 0)) FROM session").fetchone()
            return int(row[0] or 0) if row and row[0] is not None else 0
        finally:
            conn.close()
    except Exception:
        try:
            return int(os.path.getmtime(db_path))
        except OSError:
            return 0

def watch(args: argparse.Namespace) -> None:
    db_path = os.path.expanduser(args.db)
    # essai watchdog (optionnel, sinon poll)
    try:
        from watchdog.observers import Observer  # type: ignore
        from watchdog.events import FileSystemEventHandler  # type: ignore
        has_watchdog = True
    except ImportError:
        has_watchdog = False
    if has_watchdog:
        print("[watch] watchdog actif sur {}".format(os.path.dirname(db_path)))
        last_max = _db_max_time(db_path)
        extract(args)
        if args.build:
            build_report()
        class H(FileSystemEventHandler):
            def on_modified(self, event):
                if os.path.abspath(event.src_path) == os.path.abspath(db_path):
                    print("[watch] changement detecte -> re-extraction")
                    extract(args)
                    if args.build:
                        build_report()
            on_created = on_modified
        obs = Observer(); obs.schedule(H(), os.path.dirname(os.path.abspath(db_path)) or ".", recursive=False); obs.start()
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            obs.stop(); obs.join(); return
    print("[watch] surveille {} toutes les 15s (Ctrl+C pour arreter)".format(db_path))
    last_max = _db_max_time(db_path)
    last_mtime = 0
    try:
        last_mtime = os.path.getmtime(db_path)
    except OSError:
        pass
    extract(args)
    if args.build:
        build_report()
    while True:
        time.sleep(15)
        cur_max = _db_max_time(db_path)
        try:
            mtime = os.path.getmtime(db_path)
        except OSError:
            mtime = last_mtime
        if cur_max != last_max or mtime != last_mtime:
            print("[watch] changement detecte -> re-extraction")
            last_max, last_mtime = cur_max, mtime
            extract(args)
            if args.build:
                build_report()


def main():
    ap = argparse.ArgumentParser(description="Extraction usage AI depuis opencode.db")
    ap.add_argument("--db", default=os.environ.get("OPENCODE_DB") or DEFAULT_DB,
                    help="chemin vers opencode.db")
    ap.add_argument("--full", action="store_true",
                    help="re-extraction complete (ignore le cache incremental)")
    ap.add_argument("--watch", action="store_true",
                    help="surveille la base et re-extrait au changement")
    ap.add_argument("--build", action="store_true",
                    help="avec --watch : regenere aussi dist/report.html")
    args = ap.parse_args()

    if args.watch:
        watch(args)
    else:
        extract(args)
        if args.build:
            build_report()


if __name__ == "__main__":
    main()