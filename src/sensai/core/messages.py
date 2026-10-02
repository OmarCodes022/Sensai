"""Shared message model, independent of any backend."""
from typing import Literal

from pydantic import BaseModel, ConfigDict

Role = Literal["system", "user", "assistant"]


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    content: str
