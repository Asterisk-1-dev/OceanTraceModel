from fastapi import APIRouter

from app.schemas import Report
from app.services.reports import ReportService

router = APIRouter(prefix="/reports")
service = ReportService()


@router.get("", response_model=list[Report])
def list_reports():
    return service.list_reports()


@router.get("/{report_id}", response_model=Report)
def get_report(report_id: str):
    return service.get_report(report_id)


@router.get("/{report_id}/geojson")
def get_report_geojson(report_id: str):
    return service.geojson(report_id)
