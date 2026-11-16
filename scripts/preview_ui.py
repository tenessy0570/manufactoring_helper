"""Preview the interface with explicitly labeled sample data, without database services."""

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.web.router import WEB_ROOT, router

app = FastAPI(title="EVE Manufacturing UI preview")
app.include_router(router)
app.mount("/static", StaticFiles(directory=str(WEB_ROOT / "static")), name="static")


if __name__ == "__main__":
    print("Interface preview: http://127.0.0.1:8765/?demo=1", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8765)
