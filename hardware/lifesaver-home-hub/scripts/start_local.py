"""Start the Home Hub agent on loopback. No public bind."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from lifesaver_home_hub.app import router
from lifesaver_home_hub.config import is_private_host, load_config

config = load_config()
if not is_private_host(config.host):
    raise SystemExit("Refusing to start on a public host.")

app = FastAPI(title="Lifesaver Home Hub agent")
app.include_router(router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8041)
