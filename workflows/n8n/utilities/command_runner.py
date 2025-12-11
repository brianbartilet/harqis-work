import os
from flask import Flask, request
import subprocess

app = Flask(__name__)

@app.route("/run", methods=["POST"])
def run_cmd():
    # Identify which instance served the request
    print(f"[PID {os.getpid()}] Received request", flush=True)

    data = request.get_json(silent=True) or {}
    cmd = data.get("cmd")

    if not cmd:
        return {"status": "error", "message": "Missing 'cmd' field"}, 400

    try:
        subprocess.Popen(cmd, shell=True)
        print(f"[PID {os.getpid()}] Executed: {cmd}", flush=True)
        return {"status": "ok", "ran": cmd}
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


def start_server():
    print(f"Starting Flask server on PID {os.getpid()}", flush=True)
    # IMPORTANT: debug=False prevents Flask from spawning multiple worker processes
    app.run(host="0.0.0.0", port=5252, debug=False)


if __name__ == "__main__":
    # Only run the server if this file is executed directly
    start_server()
