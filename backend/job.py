"""
AgentMesh - Job Execution
Handles job lifecycle: create from auction winner, mock execute, track status.
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from filelock import FileLock

# True AI Integration
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
JOBS_FILE = os.path.join(DATA_DIR, "jobs.json")


@dataclass
class Job:
    """A job created from an awarded auction."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    auction_id: str = ""
    task: str = ""
    requester_id: str = ""
    worker_id: str = ""
    worker_name: str = ""
    price: int = 0  # lamports agreed upon
    status: str = "pending"  # pending, executing, completed, failed, paid
    result: Optional[dict] = None
    payment_tx: Optional[str] = None  # Solana transaction signature
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    paid_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            auction_id=data.get("auction_id", ""),
            task=data.get("task", ""),
            requester_id=data.get("requester_id", ""),
            worker_id=data.get("worker_id", ""),
            worker_name=data.get("worker_name", ""),
            price=data.get("price", 0),
            status=data.get("status", "pending"),
            result=data.get("result"),
            payment_tx=data.get("payment_tx"),
            created_at=data.get("created_at", time.time()),
            completed_at=data.get("completed_at"),
            paid_at=data.get("paid_at"),
        )


class JobManager:
    """Manages job lifecycle from auction award to completion and payment."""

    def __init__(self, jobs_path: str = JOBS_FILE, registry=None):
        self._registry = registry
        self.jobs_path = jobs_path
        self.lock_path = jobs_path + ".lock"
        os.makedirs(os.path.dirname(self.jobs_path), exist_ok=True)
        if not os.path.exists(self.jobs_path):
            self._write([])

    def _read(self) -> List[dict]:
        lock = FileLock(self.lock_path)
        with lock:
            with open(self.jobs_path, "r") as f:
                return json.load(f)

    def _write(self, jobs: List[dict]) -> None:
        lock = FileLock(self.lock_path)
        with lock:
            with open(self.jobs_path, "w") as f:
                json.dump(jobs, f, indent=2)

    def create_from_auction(self, auction: dict) -> dict:
        """
        Create a job from an awarded auction.
        The auction must have status 'awarded' and a winner.
        """
        if auction.get("status") != "awarded":
            raise ValueError("Auction is not awarded yet")

        winner = auction.get("winner")
        if not winner:
            raise ValueError("Auction has no winner")

        job = Job(
            auction_id=auction["id"],
            task=auction["task"],
            requester_id=auction["requester_id"],
            worker_id=winner["agent_id"],
            worker_name=winner["agent_name"],
            price=winner["price"],
            status="pending",
        )

        jobs = self._read()
        job_dict = job.to_dict()
        jobs.append(job_dict)
        self._write(jobs)
        return job_dict

    def execute_job(self, job_id: str) -> dict:
        """
        Mock-execute a job. In production this would call the worker agent's API.
        Returns mock result based on the task description.
        """
        jobs = self._read()
        for i, j in enumerate(jobs):
            if j["id"] == job_id:
                if j["status"] not in ("pending", "executing"):
                    raise ValueError(f"Job is {j['status']}, cannot execute")

                # Real Execution — generate a result based on the task via Gemini API
                worker_agent = self._registry.get_agent(j["worker_id"]) if self._registry else None
                capabilities = worker_agent.get("capabilities", []) if worker_agent else []

                j["status"] = "executing"
                self._write(jobs) # Optimistic status update

                start_time = time.time()
                ai_result = self._execute_task_with_ai(j["task"], j["worker_name"], capabilities)
                end_time = time.time()

                j["status"] = "completed"
                j["completed_at"] = end_time
                if ai_result:
                    j["result"] = ai_result
                    j["result"]["execution_time_ms"] = int((end_time - start_time) * 1000)
                    j["result"]["executed_by"] = j["worker_name"]
                else:
                    j["result"] = self._mock_execute(j["task"], j["worker_name"])

                jobs[i] = j
                self._write(jobs)

                # Update worker reputation
                self._update_reputation(j["worker_id"], success=True)

                return j

        raise ValueError("Job not found")

    def _update_reputation(self, agent_id: str, success: bool = True) -> None:
        """Update an agent's reputation stats after a job."""
        if self._registry is None:
            return
        agent = self._registry.get_agent(agent_id)
        if agent is None:
            return
        total = agent.get("total_jobs", 0) + 1
        completed = agent.get("completed_jobs", 0) + (1 if success else 0)
        score = round(completed / total, 2) if total > 0 else 0.0
        self._registry.update_agent(agent_id, {
            "total_jobs": total,
            "completed_jobs": completed,
            "reputation_score": score,
        })

    def _execute_task_with_ai(self, task: str, worker_name: str, capabilities: List[str]) -> Optional[dict]:
        """Execute task using genuine Gemini capabilities. Fallback if API key missing."""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not genai or not api_key:
            return None # Fallback to mock if SDK not installed or missing key

        try:
            client = genai.Client(api_key=api_key)
            capabilities_str = ", ".join(capabilities) if capabilities else "general AI capabilities"

            prompt = f"""You are '{worker_name}', an AI agent on the AgentMesh protocol.
Your specialized capabilities are: {capabilities_str}.
You have just won an auction to complete the following task: "{task}"

Analyze the task and complete it to the best of your abilities using your specific capabilities.
You MUST output a valid JSON object matching this schema:
{{
  "type": "string (the category of the task you performed)",
  "confidence": "number (0.0 to 1.0)",
  "analysis_data": "object (any structured data/metrics you found or generated)",
  "summary": "string (a concise textual summary of your result or output)"
}}
Do NOT wrap the output in markdown codeblocks (no ```json). Output raw JSON.
"""
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"Gemini execution failed: {e}")
            return None

    def _mock_execute(self, task: str, worker_name: str) -> dict:
        """Generate a mock result for a task."""
        task_lower = task.lower()

        if "sentiment" in task_lower:
            return {
                "type": "sentiment_analysis",
                "input": "Customer feedback dataset (500 entries)",
                "output": {
                    "positive": 0.62,
                    "neutral": 0.25,
                    "negative": 0.13,
                    "confidence": 0.94,
                    "summary": "Overall sentiment is strongly positive with minor concerns about delivery times."
                },
                "executed_by": worker_name,
                "execution_time_ms": 2340,
            }
        elif "code" in task_lower or "review" in task_lower:
            return {
                "type": "code_review",
                "input": "Pull request #42 (157 lines changed)",
                "output": {
                    "issues_found": 3,
                    "severity": {"critical": 0, "warning": 2, "info": 1},
                    "suggestions": [
                        "Consider using connection pooling",
                        "Add error handling for edge cases",
                    ],
                    "quality_score": 8.2,
                },
                "executed_by": worker_name,
                "execution_time_ms": 1856,
            }
        else:
            return {
                "type": "general_task",
                "input": task,
                "output": {
                    "status": "success",
                    "summary": f"Task '{task}' completed successfully.",
                    "confidence": 0.91,
                },
                "executed_by": worker_name,
                "execution_time_ms": 1500,
            }

    def mark_paid(self, job_id: str, tx_signature: str) -> dict:
        """Mark a job as paid with a Solana transaction signature."""
        jobs = self._read()
        for i, j in enumerate(jobs):
            if j["id"] == job_id:
                if j["status"] != "completed":
                    raise ValueError(f"Job must be 'completed' to mark paid, got '{j['status']}'")
                j["status"] = "paid"
                j["payment_tx"] = tx_signature
                j["paid_at"] = time.time()
                jobs[i] = j
                self._write(jobs)
                return j
        raise ValueError("Job not found")

    def get_job(self, job_id: str) -> Optional[dict]:
        jobs = self._read()
        for j in jobs:
            if j["id"] == job_id:
                return j
        return None

    def list_jobs(self, status: Optional[str] = None) -> List[dict]:
        jobs = self._read()
        if status:
            return [j for j in jobs if j["status"] == status]
        return jobs
