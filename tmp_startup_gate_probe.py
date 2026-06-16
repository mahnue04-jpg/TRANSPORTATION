import json
import socket
import subprocess
import time
from datetime import datetime, timezone
from urllib import request, error

HOST = "127.0.0.1"
PORT = 8011
DURATION_SECONDS = 300
INTERVAL_SECONDS = 5


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_port_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def http_status(url: str, timeout: float = 3.0):
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), ""
    except error.HTTPError as exc:
        return exc.code, str(exc)
    except Exception as exc:
        return None, str(exc)


def pids_on_port(port: int) -> list[int]:
    cmd = [
        "netstat",
        "-ano",
        "-p",
        "TCP",
    ]
    output = subprocess.check_output(cmd, text=True, errors="ignore")
    pids = set()
    needle = f":{port}"
    for line in output.splitlines():
        if "LISTENING" not in line:
            continue
        if needle not in line:
            continue
        parts = line.split()
        if parts:
            try:
                pids.add(int(parts[-1]))
            except Exception:
                pass
    return sorted(pids)


def pid_exists_windows(pid: int) -> bool:
    cmd = ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]
    output = subprocess.check_output(cmd, text=True, errors="ignore")
    lower = output.lower()
    return "no tasks are running" not in lower and "," in output


def main():
    start = time.time()
    end = start + DURATION_SECONDS

    samples = []
    failures = []
    pid_changes = []
    last_pids = None

    while time.time() < end:
        ts = now_iso()

        port_ok = is_port_listening(HOST, PORT)
        health_code, health_err = http_status(f"http://{HOST}:{PORT}/api/health")
        app_code, app_err = http_status(f"http://{HOST}:{PORT}/app")
        pids = pids_on_port(PORT)

        sample = {
            "ts": ts,
            "port_listening": port_ok,
            "health_status": health_code,
            "app_status": app_code,
            "listener_pids": pids,
        }
        samples.append(sample)
        print(
            json.dumps(
                {
                    "ts": ts,
                    "port": port_ok,
                    "health": health_code,
                    "app": app_code,
                    "pids": pids,
                }
            ),
            flush=True,
        )

        if not port_ok:
            failures.append({"ts": ts, "check": "port_listening", "detail": "port 8011 not listening"})
        if health_code != 200:
            failures.append({"ts": ts, "check": "api_health", "detail": f"/api/health={health_code} err={health_err}"})
        if app_code != 200:
            failures.append({"ts": ts, "check": "app", "detail": f"/app={app_code} err={app_err}"})

        if last_pids is not None and pids != last_pids:
            pid_changes.append({"ts": ts, "from": last_pids, "to": pids})
        last_pids = pids

        time.sleep(INTERVAL_SECONDS)

    # Hidden crash heuristic: any active listener PID disappears by end of window.
    missing_final_pids = []
    for pid in (last_pids or []):
        if not pid_exists_windows(pid):
            missing_final_pids.append(pid)

    summary = {
        "window_seconds": DURATION_SECONDS,
        "sample_count": len(samples),
        "all_port_listening": all(s["port_listening"] for s in samples),
        "all_health_200": all(s["health_status"] == 200 for s in samples),
        "all_app_200": all(s["app_status"] == 200 for s in samples),
        "no_restart_loop": len(pid_changes) == 0,
        "no_hidden_startup_crash": len(missing_final_pids) == 0 and len(failures) == 0,
        "pid_changes": pid_changes,
        "missing_final_pids": missing_final_pids,
        "failure_count": len(failures),
    }

    print(json.dumps({"summary": summary, "failures": failures, "first_samples": samples[:3], "last_samples": samples[-3:]}, indent=2))


if __name__ == "__main__":
    main()
