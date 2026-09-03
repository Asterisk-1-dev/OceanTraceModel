"""
OceanTrace — AIS Provider Abstract Interface & Provider Contract
Defines the uniform abstraction through which OceanTrace queries AIS vessel data
from streaming, local historical, research archive, and synthetic mock sources.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from ml.ais_types import AISPosition, VesselIdentity, VesselTrack, AISQuery


class AISProvider(ABC):
    """
    Abstract interface for AIS vessel data providers.
    Decouples the downstream spatiotemporal correlation engine from specific
    external APIs, databases, files, or streaming transports.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Returns unique identifier for this provider (e.g., 'aisstream', 'historical_sqlite', 'synthetic')."""
        pass

    @abstractmethod
    def query_positions(self, query: AISQuery) -> List[AISPosition]:
        """
        Retrieves raw, canonical AIS position reports matching the spatiotemporal bounding box.

        Args:
            query (AISQuery): Spatiotemporal bounds and optional MMSI filters.

        Returns:
            List[AISPosition]: Matching canonical position reports.
        """
        pass

    @abstractmethod
    def query_tracks(self, query: AISQuery) -> List[VesselTrack]:
        """
        Retrieves pre-grouped, chronologically sorted vessel tracks with data-quality audits
        matching the spatiotemporal bounding box.

        Args:
            query (AISQuery): Spatiotemporal bounds and optional MMSI filters.

        Returns:
            List[VesselTrack]: List of valid, ordered vessel tracks.
        """
        pass

    @abstractmethod
    def lookup_vessel(self, mmsi: str) -> Optional[VesselIdentity]:
        """
        Looks up static vessel identity metadata by MMSI.

        Args:
            mmsi (str): 9-digit MMSI string.

        Returns:
            Optional[VesselIdentity]: Vessel identity if known, otherwise None.
        """
        pass


class AISProviderRegistry:
    """
    Registry for configuring, registering, and retrieving active AIS providers.
    """
    def __init__(self):
        self._providers: Dict[str, AISProvider] = {}
        self._default_provider_id: Optional[str] = None

    def register_provider(self, provider: AISProvider, set_as_default: bool = False) -> None:
        """Registers an AISProvider instance."""
        pid = provider.provider_id
        self._providers[pid] = provider
        if set_as_default or self._default_provider_id is None:
            self._default_provider_id = pid

    def get_provider(self, provider_id: Optional[str] = None) -> AISProvider:
        """Retrieves a provider by ID, or returns default provider if None."""
        pid = provider_id or self._default_provider_id
        if not pid or pid not in self._providers:
            raise KeyError(f"No AISProvider registered with ID '{pid}'. Available: {list(self._providers.keys())}")
        return self._providers[pid]

    def list_providers(self) -> List[str]:
        """Returns list of registered provider IDs."""
        return list(self._providers.keys())
