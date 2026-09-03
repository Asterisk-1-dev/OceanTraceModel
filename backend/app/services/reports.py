from app.services.base import BaseService


class ReportService(BaseService):
    def list_reports(self):
        return self.repo.list_reports()

    def get_report(self, report_id: str):
        report = self.repo.get_report(report_id)
        return report or self.not_found("Report not found")

    def geojson(self, report_id: str):
        geojson = self.repo.report_geojson(report_id)
        return geojson or self.not_found("Report GeoJSON not found")
