from abc import ABC, abstractmethod
from typing import Dict, Any, List
from app.cmir.models import CMIR, CMIRNode


class BaseProviderAdapter(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @abstractmethod
    def translate_node(self, node: CMIRNode) -> Dict[str, Any]:
        pass

    @abstractmethod
    def translate_cmir(self, cmir: CMIR) -> List[Dict[str, Any]]:
        pass
