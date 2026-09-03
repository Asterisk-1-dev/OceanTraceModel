from app.services.base import BaseService


class ForecastService(BaseService):
    def get_forecast(self, incident_id: str):
        forecast = self.repo.forecast(incident_id)
        return forecast or self.not_found("Incident forecast not found")
