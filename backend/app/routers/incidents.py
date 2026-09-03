from fastapi import APIRouter

from app.schemas import EvidenceResponse, Incident, RecommendationResponse, Slick, Vessel
from app.services.incidents import IncidentService

router = APIRouter(prefix="/incidents")
service = IncidentService()


@router.get("", response_model=list[Incident])
def list_incidents():
    return service.list_incidents()


@router.get("/{incident_id}", response_model=Incident)
def get_incident(incident_id: str):
    return service.get_incident(incident_id)


@router.get("/{incident_id}/slick", response_model=Slick)
def get_slick(incident_id: str):
    return service.get_slick(incident_id)


@router.get("/{incident_id}/slick/metrics")
def get_slick_metrics(incident_id: str):
    return service.slick_metrics(incident_id)


@router.get("/{incident_id}/vessels", response_model=list[Vessel])
def get_incident_vessels(incident_id: str):
    return service.vessels(incident_id)


@router.get("/{incident_id}/recommendations", response_model=RecommendationResponse)
def get_recommendations(incident_id: str):
    return service.recommendations(incident_id)


@router.get("/{incident_id}/evidence", response_model=EvidenceResponse)
def get_evidence(incident_id: str):
    return service.evidence(incident_id)
