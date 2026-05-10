"""
AgentMesh - Agent Registry
Supabase-backed registry for agent storage.
"""

from typing import List, Optional
from backend.agent import Agent
from backend.supabase_client import supabase

class AgentRegistry:
    """Supabase-backed agent registry."""

    def __init__(self):
        pass

    def register(self, agent: Agent) -> dict:
        """
        Register a new agent in the registry.
        Returns the registered agent as a dict.
        """
        # Check for duplicate names
        existing = supabase.table("agents").select("id").ilike("name", agent.name).execute()
        if existing.data:
            raise ValueError(f"Agent with name '{agent.name}' already exists")
        
        agent_dict = agent.to_dict()
        response = supabase.table("agents").insert(agent_dict).execute()
        return response.data[0]

    def list_agents(self) -> List[dict]:
        """Return all registered agents."""
        response = supabase.table("agents").select("*").execute()
        return response.data

    def get_agent(self, agent_id: str) -> Optional[dict]:
        """Get a specific agent by ID."""
        response = supabase.table("agents").select("*").eq("id", agent_id).execute()
        if response.data:
            return response.data[0]
        return None

    def update_agent(self, agent_id: str, updates: dict) -> Optional[dict]:
        """Update an agent's fields by ID."""
        response = supabase.table("agents").update(updates).eq("id", agent_id).execute()
        if response.data:
            return response.data[0]
        return None

    def find_by_capability(self, capability: str) -> List[dict]:
        """Find all agents that have a given capability."""
        # Supabase Postgres array contains query
        # Since capabilities are array of strings, we use the `cs` (contains) array operator in PostgREST
        # However, for simplicity and case-insensitivity, we can fetch all and filter in Python,
        # or use exact array match if we assume case matches. Let's do a Python filter for now.
        agents = self.list_agents()
        return [
            a for a in agents
            if capability.lower() in [c.lower() for c in a.get("capabilities", [])]
        ]

    def clear(self) -> None:
        """Clear all agents from the registry (for testing only)."""
        # supabase-py doesn't support truncate easily, so we delete where ID is not null
        supabase.table("agents").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
