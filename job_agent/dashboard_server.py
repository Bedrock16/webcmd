"""
dashboard_server.py - High-performance local web server for the Job Hunting AI Agent.
Exposes REST endpoints for real-time state.json monitoring, log streaming,
and triggering autonomous job search and auto-apply runs.
"""

import http.server
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "dashboard"
STATE_FILE = BASE_DIR / "state.json"
CONFIG_FILE = BASE_DIR / "config.py"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DashboardServer")

# Global state for active background agent runs
RUN_STATUS = {
    "is_running": False,
    "last_exit_code": 0,
    "last_run_time": None,
    "active_role": "Remote Junior Python Developer",
    "current_url": "https://www.linkedin.com/jobs/search?keywords=Python%20Junior&location=Remote",
    "linkedin_url": "https://www.linkedin.com/jobs",
    "naukri_url": "https://www.naukri.com/",
    "logs": []
}
LOG_LOCK = threading.Lock()


def append_log(line: str):
    with LOG_LOCK:
        stripped = line.rstrip()
        RUN_STATUS["logs"].append(stripped)
        if len(RUN_STATUS["logs"]) > 500:
            RUN_STATUS["logs"].pop(0)
        
        url_extracted = None
        if "Navigating to: " in stripped:
            parts = stripped.split("Navigating to: ")
            if len(parts) > 1:
                url_extracted = parts[1].strip()
        elif "Arrived at '" in stripped:
            parts = stripped.split("Arrived at '")
            if len(parts) > 1:
                url_extracted = parts[1].split("'")[0].strip()

        if url_extracted:
            RUN_STATUS["current_url"] = url_extracted
            if "linkedin.com" in url_extracted:
                RUN_STATUS["linkedin_url"] = url_extracted
            elif "naukri.com" in url_extracted:
                RUN_STATUS["naukri_url"] = url_extracted


def execute_agent_job(role: str, dry_run: bool = True):
    RUN_STATUS["is_running"] = True
    RUN_STATUS["active_role"] = role
    append_log(f"=== INITIATING AGENT RUN: role='{role}', dry_run={dry_run} ===")

    cmd = [sys.executable, str(BASE_DIR / "main.py")]
    if role:
        cmd.extend(["--role", role])
    if dry_run:
        cmd.append("--dry-run")
    cmd.append("--skip-doctor")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(BASE_DIR)
        )
        for line in iter(proc.stdout.readline, ""):
            append_log(line)
        proc.stdout.close()
        proc.wait()
        RUN_STATUS["last_exit_code"] = proc.returncode
        append_log(f"=== AGENT RUN FINISHED (exit code {proc.returncode}) ===")
    except Exception as exc:
        append_log(f"ERROR executing agent: {exc}")
        RUN_STATUS["last_exit_code"] = 1
    finally:
        RUN_STATUS["is_running"] = False


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self.send_json_response(self.get_state_data())
        elif parsed.path == "/api/status":
            self.send_json_response(self.get_status_data())
        elif parsed.path == "/api/logs":
            with LOG_LOCK:
                self.send_json_response({"logs": list(RUN_STATUS["logs"])})
        elif parsed.path == "/api/reset-state":
            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"applied": [], "skipped": [], "paused": []}, f, indent=2)
                append_log("[DATABASE] state.json reset to empty state by user.")
                self.send_json_response({"ok": True, "message": "Database reset cleanly."})
            except Exception as exc:
                self.send_json_response({"ok": False, "error": str(exc)}, status=500)
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            try:
                data = json.loads(body)
            except Exception:
                data = {}

            role = data.get("role", "Remote Junior Python Developer")
            dry_run = data.get("dry_run", True)

            if RUN_STATUS["is_running"]:
                self.send_json_response({"ok": False, "error": "Agent is already running a task"}, status=400)
                return

            thread = threading.Thread(target=execute_agent_job, args=(role, dry_run), daemon=True)
            thread.start()
            self.send_json_response({"ok": True, "message": f"Agent task launched for '{role}' (dry_run={dry_run})"})
        elif parsed.path == "/api/open-preview-window":
            chrome_bin = Path(r"C:\Users\athar\AppData\Local\ms-playwright\chromium-1243\chrome-win64\chrome.exe")
            target_url = "http://localhost:8080/preview.html"
            opened = False
            if chrome_bin.exists():
                try:
                    subprocess.Popen([
                        str(chrome_bin),
                        f"--app={target_url}",
                        "--window-size=1200,650",
                        "--window-position=80,60"
                    ])
                    opened = True
                except Exception as exc:
                    logger.warning("Failed launching Chromium in app mode: %s", exc)
            if not opened:
                import webbrowser
                webbrowser.open(target_url)
                opened = True
            self.send_json_response({"ok": True, "opened": opened, "url": target_url})
        elif parsed.path == "/api/reset-state":
            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"applied": [], "skipped": [], "paused": []}, f, indent=2)
                append_log("[DATABASE] state.json reset to empty state by user.")
                self.send_json_response({"ok": True, "message": "Database reset cleanly."})
            except Exception as exc:
                self.send_json_response({"ok": False, "error": str(exc)}, status=500)
        else:
            self.send_error(404, "Endpoint not found")

    def send_json_response(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def get_state_data(self) -> dict:
        if not STATE_FILE.exists():
            return {"applied": [], "skipped": [], "paused": [], "stats": {}}
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            applied = data.get("applied", [])
            skipped = data.get("skipped", [])
            paused = data.get("paused", [])
            total = len(applied) + len(skipped) + len(paused)
            stats = {
                "total_jobs": total,
                "applied_count": len(applied),
                "skipped_count": len(skipped),
                "paused_count": len(paused),
                "pass_rate": f"{(len(applied) / total * 100):.1f}%" if total > 0 else "0%"
            }
            return {"applied": applied, "skipped": skipped, "paused": paused, "stats": stats}
        except Exception as exc:
            return {"error": str(exc), "applied": [], "skipped": [], "paused": [], "stats": {}}

    def get_status_data(self) -> dict:
        return {
            "agent_running": RUN_STATUS["is_running"],
            "active_role": RUN_STATUS["active_role"],
            "current_url": RUN_STATUS.get("current_url", "https://www.linkedin.com/jobs/search?keywords=Python%20Junior&location=Remote"),
            "linkedin_url": RUN_STATUS.get("linkedin_url", "https://www.linkedin.com/jobs"),
            "naukri_url": RUN_STATUS.get("naukri_url", "https://www.naukri.com/"),
            "last_exit_code": RUN_STATUS["last_exit_code"],
            "webcmd": {
                "version": "0.8.4",
                "daemon_port": 9777,
                "browser": "Stealth Chromium 146.0",
                "status": "HEALTHY"
            }
        }


def start_server(port: int = 8080):
    server_address = ("", port)
    for p in [port, port + 1, port + 2, 3000, 5000]:
        try:
            httpd = http.server.HTTPServer(("", p), DashboardHandler)
            print(f"\n=======================================================")
            print(f"   GMI-CLOUD INSPIRED JOB AGENT DASHBOARD ONLINE")
            print(f"   URL: http://localhost:{p}")
            print(f"=======================================================\n")
            httpd.serve_forever()
            break
        except OSError:
            continue


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    start_server(port)
