from flask import Flask, request
import subprocess

app = Flask(__name__)

@app.route("/run", methods=["POST"])
def run_cmd():
    cmd = request.json["cmd"]

    try:
        subprocess.Popen(cmd, shell=True)
        return {"status": "ok", "ran": cmd}
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

app.run(host="0.0.0.0", port=5151)
