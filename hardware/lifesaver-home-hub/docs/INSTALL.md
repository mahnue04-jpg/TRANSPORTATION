# Future Raspberry Pi install (not executed tonight)

Supported OS assumption: Raspberry Pi OS 64-bit, current stable.  
Python: 3.11+.

1. Copy this directory to the Pi.
2. `python -m venv .venv` and activate it.
3. `pip install -r requirements.txt`
4. Copy `config.example.env` to `.env` and set a **private** host plus a generated token. Never commit secrets.
5. Start: `python scripts/start_local.py`
6. Health check: `GET /health`
7. Logs: write only under a local `./logs` folder on the Pi. Metadata only.
8. Keep the host firewall limited to the private LAN.
9. Restart: stop the process and start again.
10. Uninstall: remove the directory and virtualenv.
11. Factory-reset prototype data: delete local state files; tokens must be regenerated.

Do not install this on a public host. Do not open GPIO tonight.
