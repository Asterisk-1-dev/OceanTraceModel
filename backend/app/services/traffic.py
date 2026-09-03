from app.services.base import BaseService


class TrafficService(BaseService):
    def get_traffic(self, stage: str = "Suspects"):
        return self.repo.traffic(stage)
