from typing import List, Set
from app.cmir.models import CMIR


def extract_subgraph_cmir(cmir: CMIR, selected_ids: List[str]) -> CMIR:
    """Extract a valid CMIR subgraph containing the specified node IDs and their internal relationships."""
    id_set: Set[str] = set(selected_ids)
    sub_nodes = [res for res in cmir.resources if res.id in id_set]
    sub_rels = [
        rel for rel in cmir.relationships
        if rel.source in id_set and rel.target in id_set
    ]
    return cmir.model_copy(
        update={
            "resources": sub_nodes,
            "relationships": sub_rels,
        }
    )
