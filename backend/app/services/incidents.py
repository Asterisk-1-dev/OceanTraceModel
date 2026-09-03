from app.services.base import BaseService


class IncidentService(BaseService):
    def list_incidents(self):
        return self.repo.list_incidents()

    def get_incident(self, incident_id: str):
        incident = self.repo.get_incident(incident_id)
        return incident or self.not_found("Incident not found")

    def get_slick(self, incident_id: str):
        slick = self.repo.get_slick(incident_id)
        return slick or self.not_found("Incident slick not found")

    def slick_metrics(self, incident_id: str):
        metrics = self.repo.slick_metrics(incident_id)
        return metrics or self.not_found("Incident slick metrics not found")

    def vessels(self, incident_id: str):
        vessels = self.repo.vessels_for_incident(incident_id)
        return vessels if vessels is not None else self.not_found("Incident not found")

    def recommendations(self, incident_id: str):
        data = self.repo.recommendations(incident_id)
        return data or self.not_found("Incident recommendations not found")

    def evidence(self, incident_id: str):
        data = self.repo.evidence(incident_id)
        return data or self.not_found("Incident evidence not found")
