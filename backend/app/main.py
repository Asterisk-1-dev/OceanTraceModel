import sys
import os

# Ensure backend and project root are always in sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
root_dir = os.path.dirname(backend_dir)
for d in (backend_dir, root_dir):
    if d not in sys.path:
        sys.path.insert(0, d)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import api_router
from app.websocket.routes import router as websocket_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="AQUAVIGIL Intelligence API",
        version="0.2.0",
        description="Demo-ready backend for OceanTrace/AQUAVIGIL maritime incident intelligence.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": settings.app_mode, "service": settings.app_name}

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(websocket_router)
    return app


app = create_app()
