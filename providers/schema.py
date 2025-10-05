from pydantic import BaseModel
from typing import Any, List, Optional


class Choice(BaseModel):
    text: Optional[str] = None
    message: Optional[dict] = None


class ProviderResponse(BaseModel):
    # Minimal canonical fields
    text: Optional[str] = None
    choices: Optional[List[Any]] = None
    raw: Optional[Any] = None
