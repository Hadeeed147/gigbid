"""Job Analyst: structured JobSpec from an untrusted job post. No MCP access."""
from agent.handoffs import JobSpec
from agent.nodes._runtime import job_text, node, untrusted
from common.llm import chat
from common.prompts import load_prompt


@node("analyst")
async def analyst(state: dict) -> dict:
    job = state["job"]
    sys = load_prompt("analyst", untrusted=load_prompt("_untrusted"))
    spec = chat("analyst", [{"role": "system", "content": sys},
                            {"role": "user", "content": untrusted("job_post", job_text(job))}], JobSpec)
    if job.get("screening_questions") and not spec.screening_questions:
        spec.screening_questions = list(job["screening_questions"])
    return {"job_spec": spec.model_dump()}
