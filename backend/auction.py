"""
AgentMesh - Auction Model & Engine
Supabase-backed reverse auction system.
"""

import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict
from backend.supabase_client import supabase

@dataclass
class Bid:
    agent_id: str
    agent_name: str
    price: int
    estimated_time: int
    submitted_at: float = field(default_factory=time.time)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


@dataclass
class Auction:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    requester_id: str = ""
    task: str = ""
    required_capability: str = ""
    budget: int = 0
    deadline: int = 30
    auction_duration: int = 10
    status: str = "open"  # open, awarded, expired
    bids: List[dict] = field(default_factory=list)
    winner: Optional[dict] = None
    created_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            id=data.get("id"),
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
            closed_at=data.get("closed_at")
        )

    def time_remaining(self) -> int:
        elapsed = time.time() - self.created_at
        rem = self.auction_duration - elapsed
        return int(rem) if rem > 0 else 0

    def is_expired(self) -> bool:
        return self.time_remaining() <= 0


class AuctionEngine:
    """Manages reverse auctions via Supabase with background auto-closure."""

    def __init__(self):
        pass

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
            auction_duration=auction_duration
        )
        
        auc_dict = auction.to_dict()
        response = supabase.table("auctions").insert(auc_dict).execute()
        created = response.data[0]

        # Start auto-close timer
        timer = threading.Timer(auction_duration + 0.5, self._auto_close, args=[created["id"]])
        timer.daemon = True
        timer.start()

        return created

    def submit_bid(self, auction_id: str, agent_id: str, agent_name: str,
                   price: int, estimated_time: int) -> dict:
        """Submit a bid to an auction."""
        res = supabase.table("auctions").select("*").eq("id", auction_id).execute()
        if not res.data:
            raise ValueError(f"Auction {auction_id} not found")
        
        auction_data = res.data[0]
        auction = Auction.from_dict(auction_data)

        if auction.status != "open":
            raise ValueError(f"Auction is {auction.status}")

        if auction.is_expired():
            self._close_auction(auction_id)
            raise ValueError("Auction has expired")

        if price > auction.budget:
            raise ValueError(f"Bid price {price} exceeds budget {auction.budget}")

        if estimated_time > auction.deadline:
            raise ValueError(f"Estimated time {estimated_time} exceeds deadline {auction.deadline}")

        # Check existing bids
        bids = auction.bids
        for b in bids:
            if b.get("agent_id") == agent_id:
                raise ValueError("Agent has already bid on this auction")

        bid = Bid(agent_id=agent_id, agent_name=agent_name, price=price, estimated_time=estimated_time)
        bids.append(bid.to_dict())

        # Update in DB
        upd = supabase.table("auctions").update({"bids": bids}).eq("id", auction_id).execute()
        return upd.data[0]

    def _auto_close(self, auction_id: str):
        """Auto-close an auction and select the winner (lowest price)."""
        self._close_auction(auction_id)

    def _close_auction(self, auction_id: str) -> Optional[dict]:
        res = supabase.table("auctions").select("*").eq("id", auction_id).execute()
        if not res.data:
            return None
        
        data = res.data[0]
        if data["status"] != "open":
            return data

        bids = data.get("bids", [])
        status = "expired"
        winner = None

        if bids:
            # Sort by lowest price
            bids.sort(key=lambda x: x["price"])
            winner = bids[0]
            status = "awarded"

        updates = {
            "status": status,
            "winner": winner,
            "closed_at": time.time()
        }
        
        upd_res = supabase.table("auctions").update(updates).eq("id", auction_id).execute()
        if upd_res.data:
            return upd_res.data[0]
        return None

    def _refetch_auction(self, auction_id: str) -> Optional[dict]:
        res = supabase.table("auctions").select("*").eq("id", auction_id).execute()
        return res.data[0] if res.data else None

    def _winner_payload(self, row: dict) -> dict:
        """
        Shape consumed by Node (Socket.IO, /demo/run): status, winner, total_bids.
        """
        bids = row.get("bids") or []
        return {
            "id": row.get("id"),
            "status": row.get("status"),
            "winner": row.get("winner"),
            "total_bids": len(bids),
            "task": row.get("task", ""),
            "required_capability": row.get("required_capability", ""),
            "budget": row.get("budget", 0),
            "created_at": row.get("created_at"),
            "closed_at": row.get("closed_at"),
        }

    def get_auction(self, auction_id: str) -> Optional[dict]:
        res = supabase.table("auctions").select("*").eq("id", auction_id).execute()
        if res.data:
            auc = res.data[0]
            # In memory enrichment for frontend real-time remaining
            a_obj = Auction.from_dict(auc)
            auc["time_remaining"] = a_obj.time_remaining() if auc["status"] == "open" else 0
            return auc
        return None

    def get_winner(self, auction_id: str) -> Optional[dict]:
        res = supabase.table("auctions").select("*").eq("id", auction_id).execute()
        if not res.data:
            return None

        data = res.data[0]
        if data["status"] == "open":
            auction = Auction.from_dict(data)
            if auction.is_expired():
                closed = self._close_auction(auction_id)
                data = closed if closed else self._refetch_auction(auction_id)
                if data is None:
                    return None

        return self._winner_payload(data)

    def list_auctions(self, status: Optional[str] = None) -> List[dict]:
        query = supabase.table("auctions").select("*")
        if status:
            query = query.eq("status", status)
        
        res = query.execute()
        auctions = res.data

        # Enrich with time_remaining and auto-close if needed
        enriched = []
        for auc in auctions:
            if auc["status"] == "open":
                a_obj = Auction.from_dict(auc)
                if a_obj.is_expired():
                    closed = self._close_auction(auc["id"])
                    if closed:
                        auc = closed
                else:
                    auc["time_remaining"] = a_obj.time_remaining()
            
            if "time_remaining" not in auc:
                auc["time_remaining"] = 0
            enriched.append(auc)

        # Sort by creation time (newest first)
        enriched.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return enriched
