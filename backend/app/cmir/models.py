from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class CMIRNode(BaseModel):
    id: str
    name: str
    type: str
    category: Optional[str] = "resource"
    parent_id: Optional[str] = None
    children_ids: List[str] = Field(default_factory=list)
    level: int = 0
    provider: Optional[str] = "aws"
    platform: Optional[str] = None
    engine: Optional[str] = None
    location: Optional[str] = "us-east-1"
    environment: Optional[str] = "production"
    status: str = "DISCOVERED"
    is_shared: bool = False
    security: Dict[str, Any] = Field(default_factory=dict)
    network: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# Backward compatibility alias
Resource = CMIRNode


class CMIRRelationship(BaseModel):
    source: str
    target: str
    type: str = "depends_on"
    metadata: Dict[str, Any] = Field(default_factory=dict)


# Backward compatibility alias
Relationship = CMIRRelationship


class CMIR(BaseModel):
    name: str
    provider: str
    version: str = "2.0"
    resources: List[CMIRNode]
    relationships: List[CMIRRelationship]
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_node(self, node_id: str) -> Optional[CMIRNode]:
        for res in self.resources:
            if res.id == node_id:
                return res
        return None