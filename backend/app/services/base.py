from fastapi import HTTPException, status

from app.services.providers import provider_factory


class BaseService:
    def __init__(self):
        self.repo = provider_factory.repository()

    def not_found(self, detail: str = "Resource not found"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
