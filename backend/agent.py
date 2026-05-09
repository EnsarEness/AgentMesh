"""
AgentMesh - Agent Model
Defines the Agent dataclass for the AgentMesh protocol.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional
from datetime import datetime, timezone
import uuid


@dataclass
class Agent:
    """Represents an AI agent registered on the AgentMesh protocol."""
    
    name: str
    capabilities: List[str]
    price_per_request: int  # in lamports
    wallet_address: str = ""
    public_key: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    registered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    reputation_score: float = 0.0
    completed_jobs: int = 0
    total_jobs: int = 0

    def to_dict(self) -> dict:
        """Serialize agent to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Agent":
        """Deserialize agent from dictionary."""
        return cls(
            name=data["name"],
            capabilities=data["capabilities"],
            price_per_request=data["price_per_request"],
            wallet_address=data.get("wallet_address", ""),
            public_key=data.get("public_key", ""),
            id=data.get("id", str(uuid.uuid4())),
            registered_at=data.get(
                "registered_at", datetime.now(timezone.utc).isoformat()
            ),
            reputation_score=data.get("reputation_score", 0.0),
            completed_jobs=data.get("completed_jobs", 0),
            total_jobs=data.get("total_jobs", 0),
        )

    def __repr__(self) -> str:
        return (
            f"Agent(name='{self.name}', capabilities={self.capabilities}, "
            f"price={self.price_per_request} lamports, wallet={self.wallet_address[:8]}...)"
        )
