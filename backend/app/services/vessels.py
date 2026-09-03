from app.services.base import BaseService


class VesselService(BaseService):
    def list_vessels(self):
        return self.repo.list_vessels()

    def get_vessel(self, mmsi: str):
        vessel = self.repo.get_vessel(mmsi)
        return vessel or self.not_found("Vessel not found")
