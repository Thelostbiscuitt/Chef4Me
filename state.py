"""Shared service container — accessible from any module."""
from services.database import DatabaseService
from services.gemini import GeminiService
from services.notion_client import NotionService
from services.scheduler import SchedulerService

db: DatabaseService = None  # type: ignore
gemini: GeminiService = None  # type: ignore
notion: NotionService = None  # type: ignore
scheduler: SchedulerService = None  # type: ignore
