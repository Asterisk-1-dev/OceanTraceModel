from fastapi import APIRouter

from app.schemas import Vessel
from app.services.vessels import VesselService

router = APIRouter(prefix="/vessels")
service = VesselService()


@router.get("", response_model=list[Vessel])
def list_vessels():
    return service.list_vessels()


@router.get("/{mmsi}", response_model=Vessel)
def get_vessel(mmsi: str):
    return service.get_vessel(mmsi)
