import subprocess
import requests
import time
import sys
import threading

DEFAULT_PORT = 5678
DEFAULT_API_URL = "http://127.0.0.1:4040/api/tunnels"


def stream_logs(process):
    """
    Continuously stream ngrok logs from stdout in real-time.
    """
    print("\n===== NGROK LOGS (Live) =====\n")

    # Because we used text=True, stdout yields decoded strings
    for line in process.stdout:
        line = line.rstrip()
        if line:
            print(line)


def start_ngrok(port=DEFAULT_PORT, ngrok_path="ngrok", api_url=DEFAULT_API_URL):
    """
    Starts ngrok on the given port and returns (public_url, process).
    Requires ngrok to be installed and authed.
    """

    # Explicitly ask ngrok to send logs to stdout
    ngrok_cmd = [
        ngrok_path,
        "http",
        str(port),
        "--log=stdout",
        "--log-level=info",
    ]

    # text=True gives us str lines instead of bytes
    ngrok_process = subprocess.Popen(
        ngrok_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Allow ngrok API time to start
    time.sleep(2)

    # Query for tunnel URL from local ngrok API
    for _ in range(20):
        try:
            resp = requests.get(api_url).json()
            tunnels = resp.get("tunnels", [])
            if tunnels:
                public_url = tunnels[0]["public_url"]
                return public_url, ngrok_process
        except Exception:
            pass
        time.sleep(0.5)

    raise RuntimeError("Ngrok failed to start or expose tunnels.")


if __name__ == "__main__":
    # ---------------------------------
    # Parse CLI args: {PORT} {API_URL}
    # ---------------------------------
    port = DEFAULT_PORT
    api_url = DEFAULT_API_URL

    if len(sys.argv) >= 2:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print("❌ Invalid port.")
            print("Usage: python ngrok.py {PORT} {API_URL}")
            sys.exit(1)

    if len(sys.argv) >= 3:
        api_url = sys.argv[2]

    print(f"➡ Using port: {port}")
    print(f"➡ Using API URL: {api_url}")

    public_url, process = (None, None)
    try:
        public_url, process = start_ngrok(port, api_url=api_url)

        print("\n🔥 NGROK TUNNEL ACTIVE!")
        print(f"🌍 Public URL: {public_url}")
        print(f"🔌 Forwarding → http://localhost:{port}")
        print("📡 Logs are streaming below (Ctrl+C to stop):\n")

        # Start log streaming on a background thread
        log_thread = threading.Thread(target=stream_logs, args=(process,), daemon=True)
        log_thread.start()

        # Keep main thread alive while ngrok runs
        process.wait()

    except KeyboardInterrupt:
        print("\n🛑 Stopping ngrok...")
        try:
            process.terminate()
        except Exception:
            pass

    except Exception as e:
        print("\n❌ ERROR:", e)
