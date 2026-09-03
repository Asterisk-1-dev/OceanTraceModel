from fastapi import APIRouter

from app.schemas import TrafficResponse
from app.services.traffic import TrafficService

router = APIRouter(prefix="/traffic")
service = TrafficService()


@router.get("", response_model=TrafficResponse)
def get_traffic(stage: str = "Suspects"):
    return service.get_traffic(stage)
