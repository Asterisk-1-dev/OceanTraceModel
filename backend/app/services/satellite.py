from app.services.base import BaseService


class SatelliteService(BaseService):
    def list_scenes(self):
        return self.repo.list_scenes()

    def get_scene(self, scene_id: str):
        scene = self.repo.get_scene(scene_id)
        return scene or self.not_found("Satellite scene not found")

    def process_scene(self, scene_id: str):
        result = self.repo.process_scene(scene_id)
        if result.status == "not_found":
            return self.not_found("Satellite scene not found")
        return result
