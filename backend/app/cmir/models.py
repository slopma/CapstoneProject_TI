from typing import List, Optional

from pydantic import BaseModel


class Resource(BaseModel):
    id: str
    name: str
    type: str
    platform: Optional[str] = None
    engine: Optional[str] = None
    location: str


class Relationship(BaseModel):
    source: str
    target: str
    type: str


class CMIR(BaseModel):
    name: str
    provider: str
    resources: List[Resource]
    relationships: List[Relationship]