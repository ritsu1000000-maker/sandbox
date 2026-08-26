from .config import PLANS, Settings
from .database import RentalDatabase
from .redis_database import RedisRentalDatabase
from .manager import RentalManager
from .rental_service import RentalService
from .errors import ServiceError


def build_database(settings):
    if settings.redis_url:
        return RedisRentalDatabase(settings.redis_url)
    return RentalDatabase(settings.database_url)


__all__ = [
    "PLANS",
    "Settings",
    "RentalDatabase",
    "RedisRentalDatabase",
    "build_database",
    "RentalManager",
    "RentalService",
    "ServiceError",
]
