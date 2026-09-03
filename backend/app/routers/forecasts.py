from fastapi import APIRouter

from app.schemas import Forecast
from app.services.forecasts import ForecastService

router = APIRouter(prefix="/incidents")
service = ForecastService()


@router.get("/{incident_id}/forecast", response_model=Forecast)
def get_forecast(incident_id: str):
    return service.get_forecast(incident_id)
