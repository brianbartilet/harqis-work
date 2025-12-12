import os
from pathlib import Path
from flask import Flask, request
import subprocess
import shlex

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

    if not cmd:
        return {"status": "error", "message": "Missing 'cmd' field"}, 400

    # Log exactly what came in
    log(f"[PID {os.getpid()}] Received cmd: {repr(cmd)}")

    try:
        # capture stdout+stderr to the same log file
        with LOG_FILE.open("a", encoding="utf-8") as logfh:
            subprocess.Popen(
                cmd,
                shell=True,                      # keep since you're passing a single string
                stdout=logfh,
                stderr=subprocess.STDOUT,
            )

        log(f"[PID {os.getpid()}] Spawned command.")
        return {"status": "ok", "ran": cmd}
    except Exception as e:
        log(f"[PID {os.getpid()}] ERROR starting command: {e!r}")
        return {"status": "error", "message": str(e)}, 500


def start_server():
    log(f"Starting Flask server on PID {os.getpid()}")
    app.run(host="0.0.0.0", port=5252, debug=False)


if __name__ == "__main__":
    start_server()
