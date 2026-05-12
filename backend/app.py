"""
AgentMesh - Flask Backend
REST API for agent registration, management, and reverse auctions.
"""

import sys
import os

# Add project root to path so we can import as `backend.xxx`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify
from flask_cors import CORS
from backend.agent import Agent
from backend.registry import AgentRegistry
from backend.solana_utils import generate_keypair
from backend.auction import AuctionEngine
from backend.job import JobManager

app = Flask(__name__)
CORS(app)

registry = AgentRegistry()
auction_engine = AuctionEngine()
job_manager = JobManager(registry=registry)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "agentmesh-backend"})


@app.route("/stats", methods=["GET"])
def get_stats():
    """Protocol-wide statistics."""
    agents = registry.list_agents()
    auctions = auction_engine.list_auctions()
    jobs = job_manager.list_jobs()
    total_sol = sum(j.get("price", 0) for j in jobs if j.get("status") == "paid") / 1e9
    completed_jobs = [j for j in jobs if j.get("status") in ("completed", "paid")]
    return jsonify({
        "total_agents": len(agents),
        "total_auctions": len(auctions),
        "open_auctions": len([a for a in auctions if a.get("status") == "open"]),
        "awarded_auctions": len([a for a in auctions if a.get("status") == "awarded"]),
        "total_jobs": len(jobs),
        "completed_jobs": len(completed_jobs),
        "total_sol_transferred": round(total_sol, 6),
        "avg_job_price_lamports": round(sum(j.get("price", 0) for j in completed_jobs) / max(len(completed_jobs), 1)),
    }), 200


# ─── Agent Registry ──────────────────────────────────────────────────────────

@app.route("/agents/register", methods=["POST"])
def register_agent():
    """
    Register a new agent.
    Body: { name: str, capabilities: [str], price_per_request: int }
    Auto-generates a Solana keypair for the agent.
    """
    data = request.get_json()

    # Validate required fields
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    name = data.get("name")
    capabilities = data.get("capabilities")
    price_per_request = data.get("price_per_request")

    if not name or not isinstance(name, str):
        return jsonify({"error": "name is required and must be a string"}), 400
    if not capabilities or not isinstance(capabilities, list):
        return jsonify({"error": "capabilities is required and must be an array"}), 400
    if price_per_request is None or not isinstance(price_per_request, (int, float)):
        return jsonify({"error": "price_per_request is required and must be a number"}), 400

    # Generate or reuse Solana keypair for the agent
    wallet_address = data.get("wallet_address")
    keypair = generate_keypair()
    
    agent = Agent(
        name=name,
        capabilities=capabilities,
        price_per_request=int(price_per_request),
        wallet_address=wallet_address or keypair["public_key"],
        public_key=wallet_address or keypair["public_key"],
    )

    try:
        result = registry.register(agent)
        # Include the secret key only in the registration response
        result["_secret_key"] = keypair["secret_key"]
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 409


@app.route("/agents/list", methods=["GET"])
def list_agents():
    """List all registered agents."""
    agents = registry.list_agents()
    return jsonify(agents), 200


@app.route("/agents/<agent_id>", methods=["GET"])
def get_agent(agent_id):
    """Get a specific agent by ID."""
    agent = registry.get_agent(agent_id)
    if agent is None:
        return jsonify({"error": "Agent not found"}), 404
    return jsonify(agent), 200


@app.route("/agents/search", methods=["GET"])
def search_agents():
    """Search agents by capability. Query: ?capability=xxx"""
    capability = request.args.get("capability")
    if not capability:
        return jsonify({"error": "capability query parameter is required"}), 400
    agents = registry.find_by_capability(capability)
    return jsonify(agents), 200


# ─── Reverse Auctions ────────────────────────────────────────────────────────

