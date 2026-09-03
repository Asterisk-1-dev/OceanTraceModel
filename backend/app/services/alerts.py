from app.services.base import BaseService


class AlertService(BaseService):
    def list_alerts(self):
        return self.repo.list_alerts()

    def get_alert(self, alert_id: str):
        alert = self.repo.get_alert(alert_id)
        return alert or self.not_found("Alert not found")
