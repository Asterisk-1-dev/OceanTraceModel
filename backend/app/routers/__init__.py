from fastapi import APIRouter

from app.routers import alerts, forecasts, incidents, reports, satellite, traffic, vessels

api_router = APIRouter()
api_router.include_router(incidents.router, tags=["incidents"])
api_router.include_router(vessels.router, tags=["vessels"])
api_router.include_router(traffic.router, tags=["traffic"])
api_router.include_router(satellite.router, tags=["satellite"])
api_router.include_router(forecasts.router, tags=["forecasts"])
api_router.include_router(alerts.router, tags=["alerts"])
api_router.include_router(reports.router, tags=["reports"])
