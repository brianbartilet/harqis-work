import os
import shlex
from pathlib import Path
from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

LOG_FILE = Path(__file__).parent / "command_runner.log"

_RUNNER_TOKEN = os.environ.get("RUNNER_TOKEN", "")


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


def _check_auth() -> bool:
    if not _RUNNER_TOKEN:
        log("WARNING: RUNNER_TOKEN is not set — all requests are rejected")
        return False
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {_RUNNER_TOKEN}"


@app.route("/run", methods=["POST"])
def run_cmd():
    if not _check_auth():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    cmd = data.get("cmd")

    if not cmd or not isinstance(cmd, str):
        return jsonify({"status": "error", "message": "Missing 'cmd' field (string)"}), 400

    if len(cmd) > 4096:
        return jsonify({"status": "error", "message": "'cmd' exceeds maximum length"}), 400

    try:
        args = shlex.split(cmd, posix=False)
    except ValueError as e:
        return jsonify({"status": "error", "message": f"Invalid command syntax: {e}"}), 400

    pid = os.getpid()
    log(f"[PID {pid}] Received cmd: {repr(cmd)}")

    try:
        completed = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
        )

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code = completed.returncode

        with LOG_FILE.open("a", encoding="utf-8") as logfh:
            logfh.write(f"\n[PID {pid}] ===== COMMAND START =====\n")
            logfh.write(f"[PID {pid}] CMD: {cmd}\n")
            logfh.write(f"[PID {pid}] EXIT: {exit_code}\n")
            if stdout:
                logfh.write(f"[PID {pid}] --- STDOUT ---\n{stdout}\n")
            if stderr:
                logfh.write(f"[PID {pid}] --- STDERR ---\n{stderr}\n")
            logfh.write(f"[PID {pid}] ===== COMMAND END =====\n")

        ok = (exit_code == 0)
        resp = {
            "status": "ok" if ok else "error",
            "ran": cmd,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        }

        return jsonify(resp), (200 if ok else 500)

    except Exception as e:
        log(f"[PID {pid}] ERROR running command: {e!r}")
        return jsonify({"status": "error", "message": str(e), "ran": cmd}), 500


def start_server():
    log(f"Starting Flask server on PID {os.getpid()}")
    app.run(host="127.0.0.1", port=5252, debug=False)


if __name__ == "__main__":
    start_server()
