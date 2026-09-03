from fastapi import APIRouter

from app.schemas import Alert
from app.services.alerts import AlertService

router = APIRouter(prefix="/alerts")
service = AlertService()


@router.get("", response_model=list[Alert])
def list_alerts():
    return service.list_alerts()


@router.get("/{alert_id}", response_model=Alert)
def get_alert(alert_id: str):
    return service.get_alert(alert_id)
