"""
AgentMesh - Agent Registry
Thread-safe JSON-backed registry for agent storage (mock on-chain).
"""

import json
import os
from typing import List, Optional
from filelock import FileLock
from backend.agent import Agent

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
REGISTRY_FILE = os.path.join(DATA_DIR, "registry.json")
LOCK_FILE = REGISTRY_FILE + ".lock"


class AgentRegistry:
    """Thread-safe JSON-backed agent registry."""

    def __init__(self, registry_path: str = REGISTRY_FILE):
        self.registry_path = registry_path
        self.lock_path = registry_path + ".lock"
        os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
        if not os.path.exists(self.registry_path):
            self._write([])

    def _read(self) -> List[dict]:
        """Read all agents from JSON file."""
        lock = FileLock(self.lock_path)
        with lock:
            with open(self.registry_path, "r") as f:
                return json.load(f)

    def _write(self, agents: List[dict]) -> None:
        """Write agents list to JSON file."""
        lock = FileLock(self.lock_path)
        with lock:
            with open(self.registry_path, "w") as f:
                json.dump(agents, f, indent=2)

    def register(self, agent: Agent) -> dict:
        """
        Register a new agent in the registry.
        Returns the registered agent as a dict.
        """
        agents = self._read()
        
        # Check for duplicate names
        for existing in agents:
            if existing["name"].lower() == agent.name.lower():
                raise ValueError(f"Agent with name '{agent.name}' already exists")
        
        agent_dict = agent.to_dict()
        agents.append(agent_dict)
        self._write(agents)
        return agent_dict

    def list_agents(self) -> List[dict]:
        """Return all registered agents."""
        return self._read()

    def get_agent(self, agent_id: str) -> Optional[dict]:
        """Get a specific agent by ID."""
        agents = self._read()
        for agent in agents:
            if agent["id"] == agent_id:
                return agent
        return None

    def update_agent(self, agent_id: str, updates: dict) -> Optional[dict]:
        """Update an agent's fields by ID."""
        agents = self._read()
        for i, agent in enumerate(agents):
            if agent["id"] == agent_id:
                agents[i].update(updates)
                self._write(agents)
                return agents[i]
        return None

    def find_by_capability(self, capability: str) -> List[dict]:
        """Find all agents that have a given capability."""
        agents = self._read()
        return [
            a for a in agents
            if capability.lower() in [c.lower() for c in a.get("capabilities", [])]
        ]

    def clear(self) -> None:
        """Clear all agents from the registry."""
        self._write([])
