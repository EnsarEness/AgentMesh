"""
AgentMesh - Auction Model & Engine
Reverse auction system: requester broadcasts a job, agents bid, lowest price wins.
"""

import json
import os
import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict
from filelock import FileLock

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
AUCTIONS_FILE = os.path.join(DATA_DIR, "auctions.json")


@dataclass
class Bid:
    """A bid submitted by an agent for an auction."""
    agent_id: str
    agent_name: str
    price: int  # lamports
    estimated_time: int  # seconds
    submitted_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Bid":
        return cls(**data)


@dataclass
class Auction:
    """A reverse auction for a job on AgentMesh."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    requester_id: str = ""
    task: str = ""
    required_capability: str = ""
    budget: int = 0  # lamports
    deadline: int = 30  # seconds for the job itself
    auction_duration: int = 10  # seconds the auction stays open
    status: str = "open"  # open, closed, awarded, expired
    bids: List[dict] = field(default_factory=list)
    winner: Optional[dict] = None
    created_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Auction":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            requester_id=data.get("requester_id", ""),
            task=data.get("task", ""),
            required_capability=data.get("required_capability", ""),
            budget=data.get("budget", 0),
            deadline=data.get("deadline", 30),
            auction_duration=data.get("auction_duration", 10),
            status=data.get("status", "open"),
            bids=data.get("bids", []),
            winner=data.get("winner"),
            created_at=data.get("created_at", time.time()),
            closed_at=data.get("closed_at"),
        )

    @property
    def time_remaining(self) -> float:
        """Seconds remaining in the auction."""
        elapsed = time.time() - self.created_at
        remaining = self.auction_duration - elapsed
        return max(0, remaining)

    @property
    def is_expired(self) -> bool:
        return self.time_remaining <= 0


class AuctionEngine:
    """Manages reverse auctions with timed bidding and auto-closure."""

    def __init__(self, auctions_path: str = AUCTIONS_FILE):
        self.auctions_path = auctions_path
        self.lock_path = auctions_path + ".lock"
        os.makedirs(os.path.dirname(self.auctions_path), exist_ok=True)
        if not os.path.exists(self.auctions_path):
            self._write([])
        # In-memory timers for auto-closing auctions
        self._timers: Dict[str, threading.Timer] = {}

    def _read(self) -> List[dict]:
        lock = FileLock(self.lock_path)
        with lock:
            with open(self.auctions_path, "r") as f:
                return json.load(f)

    def _write(self, auctions: List[dict]) -> None:
        lock = FileLock(self.lock_path)
        with lock:
            with open(self.auctions_path, "w") as f:
                json.dump(auctions, f, indent=2)

    def _update_auction(self, auction_id: str, updates: dict) -> Optional[dict]:
        """Update an auction by ID and return the updated version."""
        auctions = self._read()
        for i, a in enumerate(auctions):
            if a["id"] == auction_id:
                auctions[i].update(updates)
                self._write(auctions)
                return auctions[i]
        return None

    def create_auction(self, requester_id: str, task: str, required_capability: str,
                       budget: int, deadline: int = 30, auction_duration: int = 10) -> dict:
        """
        Create a new reverse auction.
        Starts a timer that auto-closes the auction after auction_duration seconds.
        """
        auction = Auction(
            requester_id=requester_id,
            task=task,
            required_capability=required_capability,
            budget=budget,
            deadline=deadline,
            auction_duration=auction_duration,
        )

        auctions = self._read()
        auction_dict = auction.to_dict()
        auctions.append(auction_dict)
        self._write(auctions)

        # Schedule auto-close
        timer = threading.Timer(auction_duration, self._auto_close, args=[auction.id])
        timer.daemon = True
        timer.start()
        self._timers[auction.id] = timer

        return auction_dict

    def submit_bid(self, auction_id: str, agent_id: str, agent_name: str,
                   price: int, estimated_time: int) -> dict:
        """
        Submit a bid to an auction.
        Returns the bid dict or raises ValueError if invalid.
        """
        auctions = self._read()
        auction = None
        for a in auctions:
            if a["id"] == auction_id:
                auction = a
                break

        if auction is None:
            raise ValueError("Auction not found")

        # Check auction is still open
        auction_obj = Auction.from_dict(auction)
        if auction_obj.status != "open":
            raise ValueError(f"Auction is {auction_obj.status}, not accepting bids")
        if auction_obj.is_expired:
            raise ValueError("Auction has expired")

        # Check bid is within budget
        if price > auction["budget"]:
            raise ValueError(f"Bid price {price} exceeds budget {auction['budget']}")

        # Check agent hasn't already bid
        for bid in auction.get("bids", []):
            if bid["agent_id"] == agent_id:
                raise ValueError("Agent has already submitted a bid")

        bid = Bid(
            agent_id=agent_id,
            agent_name=agent_name,
            price=price,
            estimated_time=estimated_time,
        )

        bid_dict = bid.to_dict()

        # Add bid to auction
        for i, a in enumerate(auctions):
            if a["id"] == auction_id:
                auctions[i]["bids"].append(bid_dict)
                self._write(auctions)
                return bid_dict

        raise ValueError("Failed to submit bid")

    def _auto_close(self, auction_id: str) -> None:
        """Auto-close an auction and select the winner (lowest price)."""
        self._close_auction(auction_id)

    def _close_auction(self, auction_id: str) -> Optional[dict]:
        """Close an auction and determine the winner by lowest price."""
        auctions = self._read()
        for i, a in enumerate(auctions):
            if a["id"] == auction_id:
                if a["status"] != "open":
                    return a

                bids = a.get("bids", [])
                if bids:
                    # Sort by price (ascending), then by submitted_at (earliest first)
                    winner = min(bids, key=lambda b: (b["price"], b["submitted_at"]))
                    a["winner"] = winner
                    a["status"] = "awarded"
                else:
                    a["status"] = "expired"

                a["closed_at"] = time.time()
                auctions[i] = a
                self._write(auctions)

                # Clean up timer
                if auction_id in self._timers:
                    del self._timers[auction_id]

                return a
        return None

    def get_auction(self, auction_id: str) -> Optional[dict]:
        """Get auction by ID, with live time_remaining."""
        auctions = self._read()
        for a in auctions:
            if a["id"] == auction_id:
                auction_obj = Auction.from_dict(a)
                a["time_remaining"] = round(auction_obj.time_remaining, 1)

                # Auto-expire if time is up and still open
                if auction_obj.is_expired and a["status"] == "open":
                    self._close_auction(auction_id)
                    return self.get_auction(auction_id)

                return a
        return None

    def get_winner(self, auction_id: str) -> Optional[dict]:
        """Get the winner of an auction. Forces close if expired."""
        auction = self.get_auction(auction_id)
        if auction is None:
            return None

        if auction["status"] == "open":
            auction_obj = Auction.from_dict(auction)
            if auction_obj.is_expired:
                self._close_auction(auction_id)
                auction = self.get_auction(auction_id)

        return {
            "auction_id": auction["id"],
            "task": auction["task"],
            "status": auction["status"],
            "total_bids": len(auction.get("bids", [])),
            "winner": auction.get("winner"),
        }

    def list_auctions(self, status: Optional[str] = None) -> List[dict]:
        """List all auctions, optionally filtered by status."""
        auctions = self._read()
        result = []
        for a in auctions:
            auction_obj = Auction.from_dict(a)
            a["time_remaining"] = round(auction_obj.time_remaining, 1)

            # Auto-expire if needed
            if auction_obj.is_expired and a["status"] == "open":
                self._close_auction(a["id"])
                a = self.get_auction(a["id"]) or a

            if status and a["status"] != status:
                continue
            result.append(a)
        return result
