import os
from pathlib import Path
from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

LOG_FILE = Path(__file__).parent / "command_runner.log"

def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg, flush=True)

@app.route("/run", methods=["POST"])
def run_cmd():
    data = request.get_json(silent=True) or {}
    cmd = data.get("cmd")

    if not cmd or not isinstance(cmd, str):
        return jsonify({"status": "error", "message": "Missing 'cmd' field (string)"}), 400

    pid = os.getpid()
    log(f"[PID {pid}] Received cmd: {repr(cmd)}")

    try:
        # Run and CAPTURE output so n8n can see what happened (including Flower response)
        completed = subprocess.run(
            cmd,
            shell=True,              # keep, since cmd is a single string
            capture_output=True,
            text=True,
        )

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code = completed.returncode

        # Also write the output into the shared log file (so you keep your existing logging)
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

        # If command failed, make the HTTP request fail so n8n shows it clearly
        return jsonify(resp), (200 if ok else 500)

    except Exception as e:
        log(f"[PID {pid}] ERROR running command: {e!r}")
        return jsonify({"status": "error", "message": str(e), "ran": cmd}), 500

def start_server():
    log(f"Starting Flask server on PID {os.getpid()}")
    app.run(host="0.0.0.0", port=5252, debug=False)

if __name__ == "__main__":
    start_server()
