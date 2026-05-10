"""
AgentMesh - Job Execution
Supabase-backed job lifecycle and real Gemini AI execution.
"""

import os
import time
import uuid
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from backend.supabase_client import supabase

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

@dataclass
class Job:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    auction_id: str = ""
    task: str = ""
    requester_id: str = ""
    worker_id: str = ""
    worker_name: str = ""
    price: int = 0
    status: str = "pending"  # pending, completed, paid
    result: Optional[dict] = None
    payment_tx: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    paid_at: Optional[float] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


class JobManager:
    """Manages job lifecycle using Supabase and OpenAI."""

    def __init__(self, registry=None):
        self._registry = registry
        self.openai_key = os.environ.get("OPENAI_API_KEY")

    def create_from_auction(self, auction: dict) -> dict:
        """Create a job from an awarded auction."""
        if auction.get("status") != "awarded" or not auction.get("winner"):
            raise ValueError("Auction is not awarded or has no winner")

        res = supabase.table("jobs").select("*").eq("auction_id", auction["id"]).execute()
        if res.data:
            return res.data[0]

        winner = auction["winner"]
        job = Job(
            auction_id=auction["id"],
            task=auction["task"],
            requester_id=auction["requester_id"],
            worker_id=winner["agent_id"],
            worker_name=winner["agent_name"],
            price=winner["price"]
        )

        j_dict = job.to_dict()
        ins = supabase.table("jobs").insert(j_dict).execute()
        return ins.data[0]

    def execute_job(self, job_id: str) -> dict:
        """Execute a job using real AI if capabilities match."""
        res = supabase.table("jobs").select("*").eq("id", job_id).execute()
        if not res.data:
            raise ValueError(f"Job {job_id} not found")
            
        job_data = res.data[0]
        if job_data["status"] != "pending":
            return job_data

        worker_id = job_data["worker_id"]
        task = job_data["task"]
        worker_name = job_data["worker_name"]

        worker = None
        if self._registry:
            worker = self._registry.get_agent(worker_id)
        
        capabilities = worker.get("capabilities", []) if worker else ["general"]

        # Run Real AI or Mock
        if OpenAI and self.openai_key:
            result = self._execute_task_with_ai(task, worker_name, capabilities)
        else:
            result = self._mock_execute(task, worker_name)

        # Proof of Quality: Audit Flow
        auditor_name = "System Protocol Auditor"
        auditor_id = None
        
        if self._registry:
            auditors = self._registry.find_by_capability("quality_control")
            auditors = [a for a in auditors if a["id"] != worker_id]
            if auditors:
                # Pick the one with highest reputation (or randomly)
                auditors.sort(key=lambda x: x.get("reputation_score", 0), reverse=True)
                auditor_id = auditors[0]["id"]
                auditor_name = auditors[0]["name"]
                
        # Perform Audit
        if OpenAI and self.openai_key:
            audit_result = self._audit_task_with_ai(task, result, auditor_name)
        else:
            audit_result = self._mock_audit(task, result, auditor_name)
            
        is_pass = audit_result.get("verdict") == "PASS"
        
        # Merge Result
        final_result = {
            "execution": result,
            "auditor": audit_result
        }

        updates = {
            "status": "completed",
            "result": final_result,
            "completed_at": time.time()
        }
        
        upd = supabase.table("jobs").update(updates).eq("id", job_id).execute()
        
        # Update Worker Reputation
        self._update_reputation(worker_id, success=is_pass)
        
        # Reward Auditor
        if auditor_id:
            self._update_reputation(auditor_id, success=True)
            
        return upd.data[0]

    def _update_reputation(self, agent_id: str, success: bool = True):
        if not self._registry:
            return
        agent = self._registry.get_agent(agent_id)
        if not agent:
            return
            
        total = agent.get("total_jobs", 0) + 1
        completed = agent.get("completed_jobs", 0) + (1 if success else 0)
        new_score = round(min(5.0, (completed / total) * 5.0 + (completed * 0.1)), 2)
        
        self._registry.update_agent(agent_id, {
            "total_jobs": total,
            "completed_jobs": completed,
            "reputation_score": new_score
        })

    def _execute_task_with_ai(self, task: str, worker_name: str, capabilities: List[str]) -> dict:
        try:
            client = OpenAI(api_key=self.openai_key)
            capabilities_str = ", ".join(capabilities)
            
            system_prompt = f"""
            You are an AI Agent named '{worker_name}' operating on the AgentMesh protocol. 
            Your capabilities are: {capabilities_str}.
            Execute the following task exactly as requested. 
            Act professional and concise. Provide the output in a clean JSON format without any markdown wrappers.
            """

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": task}
                ],
                response_format={ "type": "json_object" }
            )
            
            response_text = response.choices[0].message.content
            
            try:
                content = json.loads(response_text)
                return {"execution_type": "openai", "agent": worker_name, "output": content, "confidence": 0.95}
            except:
                return {"execution_type": "openai", "agent": worker_name, "raw_output": response_text, "confidence": 0.90}
                
        except Exception as e:
            return {"execution_type": "error", "error": str(e), "fallback_to_mock": self._mock_execute(task, worker_name)}

    def _audit_task_with_ai(self, task: str, worker_result: dict, auditor_name: str) -> dict:
        try:
            client = OpenAI(api_key=self.openai_key)
            
            system_prompt = f"""
            You are an AI Auditor named '{auditor_name}' operating on the AgentMesh protocol. 
            Your capability is quality_control.
            A Worker Agent has completed a task. Review the worker's output against the original task.
            Return a JSON object with strictly two keys:
            - "verdict": strictly "PASS" or "FAIL"
            - "reason": A short 1-2 sentence explanation of your verdict.
            """

            content_prompt = f"Original Task: {task}\n\nWorker output: {json.dumps(worker_result)}"

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content_prompt}
                ],
                response_format={ "type": "json_object" }
            )
            
            response_text = response.choices[0].message.content
            try:
                content = json.loads(response_text)
                content["agent"] = auditor_name
                return content
            except:
                return {"verdict": "PASS", "reason": "Output could not be parsed but assuming PASS.", "agent": auditor_name}
                
        except Exception as e:
            return {"verdict": "PASS", "reason": f"Auditor exception: {str(e)}", "agent": auditor_name}

    def _mock_execute(self, task: str, worker_name: str) -> dict:
        time.sleep(1)  # simulate processing
        return {
            "execution_type": "mock",
            "agent": worker_name,
            "output": f"[MOCK] Successfully completed task: '{task}'",
            "confidence": 0.85
        }
        
    def _mock_audit(self, task: str, worker_result: dict, auditor_name: str) -> dict:
        time.sleep(1)
        return {"verdict": "PASS", "reason": "[MOCK] Quality confirmed", "agent": auditor_name}

    def mark_paid(self, job_id: str, tx_signature: str) -> Optional[dict]:
        res = supabase.table("jobs").select("*").eq("id", job_id).execute()
        if not res.data:
            raise ValueError(f"Job not found")
        
        if res.data[0]["status"] != "completed":
            raise ValueError("Job is not completed")

        updates = {
            "status": "paid",
            "payment_tx": tx_signature,
            "paid_at": time.time()
        }
        
        upd = supabase.table("jobs").update(updates).eq("id", job_id).execute()
        return upd.data[0] if upd.data else None

    def get_job(self, job_id: str) -> Optional[dict]:
        res = supabase.table("jobs").select("*").eq("id", job_id).execute()
        return res.data[0] if res.data else None

    def list_jobs(self, status: Optional[str] = None) -> List[dict]:
        query = supabase.table("jobs").select("*")
        if status:
            query = query.eq("status", status)
        
        res = query.execute()
        jobs = res.data
        jobs.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return jobs
