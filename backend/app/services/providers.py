from app.services.pipeline_repository import PipelineRepository


class ProviderFactory:
    def __init__(self):
        self._repository = PipelineRepository()

    def repository(self) -> PipelineRepository:
        return self._repository


provider_factory = ProviderFactory()
