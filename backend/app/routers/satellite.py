from fastapi import APIRouter

from app.schemas import ProcessSatelliteRequest, ProcessSatelliteResponse, SatelliteScene
from app.services.satellite import SatelliteService

router = APIRouter(prefix="/satellite")
service = SatelliteService()


@router.get("/scenes", response_model=list[SatelliteScene])
def list_scenes():
    return service.list_scenes()


@router.get("/scenes/{scene_id}", response_model=SatelliteScene)
def get_scene(scene_id: str):
    return service.get_scene(scene_id)


@router.post("/process", response_model=ProcessSatelliteResponse)
def process_scene(payload: ProcessSatelliteRequest):
    return service.process_scene(payload.scene_id)
