from pydantic import BaseModel, Field
from typing import Optional


class UserPreferences(BaseModel):
    user_id: int
    dietary_restrictions: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    preferred_cuisines: list[str] = Field(default_factory=list)
    skill_level: str = "beginner"
    serving_size: int = Field(default=2, ge=1, le=20)
    notifications_enabled: bool = True
    notion_token: Optional[str] = None
    notion_database_id: Optional[str] = None


class UserProfile(BaseModel):
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    preferences: Optional[UserPreferences] = None