@app.route("/auction/create", methods=["POST"])
def create_auction():
    """
    Create a new reverse auction.
    Body: { requester_id, task, required_capability, budget, deadline?, auction_duration? }
    budget is in lamports. auction_duration defaults to 10 seconds.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    requester_id = data.get("requester_id")
    task = data.get("task")
    required_capability = data.get("required_capability")
    budget = data.get("budget")

    if not requester_id:
        return jsonify({"error": "requester_id is required"}), 400
    if not task:
        return jsonify({"error": "task is required"}), 400
    if not required_capability:
        return jsonify({"error": "required_capability is required"}), 400
    if budget is None or not isinstance(budget, (int, float)):
        return jsonify({"error": "budget is required and must be a number"}), 400

    # Verify requester exists
    requester = registry.get_agent(requester_id)
    if requester is None:
        return jsonify({"error": "Requester agent not found"}), 404

    # Find eligible agents (those with the required capability, excluding requester)
    eligible_agents = [
        a for a in registry.find_by_capability(required_capability)
        if a["id"] != requester_id
    ]

    auction_dict = auction_engine.create_auction(
        requester_id=requester_id,
        task=task,
        required_capability=required_capability,
        budget=int(budget),
        deadline=data.get("deadline", 30),
        auction_duration=data.get("auction_duration", 10),
    )

    auction_dict["eligible_agents"] = [
        {"id": a["id"], "name": a["name"], "price_per_request": a["price_per_request"]}
        for a in eligible_agents
    ]

    return jsonify(auction_dict), 201


@app.route("/auction/bid", methods=["POST"])
def submit_bid():
    """
    Submit a bid to an auction.
    Body: { auction_id, agent_id, price, estimated_time }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    auction_id = data.get("auction_id")
    agent_id = data.get("agent_id")
    price = data.get("price")
    estimated_time = data.get("estimated_time")

    if not auction_id:
        return jsonify({"error": "auction_id is required"}), 400
    if not agent_id:
        return jsonify({"error": "agent_id is required"}), 400
    if price is None:
        return jsonify({"error": "price is required"}), 400
    if estimated_time is None:
        return jsonify({"error": "estimated_time is required"}), 400

    # Verify agent exists
    agent = registry.get_agent(agent_id)
    if agent is None:
        return jsonify({"error": "Agent not found"}), 404

    # Verify agent has the required capability
    auction = auction_engine.get_auction(auction_id)
    if auction is None:
        return jsonify({"error": "Auction not found"}), 404

    required_cap = auction.get("required_capability", "")
    agent_caps = [c.lower() for c in agent.get("capabilities", [])]
    if required_cap.lower() not in agent_caps:
        return jsonify({
            "error": f"Agent lacks required capability: {required_cap}"
        }), 403

    try:
        bid_dict = auction_engine.submit_bid(
            auction_id=auction_id,
            agent_id=agent_id,
            agent_name=agent.get("name", "Unknown"),
            price=int(price),
            estimated_time=int(estimated_time),
        )
        return jsonify(bid_dict), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/auction/<auction_id>/winner", methods=["GET"])
def get_auction_winner(auction_id):
    """
    Resolved auction summary: status, winner, total_bids (matches Node / Socket consumers).
    """
    result = auction_engine.get_winner(auction_id)
    if result is None:
        return jsonify({"error": "Auction not found"}), 404
    return jsonify(result), 200


@app.route("/auction/<auction_id>", methods=["GET"])
def get_auction(auction_id):
    """Get auction details by ID."""
    auction = auction_engine.get_auction(auction_id)
    if auction is None:
        return jsonify({"error": "Auction not found"}), 404
    return jsonify(auction), 200


@app.route("/auction/list", methods=["GET"])
def list_auctions():
    """List all auctions. Optional query: ?status=open|closed|awarded|expired"""
    status = request.args.get("status")
    auctions = auction_engine.list_auctions(status=status)
    return jsonify(auctions), 200


# ─── Job Execution ────────────────────────────────────────────────────────────

@app.route("/job/execute", methods=["POST"])
def execute_job():
    """
    Create and execute a job from an awarded auction.
    Body: { auction_id }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    auction_id = data.get("auction_id")
    if not auction_id:
        return jsonify({"error": "auction_id is required"}), 400

    # Get the auction
    auction = auction_engine.get_auction(auction_id)
    if auction is None:
        return jsonify({"error": "Auction not found"}), 404
    if auction.get("status") != "awarded":
        return jsonify({"error": f"Auction status is '{auction.get('status')}', expected 'awarded'"}), 400

    try:
        # Create job from auction
        job = job_manager.create_from_auction(auction)
        # Execute immediately (mock)
        job = job_manager.execute_job(job["id"])
        return jsonify(job), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/job/<job_id>/status", methods=["GET"])
def get_job_status(job_id):
    """Get job status by ID."""
    job = job_manager.get_job(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job), 200


@app.route("/job/<job_id>/mark-paid", methods=["POST"])
def mark_job_paid(job_id):
    """
    Mark a job as paid with a Solana tx signature.
    Body: { tx_signature }
    """
    data = request.get_json()
    tx_signature = data.get("tx_signature", "") if data else ""
    if not tx_signature:
        return jsonify({"error": "tx_signature is required"}), 400

    try:
        job = job_manager.mark_paid(job_id, tx_signature)
        return jsonify(job), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/job/list", methods=["GET"])
def list_jobs():
    """List all jobs. Optional query: ?status=pending|completed|paid"""
    status = request.args.get("status")
    jobs = job_manager.list_jobs(status=status)
    return jsonify(jobs), 200


if __name__ == "__main__":
    print("🚀 AgentMesh Python Backend starting on port 5001...")
    app.run(host="0.0.0.0", port=5001, debug=False)


# Fix Vercel path prefix mapping
class VercelPathFix:
    def __init__(self, app):
        self.app = app
    def __call__(self, environ, start_response):
        if environ.get('PATH_INFO', '').startswith('/python-api'):
            environ['PATH_INFO'] = environ['PATH_INFO'].replace('/python-api', '', 1)
        return self.app(environ, start_response)

app.wsgi_app = VercelPathFix(app.wsgi_app)
