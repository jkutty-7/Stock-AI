"""FastAPI dependency injection utilities."""

from src.services.database import db


async def get_db():
    """Dependency that provides the database instance."""
    return db
