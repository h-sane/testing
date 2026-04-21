"""Lightweight local HTTP API for command ingestion and status polling."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from sara.config import LOCAL_API_HOST, LOCAL_API_PORT

logger = logging.getLogger("sara.api")


class LocalCommandApiServer:
    """Threaded local API exposing command submit and status endpoints."""

    def __init__(self, agent, host: str = LOCAL_API_HOST, port: int = LOCAL_API_PORT):
        self.agent = agent
        self.host = host
        self.port = int(port)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._httpd is not None:
            return

        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="sara-local-api")
        self._thread.start()
        logger.info("Local API listening on http://%s:%s", self.host, self.port)

    def stop(self) -> None:
        httpd = self._httpd
        thread = self._thread
        self._httpd = None
        self._thread = None

        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)

    def submit_command(self, command: str) -> Dict[str, Any]:
        text = (command or "").strip()
        if not text:
            raise ValueError("command must not be empty")

        job_id = str(uuid.uuid4())
        now = time.time()
        job = {
            "job_id": job_id,
            "command": text,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True, name=f"sara-job-{job_id[:8]}")
        thread.start()

        return {
            "job_id": job_id,
            "status": "queued",
        }

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["updated_at"] = time.time()
            command = str(job["command"])

        try:
            result = self.agent.process_command(command)
            payload = result.to_dict() if hasattr(result, "to_dict") else result
            with self._lock:
                target = self._jobs.get(job_id)
                if target:
                    target["status"] = "done"
                    target["updated_at"] = time.time()
                    target["result"] = payload
                    target["error"] = None
        except Exception as exc:
            with self._lock:
                target = self._jobs.get(job_id)
                if target:
                    target["status"] = "failed"
                    target["updated_at"] = time.time()
                    target["error"] = str(exc)

    def _make_handler(self):
        server = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args):
                logger.debug("api %s - %s", self.address_string(), format % args)

            def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> Dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"

                if path == "/health":
                    return self._send_json(
                        200,
                        {
                            "ok": True,
                            "service": "sara-local-api",
                            "host": server.host,
                            "port": server.port,
                        },
                    )

                if path == "/status":
                    return self._send_json(200, server.agent.get_system_status())

                if path == "/history":
                    return self._send_json(200, {"items": server.agent.get_history()[-20:]})

                if path.startswith("/jobs/"):
                    job_id = path.split("/jobs/", 1)[1].strip()
                    if not job_id:
                        return self._send_json(400, {"error": "job id required"})
                    job = server.get_job(job_id)
                    if not job:
                        return self._send_json(404, {"error": "job not found", "job_id": job_id})
                    return self._send_json(200, job)

                return self._send_json(404, {"error": "not found"})

            def do_POST(self):
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"

                if path != "/command":
                    return self._send_json(404, {"error": "not found"})

                try:
                    payload = self._read_json()
                except Exception as exc:
                    return self._send_json(400, {"error": f"invalid json: {exc}"})

                command = str(payload.get("command", "") or "").strip()
                if not command:
                    return self._send_json(400, {"error": "field 'command' is required"})

                try:
                    submitted = server.submit_command(command)
                except Exception as exc:
                    return self._send_json(500, {"error": str(exc)})

                return self._send_json(202, submitted)

        return _Handler
