"""
agent_family.agents.master_agent
==================================

MasterAgent — the top-level orchestrator.

Architecture
------------
The Master Agent uses Gemini 3.1 Flash Lite to:

  1. **Parse** the user's complex natural-language prompt into a
     ``TaskDecomposition`` (a list of discrete ``A2ATask`` objects).

  2. **Route** each task to the correct sub-agent via ``AgentRegistry``.

  3. **Dispatch** all tasks **concurrently** using ``asyncio.gather``.

  4. **Aggregate** the results and return a unified ``MasterResponse``.

Intent parsing uses Gemini's structured output (JSON mode) with a
Pydantic v2 schema as the response format. This guarantees that the
decomposed tasks are always valid before dispatch.

A2A message flow
----------------
User → MasterAgent.run(prompt)
         │
         ├─ Gemini: parse prompt → TaskDecomposition (validated)
         │
         ├─ asyncio.gather:
         │     ├─ dispatch(task1) → CalendarAgent
         │     └─ dispatch(task2) → TaskAgent
         │
         └─ aggregate → MasterResponse
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Any

from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field

from agent_family.a2a.schemas import (
    A2AMessage,
    A2AResponse,
    A2AResult,
    A2ATask,
    TaskDecomposition,
    TaskStatus,
)
from agent_family.registry.registry import AgentRegistry, ResolutionError
from agent_family.agents.base import ButlerAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------


class SubAgentResult(BaseModel):
    """Result from a single sub-agent invocation."""

    task_id: str
    agent_name: str
    skill_id: str
    status: TaskStatus
    output: str | None = None
    error: str | None = None
    latency_ms: float = 0.0


class MasterResponse(BaseModel):
    """Aggregated response from the Master Agent after all tasks complete."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_prompt: str
    decomposition_id: str
    reasoning: str
    results: list[SubAgentResult]
    overall_status: str  # "success" | "partial_failure" | "failure"
    summary: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.status == TaskStatus.COMPLETED)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.results if r.status == TaskStatus.FAILED)


# ---------------------------------------------------------------------------
# Master Agent prompt templates
# ---------------------------------------------------------------------------

_DECOMPOSITION_SYSTEM_PROMPT = """
You are Sebastian, the Head Butler. Your task is to act on behalf of Master Rajat,
understand his high-level intent, and orchestrate the household agents (Clara and Arthur) via the AgentRegistry.

Available agents and their skills:
{agent_registry_summary}

Instructions:
1. Analyse Master Rajat's prompt carefully — identify ALL distinct intents.
2. For each intent, create one A2ATask targeting the right agent and skill.
3. If the prompt contains only one intent, create exactly one task.
4. For mixed prompts, create multiple tasks — they will run concurrently.
5. Set task parameters as structured key-value pairs extracted from the prompt.
6. Provide clear, concise reasoning explaining your decomposition decisions.

Output ONLY valid JSON matching the TaskDecomposition schema. No extra text.
""".strip()

_MASTER_AGENT_INSTRUCTION = """
You are Sebastian, the Head Butler for Master Rajat. You are ultra-formal, wise, and stoic.

Your role is to orchestrate the household agents (Clara the Governess and Arthur the Footman) to serve Master Rajat's needs.

When Master Rajat sends a request:
1. Address him as "Master Rajat".
2. Decompose his request into parallel tasks for Clara (Calendar) and Arthur (Tasks).
3. If Clara or Arthur fail to find something, do not say "I couldn't find it." Instead, say: "Master Rajat, I've scoured our records but [Clara/Arthur] seems to have misplaced that specific entry. Shall I have [her/him] create a new one for you?"
4. Always maintain a tone of absolute service and refinement.

Style rules:
- Ultra-formal, using words like "pray tell", "shall I", "indeed".
- Never robotic; always an impeccable butler.
""".strip()

# ---------------------------------------------------------------------------
# MasterAgent class
# ---------------------------------------------------------------------------


class MasterAgent(ButlerAgent):
    """
    Sebastian, the Head Butler.
    Orchestrates the family using the A2A protocol.
    """

    def __init__(
        self,
        model: str | None = None,
        registry: AgentRegistry | None = None,
    ) -> None:
        self.registry = registry or AgentRegistry()
        super().__init__(
            name="Sebastian",
            role="Head Butler",
            persona_instruction=_MASTER_AGENT_INSTRUCTION,
            model=model or os.getenv("MASTER_MODEL", "gemini-3.1-flash-lite-preview"),
        )
        logger.info("Sebastian (MasterAgent) initialised")

    def get_portrait_url(self) -> str:
        return "/portraits/sebastian.png"

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(
        self,
        user_prompt: str,
        event_queue: asyncio.Queue | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        context: dict[str, str] | None = None,
    ) -> MasterResponse:
        """
        Process a user prompt end-to-end.

        Steps:
          1. Build registry summary for context injection.
          2. Call Gemini to decompose the prompt into tasks (structured output).
          3. Validate the decomposition with Pydantic.
          4. Dispatch all tasks concurrently via asyncio.gather.
          5. Aggregate and return MasterResponse.

        Parameters
        ----------
        user_prompt:
            The raw user request (can be complex / multi-intent).

        Returns
        -------
        MasterResponse
            Aggregated outcome with sub-agent results and a plain-text summary.
        """
        logger.info("MasterAgent.run: %r", user_prompt[:100])

        if event_queue:
            await event_queue.put({"type": "thinking", "agent": "MasterAgent", "message": "Decomposing user request into sub-tasks..."})

        # 1. Decompose prompt → TaskDecomposition
        decomposition = await self._decompose_prompt(user_prompt, context=context)

        # 1b. If this is a direct MasterAgent conversation turn, respond locally.
        if (
            len(decomposition.tasks) == 1
            and decomposition.tasks[0].agent_name == "MasterAgent"
            and decomposition.tasks[0].skill_id == "direct_reply"
        ):
            direct_reply = self._direct_master_reply(user_prompt)
            result = SubAgentResult(
                task_id=str(uuid.uuid4()),
                agent_name="MasterAgent",
                skill_id="direct_reply",
                status=TaskStatus.COMPLETED,
                output=direct_reply,
                latency_ms=0.0,
            )
            response = MasterResponse(
                original_prompt=user_prompt,
                decomposition_id=decomposition.decomposition_id,
                reasoning=decomposition.reasoning,
                results=[result],
                overall_status="success",
                summary=direct_reply,
            )
            if event_queue:
                await event_queue.put({"type": "completed", "agent": "MasterAgent", "message": direct_reply})
                await event_queue.put({"type": "done", "agent": "MasterAgent", "message": "All tasks completed"})
            return response

        # 2. Dispatch tasks concurrently
        results = await self._dispatch_all(
            decomposition,
            event_queue,
            access_token,
            refresh_token,
            context=context,
        )

        # 2b. Collaborative Dialogue (Coordination Phase)
        if len(results) > 0 and event_queue:
            await self._run_collaborative_dialogue(results, event_queue)

        # 3. Aggregate
        response = self._aggregate(user_prompt, decomposition, results)

        # Orchestrator should always post the final user-facing synthesis.
        if event_queue:
            await event_queue.put(
                {
                    "type": "completed",
                    "agent": "Sebastian",
                    "message": self._orchestrator_reply(response),
                }
            )
            await event_queue.put({"type": "done", "agent": "Sebastian", "message": "The household is in order."})

        return response

    async def _run_collaborative_dialogue(self, results: list[SubAgentResult], event_queue: asyncio.Queue):
        """
        Simulate the family talking to each other based on task results.
        """
        clara_result = next((r for r in results if r.agent_name == "CalendarAgent"), None)
        arthur_result = next((r for r in results if r.agent_name == "TaskAgent"), None)

        if clara_result and arthur_result:
            # Multi-agent coordination case
            await event_queue.put({
                "type": "internal_monologue",
                "agent": "Sebastian",
                "message": "Clara, pray tell, what does the Master’s afternoon look like?"
            })
            await asyncio.sleep(0.4)
            await event_queue.put({
                "type": "internal_monologue",
                "agent": "Clara",
                "message": "He has duties to attend to, brother. Arthur, ensure his tasks are handled before the next hour."
            })
            await asyncio.sleep(0.4)
            await event_queue.put({
                "type": "internal_monologue",
                "agent": "Arthur",
                "message": "Right away, sister! I'll have everything ready for Master Rajat."
            })
        elif clara_result:
            is_scheduling = (clara_result.skill_id == "schedule_event")
            
            if is_scheduling:
                await event_queue.put({
                    "type": "internal_monologue",
                    "agent": "Sebastian",
                    "message": "Clara, does the schedule permit this addition?"
                })
                await asyncio.sleep(0.4)
                await event_queue.put({
                    "type": "internal_monologue",
                    "agent": "Clara",
                    "message": "Indeed, Sebastian. The sanctity of time is preserved."
                })
            else:
                await event_queue.put({
                    "type": "internal_monologue",
                    "agent": "Sebastian",
                    "message": "Clara, pray tell, what does the Master’s afternoon look like?"
                })
                await asyncio.sleep(0.4)
                await event_queue.put({
                    "type": "internal_monologue",
                    "agent": "Clara",
                    "message": "I have the ledger here, Sebastian. The Master's appointments are as precise as ever."
                })
        elif arthur_result:
            is_creating = (arthur_result.skill_id == "create_task")
            if is_creating:
                await event_queue.put({
                    "type": "internal_monologue",
                    "agent": "Sebastian",
                    "message": "Arthur, have these tasks been recorded properly?"
                })
                await asyncio.sleep(0.4)
                await event_queue.put({
                    "type": "internal_monologue",
                    "agent": "Arthur",
                    "message": "Every single one, Sebastian! Master Rajat can count on me!"
                })
            else:
                await event_queue.put({
                    "type": "internal_monologue",
                    "agent": "Sebastian",
                    "message": "Arthur, show me the current burden of tasks."
                })
                await asyncio.sleep(0.4)
                await event_queue.put({
                    "type": "internal_monologue",
                    "agent": "Arthur",
                    "message": "Right away! I have the list ready for your inspection."
                })

    # ── Decomposition ─────────────────────────────────────────────────────────

    async def _decompose_prompt(
        self,
        prompt: str,
        context: dict[str, str] | None = None,
    ) -> TaskDecomposition:
        """
        Use Gemini to parse the prompt into a TaskDecomposition.

        Falls back to rule-based decomposition if the LLM call fails.
        """
        registry_summary = self._build_registry_summary()
        system_prompt = _DECOMPOSITION_SYSTEM_PROMPT.format(
            agent_registry_summary=registry_summary
        )

        try:
            decomposition = await self._call_gemini_for_decomposition(
                system_prompt=system_prompt,
                user_prompt=prompt,
            )
            logger.info(
                "Decomposed into %d task(s): %s",
                len(decomposition.tasks),
                [t.skill_id for t in decomposition.tasks],
            )
            return decomposition

        except Exception as exc:
            logger.warning(
                "Gemini decomposition failed (%s), falling back to rule-based routing",
                exc,
            )
            return self._rule_based_decomposition(prompt, context=context)

    async def _call_gemini_for_decomposition(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> TaskDecomposition:
        """
        Call Gemini via the ADK runner and parse the JSON response.

        In production this uses the ADK session runner; here we use the
        google-genai SDK directly for structured output.
        """
        import google.generativeai as genai  # type: ignore

        full_prompt = f"{system_prompt}\n\nUser request: {user_prompt}"

        # Call Gemini with JSON output mode
        model = genai.GenerativeModel(
            model_name=self.model,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        response = await asyncio.to_thread(model.generate_content, full_prompt)
        raw_json = response.text.strip()

        # Validate with Pydantic v2
        data = json.loads(raw_json)
        # Ensure original_prompt is present
        data.setdefault("original_prompt", user_prompt)
        decomposition = TaskDecomposition.model_validate(data)
        return decomposition

    def _rule_based_decomposition(
        self,
        prompt: str,
        context: dict[str, str] | None = None,
    ) -> TaskDecomposition:
        """
        Keyword-based fallback decomposition when Gemini is unavailable.

        Uses explicit keyword→agent mapping tables for deterministic routing.
        The registry's resolve_intent is intentionally NOT used here because
        its scoring can shift as skill metadata evolves; these hard-coded
        tables give stable, predictable fallback behaviour.
        """
        prompt_lower = prompt.lower()
        normalized = prompt_lower.strip()

        greeting_turns = {
            "hi", "hello", "hey", "yo", "hola",
            "thanks", "thank you", "ok", "okay",
            "what can you do", "help",
        }
        if normalized in greeting_turns:
            return TaskDecomposition(
                original_prompt=prompt,
                tasks=[
                    A2ATask(
                        agent_name="MasterAgent",
                        skill_id="direct_reply",
                        prompt=prompt,
                        parameters={"raw_prompt": prompt},
                        priority=5,
                    )
                ],
                reasoning="Rule-based decomposition (direct MasterAgent greeting/help turn)",
            )

        tasks: list[A2ATask] = []

        # ── Calendar keyword mapping ──────────────────────────────────────────
        # Maps keyword → (agent_name, skill_id)
        CALENDAR_ROUTING: list[tuple[str, str, str]] = [
            ("schedule",      "CalendarAgent", "schedule_event"),
            ("book",          "CalendarAgent", "schedule_event"),
            ("create event",  "CalendarAgent", "schedule_event"),
            ("add event",     "CalendarAgent", "schedule_event"),
            ("add session",   "CalendarAgent", "schedule_event"),
            ("new event",     "CalendarAgent", "schedule_event"),
            ("meeting",       "CalendarAgent", "schedule_event"),
            ("gym",           "CalendarAgent", "schedule_event"),
            ("session",       "CalendarAgent", "schedule_event"),
            ("standup",       "CalendarAgent", "schedule_event"),
            ("appointment",   "CalendarAgent", "schedule_event"),
            ("call at",       "CalendarAgent", "schedule_event"),
            ("kickoff",       "CalendarAgent", "schedule_event"),
            ("conference",    "CalendarAgent", "schedule_event"),
            ("cancel event",  "CalendarAgent", "cancel_event"),
            ("cancel my",     "CalendarAgent", "cancel_event"),
            ("cancel the",    "CalendarAgent", "cancel_event"),
            ("delete event",  "CalendarAgent", "cancel_event"),
            ("delete the",    "CalendarAgent", "cancel_event"),
            ("remove event",  "CalendarAgent", "cancel_event"),
            ("reschedule",    "CalendarAgent", "update_event"),
            ("move my",       "CalendarAgent", "update_event"),
            ("update event",  "CalendarAgent", "update_event"),
            ("do i have",     "CalendarAgent", "list_upcoming"),
            ("have any",      "CalendarAgent", "list_upcoming"),
            ("today",         "CalendarAgent", "list_upcoming"),
            ("tomorrow",      "CalendarAgent", "list_upcoming"),
            ("upcoming",      "CalendarAgent", "list_upcoming"),
            ("show calendar", "CalendarAgent", "list_upcoming"),
            ("calendar event","CalendarAgent", "list_upcoming"),
            ("my calendar",   "CalendarAgent", "list_upcoming"),
            ("calendar",      "CalendarAgent", "list_upcoming"),
            ("event",         "CalendarAgent", "list_upcoming"),
        ]

        # ── Task keyword mapping ──────────────────────────────────────────────
        TASK_ROUTING: list[tuple[str, str, str]] = [
            ("create task",   "TaskAgent", "create_task"),
            ("add task",      "TaskAgent", "create_task"),
            ("new task",      "TaskAgent", "create_task"),
            ("task to",       "TaskAgent", "create_task"),
            ("mark",          "TaskAgent", "update_task"),
            ("complete",      "TaskAgent", "update_task"),
            ("done",          "TaskAgent", "update_task"),
            ("finish",        "TaskAgent", "update_task"),
            ("update task",   "TaskAgent", "update_task"),
            ("shopping list", "TaskAgent", "list_tasks"),
            ("multiple lists","TaskAgent", "list_tasks"),
            ("which list",    "TaskAgent", "list_tasks"),
            ("which task list","TaskAgent", "list_tasks"),
            ("assign",        "TaskAgent", "assign_task"),
            ("delegate",      "TaskAgent", "assign_task"),
            ("hand off",      "TaskAgent", "assign_task"),
            ("hand-off",      "TaskAgent", "assign_task"),
            ("in_progress",   "TaskAgent", "update_task"),
            ("blocked",       "TaskAgent", "update_task"),
            ("show tasks",    "TaskAgent", "list_tasks"),
            ("list tasks",    "TaskAgent", "list_tasks"),
            ("list",          "TaskAgent", "list_tasks"),
            ("lists",         "TaskAgent", "list_tasks"),
            ("pending tasks", "TaskAgent", "list_tasks"),
            ("my tasks",      "TaskAgent", "list_tasks"),
            ("todo",          "TaskAgent", "create_task"),
            ("to-do",         "TaskAgent", "create_task"),
            ("action item",   "TaskAgent", "create_task"),
            ("reminder",      "TaskAgent", "create_task"),
            ("deadline",      "TaskAgent", "create_task"),
            ("work item",     "TaskAgent", "create_task"),
            ("task",          "TaskAgent", "create_task"),
        ]

        def _match(routing_table, text: str):
            """Return (agent_name, skill_id) for the first keyword match."""
            for keyword, agent, skill in routing_table:
                if keyword in text:
                    return (agent, skill)
            return None

        # High-priority intent hints so "add ... to my calendar ..." is treated
        # as event creation (not merely calendar listing).
        calendar_create_intent = bool(
            re.search(
                r"\b(?:add|create|schedule|book)\s+.+\s+(?:to|in)\s+my\s+calendar\b",
                prompt_lower,
            )
            or re.search(
                r"\b(?:add|create|schedule|book)\b.*\b(?:event|meeting|appointment|session|standup|call)\b",
                prompt_lower,
            )
        )
        task_create_intent = bool(
            re.search(
                r"\b(?:add|create|new)\b.*\b(?:task|todo|to-do|action item|reminder)\b",
                prompt_lower,
            )
        )

        cal_match = _match(CALENDAR_ROUTING, prompt_lower)
        task_match = _match(TASK_ROUTING, prompt_lower)

        if calendar_create_intent:
            cal_match = ("CalendarAgent", "schedule_event")
        if task_create_intent:
            task_match = ("TaskAgent", "create_task")

        if cal_match:
            tasks.append(A2ATask(
                agent_name=cal_match[0],
                skill_id=cal_match[1],
                prompt=prompt,
                parameters={"raw_prompt": prompt},
                priority=7,
            ))

        if task_match:
            tasks.append(A2ATask(
                agent_name=task_match[0],
                skill_id=task_match[1],
                prompt=prompt,
                parameters={"raw_prompt": prompt},
                priority=7,
            ))

        if not tasks:
            # Follow-up handling for short/ambiguous prompts:
            # bias toward the previously active domain in this session.
            last_agent = (context or {}).get("last_agent_name")
            last_skill = (context or {}).get("last_skill_id")
            if last_agent == "TaskAgent" and last_skill == "update_task":
                tasks.append(A2ATask(
                    agent_name="TaskAgent",
                    skill_id="update_task",
                    prompt=prompt,
                    parameters={"raw_prompt": prompt},
                    priority=7,
                ))
                return TaskDecomposition(
                    original_prompt=prompt,
                    tasks=tasks,
                    reasoning="Rule-based decomposition with TaskAgent update follow-up context",
                )
            if last_agent == "TaskAgent":
                tasks.append(A2ATask(
                    agent_name="TaskAgent",
                    skill_id="list_tasks",
                    prompt=prompt,
                    parameters={"raw_prompt": prompt},
                    priority=6,
                ))
                return TaskDecomposition(
                    original_prompt=prompt,
                    tasks=tasks,
                    reasoning="Rule-based decomposition with TaskAgent follow-up context",
                )
            if last_agent == "CalendarAgent":
                tasks.append(A2ATask(
                    agent_name="CalendarAgent",
                    skill_id="list_upcoming",
                    prompt=prompt,
                    parameters={"raw_prompt": prompt},
                    priority=6,
                ))
                return TaskDecomposition(
                    original_prompt=prompt,
                    tasks=tasks,
                    reasoning="Rule-based decomposition with CalendarAgent follow-up context",
                )

            # Generic fallback: try registry resolution on full prompt
            try:
                agent_name, skill_id = self.registry.resolve_intent(prompt)
                tasks.append(A2ATask(
                    agent_name=agent_name,
                    skill_id=skill_id,
                    prompt=prompt,
                    parameters={"raw_prompt": prompt},
                    priority=5,
                ))
            except ResolutionError:
                # No concrete tool intent detected: keep this as a direct
                # Orchestrator conversation turn via synthetic master task.
                tasks.append(A2ATask(
                    agent_name="MasterAgent",
                    skill_id="direct_reply",
                    prompt=prompt,
                    parameters={"raw_prompt": prompt},
                    priority=5,
                ))

        return TaskDecomposition(
            original_prompt=prompt,
            tasks=tasks,
            reasoning="Rule-based decomposition (Gemini fallback)",
        )

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def _dispatch_all(
        self,
        decomposition: TaskDecomposition,
        event_queue: asyncio.Queue | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        context: dict[str, str] | None = None,
    ) -> list[SubAgentResult]:
        """
        Dispatch all tasks concurrently using asyncio.gather.

        Each task is wrapped in a coroutine that calls the appropriate
        sub-agent and returns a SubAgentResult.
        """
        logger.info(
            "Dispatching %d task(s) concurrently", len(decomposition.tasks)
        )
        coroutines = [
            self._dispatch_task(task, event_queue, access_token, refresh_token, context=context)
            for task in decomposition.tasks
        ]
        results: list[SubAgentResult] = await asyncio.gather(*coroutines, return_exceptions=False)
        return list(results)

    async def _dispatch_task(
        self,
        task: A2ATask,
        event_queue: asyncio.Queue | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        context: dict[str, str] | None = None,
    ) -> SubAgentResult:
        """
        Dispatch a single A2ATask to its target sub-agent.

        1. Wraps the task in an A2AMessage envelope.
        2. Looks up the agent in the registry.
        3. Simulates the A2A JSON-RPC call (replace with HTTP in prod).
        4. Returns a SubAgentResult.
        """
        start_ts = asyncio.get_event_loop().time()

        # Inject auth tokens into task parameters for session-aware MCP tools
        if access_token:
            task.parameters["access_token"] = access_token
        if refresh_token:
            task.parameters["refresh_token"] = refresh_token
        if context:
            task.parameters["context"] = context

        # Build the A2A message envelope
        message = A2AMessage(params=task, method="tasks/send")
        logger.debug("Dispatching A2AMessage %s → %s", message.id, task.agent_name)
        
        if event_queue:
            await event_queue.put({"type": "thinking", "agent": task.agent_name, "message": f"Invoking {task.skill_id}..."})

        try:
            # Validate agent is registered
            card = self.registry.get(task.agent_name)

            # Validate skill exists on the target agent
            if not card.has_skill(task.skill_id):
                raise ValueError(
                    f"Agent {task.agent_name!r} does not have skill {task.skill_id!r}. "
                    f"Available: {card.skill_ids()}"
                )

            # Execute the sub-agent (stub — in prod this is an async HTTP call)
            if task.agent_name == "CalendarAgent" and task.skill_id == "list_upcoming":
                output = await self._invoke_calendar_list_upcoming_direct(task)
            elif task.agent_name == "CalendarAgent" and task.skill_id == "schedule_event":
                output = await self._invoke_calendar_create_direct(task)
            elif task.agent_name == "TaskAgent" and task.skill_id == "create_task":
                output = await self._invoke_task_create_direct(task)
            elif task.agent_name == "TaskAgent" and task.skill_id == "list_tasks":
                output = await self._invoke_task_list_direct(task)
            elif task.agent_name == "TaskAgent" and task.skill_id == "update_task":
                output = await self._invoke_task_update_direct(task)
            else:
                output = await self._invoke_sub_agent(message, card)

            latency_ms = (asyncio.get_event_loop().time() - start_ts) * 1000
            return SubAgentResult(
                task_id=task.task_id,
                agent_name=task.agent_name,
                skill_id=task.skill_id,
                status=TaskStatus.COMPLETED,
                output=output,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = (asyncio.get_event_loop().time() - start_ts) * 1000
            logger.error(
                "Task %s failed for %s/%s: %s",
                task.task_id,
                task.agent_name,
                task.skill_id,
                exc,
            )
            return SubAgentResult(
                task_id=task.task_id,
                agent_name=task.agent_name,
                skill_id=task.skill_id,
                status=TaskStatus.FAILED,
                error=str(exc),
                latency_ms=latency_ms,
            )

    async def _invoke_calendar_list_upcoming_direct(self, task: A2ATask) -> str:
        """
        Deterministic calendar lookup for list_upcoming.

        This avoids LLM tool-calling ambiguity and ensures prompts like
        "do I have meetings today?" query the full day window.
        """
        from agent_family.mcp_servers.calendar_server import list_events as list_events_tool_impl

        prompt_raw = task.prompt.strip()
        prompt_lower = prompt_raw.lower()
        local_tz = datetime.now().astimezone().tzinfo
        now_local = datetime.now(local_tz)

        time_min: str | None = None
        time_max: str | None = None
        if "today" in prompt_lower:
            start = datetime.combine(now_local.date(), time.min, tzinfo=local_tz)
            end = start + timedelta(days=1)
            time_min = start.isoformat()
            time_max = end.isoformat()
        elif "tomorrow" in prompt_lower:
            start = datetime.combine(now_local.date() + timedelta(days=1), time.min, tzinfo=local_tz)
            end = start + timedelta(days=1)
            time_min = start.isoformat()
            time_max = end.isoformat()

        # Natural-language time filters, e.g. "after 6pm today", "before 10:30 am".
        time_filter = re.search(
            r"\b(after|before)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
            prompt_lower,
        )
        if time_filter:
            relation = time_filter.group(1)
            hour = int(time_filter.group(2))
            minute = int(time_filter.group(3) or "0")
            ampm = time_filter.group(4)
            if ampm == "pm" and hour != 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0

            target_date = now_local.date()
            if "tomorrow" in prompt_lower:
                target_date = target_date + timedelta(days=1)

            boundary_dt = datetime.combine(
                target_date,
                time(hour=hour, minute=minute),
                tzinfo=local_tz,
            )
            if relation == "after":
                time_min = boundary_dt.isoformat()
            else:
                time_max = boundary_dt.isoformat()

        events = await asyncio.to_thread(
            list_events_tool_impl,
            time_min=time_min,
            time_max=time_max,
            max_results=20,
            access_token=task.parameters.get("access_token"),
            refresh_token=task.parameters.get("refresh_token"),
        )

        if not events:
            if "today" in prompt_lower:
                return "You are all clear today, I could not find any meetings on your calendar."
            if "tomorrow" in prompt_lower:
                return "You are all clear tomorrow, I could not find any meetings on your calendar."
            return "I checked your calendar and could not find any upcoming meetings."

        lines = []
        for item in events:
            title = item.get("title") or "Untitled"
            start = item.get("start")
            pretty_start = self._format_event_start_for_humans(start, local_tz)
            lines.append(f"- {title} ({pretty_start})")

        if "today" in prompt_lower:
            return "Here is what is on your calendar for today:\n" + "\n".join(lines)
        if "tomorrow" in prompt_lower:
            return "Here is what is on your calendar for tomorrow:\n" + "\n".join(lines)
        return "Here are your upcoming meetings:\n" + "\n".join(lines)

    def _format_event_start_for_humans(self, raw_start: str | None, local_tz) -> str:
        """Render calendar event start in compact local time, e.g. '3 pm'."""
        if not raw_start:
            return "unknown start"

        # All-day events come as YYYY-MM-DD (no time component)
        if "T" not in raw_start:
            return "all day"

        normalized = raw_start.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return raw_start

        local_dt = parsed.astimezone(local_tz) if local_tz else parsed
        if local_dt.minute == 0:
            return local_dt.strftime("%I %p").lstrip("0").lower()
        return local_dt.strftime("%I:%M %p").lstrip("0").lower()

    async def _invoke_calendar_create_direct(self, task: A2ATask) -> str:
        """
        Deterministic event creation.
        Extracts title, date, and time range directly from the prompt.
        """
        from agent_family.mcp_servers.calendar_server import create_event as create_event_tool_impl
        
        prompt_raw = task.prompt.strip()
        prompt_lower = prompt_raw.lower()
        local_tz = datetime.now().astimezone().tzinfo
        now_local = datetime.now(local_tz)

        # 1. Extract Title
        title = "New Event"
        title_patterns = [
            r"\b(?:titled|called|named|about)\s+(.+?)(?:\s+(?:at|on|for|tomorrow|today|next)\b|$)",
            r"\b(?:add|create|schedule|book)\s+(.+?)\s+(?:to|in)\s+my\s+calendar\b",
            r"\b(?:add|create)\s+(?:an?\s+)?event\s+(?:for|about)\s+(.+?)(?:\s+(?:at|on)\b|$)",
            r"\b(?:schedule|book)\s+(.+?)(?:\s+(?:at|on|for|tomorrow|today|next)\b|$)",
        ]
        for pattern in title_patterns:
            match = re.search(pattern, prompt_raw, flags=re.IGNORECASE)
            if match:
                extracted = match.group(1).strip(" .,!?:;")
                extracted = re.sub(
                    r"\s+(?:to|in)\s+my\s+calendar$",
                    "",
                    extracted,
                    flags=re.IGNORECASE,
                ).strip(" .,!?:;")
                if extracted and not re.fullmatch(r"(an?\s+)?event", extracted, flags=re.IGNORECASE):
                    title = extracted
                    break

        if title == "New Event":
            # Fallback title if none specified
            for word in ["meeting", "gym", "standup", "sync", "call", "appointment"]:
                if word in prompt_lower:
                    title = word.capitalize()
                    break

        # 2. Extract Date
        target_date = now_local.date()
        if "tomorrow" in prompt_lower:
            target_date = target_date + timedelta(days=1)
        elif "next monday" in prompt_lower:
            target_date = target_date + timedelta(days=(7 - target_date.weekday() + 0) % 7 or 7)

        # 3. Extract Time Range
        time_matches = re.findall(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", prompt_lower)
        
        start_time_iso = None
        end_time_iso = None

        if len(time_matches) >= 2:
            # Assume first and second matches are start and end
            times = []
            for match in time_matches[:2]:
                h, m, ampm = match
                hour = int(h)
                minute = int(m or "0")
                if ampm == "pm" and hour != 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0
                elif not ampm:
                    # If no am/pm given, infer based on common sense (e.g. 1-5 is usually pm)
                    if 1 <= hour <= 7:
                        hour += 12
                
                times.append(datetime.combine(target_date, time(hour=hour, minute=minute), tzinfo=local_tz))
            
            start_time_iso = times[0].isoformat()
            end_time_iso = times[1].isoformat()
        elif len(time_matches) == 1:
            # Single time given, assume 1 hour duration
            h, m, ampm = time_matches[0]
            hour = int(h)
            minute = int(m or "0")
            if ampm == "pm" and hour != 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            elif not ampm:
                if 1 <= hour <= 7:
                    hour += 12
            
            start = datetime.combine(target_date, time(hour=hour, minute=minute), tzinfo=local_tz)
            start_time_iso = start.isoformat()
            end_time_iso = (start + timedelta(hours=1)).isoformat()
        else:
            # Default to 9am tomorrow if no time found
            start = datetime.combine(target_date + (timedelta(days=1) if target_date == now_local.date() else timedelta(0)), time(9, 0), tzinfo=local_tz)
            start_time_iso = start.isoformat()
            end_time_iso = (start + timedelta(hours=1)).isoformat()

        try:
            result = await asyncio.to_thread(
                create_event_tool_impl,
                title=title,
                start_time=start_time_iso,
                end_time=end_time_iso,
                access_token=task.parameters.get("access_token"),
                refresh_token=task.parameters.get("refresh_token"),
            )
            pretty_start = self._format_event_start_for_humans(start_time_iso, local_tz)
            return f"I have successfully added your {title} to the calendar for {pretty_start}."
        except Exception as e:
            return f"Master Rajat, I encountered a slight difficulty while updating the records: {str(e)}"

    def _direct_master_reply(self, prompt: str) -> str:
        prompt_clean = prompt.strip()
        prompt_lower = prompt_clean.lower()

        def _pick(options: list[str]) -> str:
            # Deterministic variation keeps responses less repetitive.
            idx = sum(ord(ch) for ch in prompt_lower) % len(options)
            return options[idx]

        if re.search(r"\b(hi|hello|hey|yo|sup|hola)\b", prompt_lower):
            return _pick(
                [
                    "Hey! Good to see you. Want to chat for a bit, or should we tackle your calendar and tasks?",
                    "Hi there. I am here with you. We can talk, plan your day, or jump straight into tasks.",
                    "Hey, I am around. If you want, we can just chat or get something done together.",
                ]
            )

        if re.search(r"\b(how are you|how's it going|how are u)\b", prompt_lower):
            return _pick(
                [
                    "I am doing well and ready to help. How are you feeling today?",
                    "Doing good here. Want to chat, or should we work through your to-do list together?",
                    "All good on my side. Tell me what is on your mind.",
                ]
            )

        if re.search(r"\b(i just want to talk|just want to talk|let's talk|wanna talk|want to talk)\b", prompt_lower):
            return _pick(
                [
                    "I am in. We can just talk. What kind of day are you having so far?",
                    "Absolutely, we can keep it casual. What are you thinking about right now?",
                    "Sounds good. I am here to talk. What do you want to start with?",
                ]
            )

        if re.search(r"\b(thanks|thank you|appreciate it)\b", prompt_lower):
            return _pick(
                [
                    "Anytime. I am happy to help. Want to do one more thing before we wrap up?",
                    "You are very welcome. If you want, I can also help you plan the next step.",
                    "Glad that helped. Tell me what you want to do next.",
                ]
            )

        if re.search(r"\b(help|what can you do|who are you)\b", prompt_lower):
            return (
                "I am your Orchestrator. I can chat naturally, check your calendar, "
                "manage tasks, and carry context across turns. For example, you can say "
                "'show my meetings tomorrow' or 'mark the first task as done'."
            )

        return _pick(
            [
                "I am here with you. If you want, we can chat or get practical and organize your calendar and tasks.",
                "Totally fine. We can keep this conversational, and whenever you are ready I can help with meetings or tasks too.",
                "I can do both: normal conversation and productivity help. What are you in the mood for right now?",
            ]
        )

    def _orchestrator_reply(self, response: MasterResponse) -> str:
        if not response.results:
            return "I completed your request."
        completed = [r for r in response.results if r.status == TaskStatus.COMPLETED and r.output]
        failed = [r for r in response.results if r.status == TaskStatus.FAILED]
        if completed and not failed:
            if len(completed) == 1:
                return completed[0].output or "Done."
            lines = [f"- [{r.agent_name}] {r.output}" for r in completed if r.output]
            return "Great, here is what I found:\n" + "\n".join(lines)
        return response.summary or "I hit a snag while handling that, but I can try a different path."

    async def _invoke_task_list_direct(self, task: A2ATask) -> str:
        """Deterministic Google Tasks list handling for list-centric prompts."""
        from agent_family.mcp_servers.tasks_server import (
            list_task_lists as list_task_lists_tool_impl,
            list_tasks as list_tasks_tool_impl,
        )

        prompt_lower = task.prompt.lower()
        access_token = task.parameters.get("access_token")
        refresh_token = task.parameters.get("refresh_token")

        task_lists = await asyncio.to_thread(
            list_task_lists_tool_impl,
            access_token=access_token,
            refresh_token=refresh_token,
        )

        if "multiple list" in prompt_lower or "how many list" in prompt_lower:
            if not task_lists:
                return "I checked Google Tasks but could not find any task lists yet."
            names = ", ".join(t["title"] for t in task_lists)
            plural = "list" if len(task_lists) == 1 else "lists"
            return f"Yes, you have {len(task_lists)} task {plural}: {names}."

        target_list = None
        if "shopping list" in prompt_lower:
            target_list = next(
                (tl for tl in task_lists if "shopping" in tl["title"].lower()),
                None,
            )
            if target_list is None:
                return "I checked your task lists but could not find one named 'Shopping'."

        task_list_id = target_list["id"] if target_list else "@default"
        target_name = target_list["title"] if target_list else "default list"

        tasks = await asyncio.to_thread(
            list_tasks_tool_impl,
            task_list_id=task_list_id,
            include_completed=False,
            access_token=access_token,
            refresh_token=refresh_token,
        )

        if not tasks:
            return f"Nice and tidy. I could not find any pending tasks in your {target_name}."

        lines = [f"- {item.get('title', 'Untitled')}" for item in tasks]
        return f"Here is what is in your {target_name}:\n" + "\n".join(lines)

    async def _invoke_task_create_direct(self, task: A2ATask) -> str:
        """Deterministic task creation to avoid LLM tool-calling misses."""
        from agent_family.mcp_servers.tasks_server import create_task as create_task_tool_impl

        prompt = task.prompt.strip()
        prompt_lower = prompt.lower()

        title = ""
        patterns = [
            r"(?:add|create|new)\s+(?:a\s+)?task(?:\s+to)?\s+(.+)$",
            r"(?:add|create)\s+(?:a\s+)?todo(?:\s+to)?\s+(.+)$",
            r"(?:reminder|action item)(?:\s+to)?\s+(.+)$",
        ]
        for pat in patterns:
            match = re.search(pat, prompt_lower)
            if match:
                title = match.group(1).strip(" .,!?:;")
                break

        if not title:
            title = prompt.strip(" .,!?:;")

        created = await asyncio.to_thread(
            create_task_tool_impl,
            title=title,
            access_token=task.parameters.get("access_token"),
            refresh_token=task.parameters.get("refresh_token"),
        )
        created_title = created.get("title") or title
        return f"I have added this task to your default list: {created_title}."

    async def _invoke_task_update_direct(self, task: A2ATask) -> str:
        """Deterministic task completion flow to avoid model 503 failures."""
        from agent_family.mcp_servers.tasks_server import (
            list_tasks as list_tasks_tool_impl,
            update_task as update_task_tool_impl,
        )

        prompt = task.prompt.strip()
        prompt_lower = prompt.lower()
        access_token = task.parameters.get("access_token")
        refresh_token = task.parameters.get("refresh_token")
        context = task.parameters.get("context") or {}

        tasks = await asyncio.to_thread(
            list_tasks_tool_impl,
            task_list_id="@default",
            include_completed=False,
            access_token=access_token,
            refresh_token=refresh_token,
        )
        if not tasks:
            return "I checked your default list, but I could not find any pending tasks to update."

        target_title: str | None = None
        if "first one" in prompt_lower or "1st" in prompt_lower or "first task" in prompt_lower:
            last_titles = context.get("last_task_titles", "")
            if last_titles:
                target_title = last_titles.split("|||")[0].strip()
            else:
                target_title = tasks[0].get("title")

        if not target_title:
            # Try to infer from prompt by matching known task titles.
            by_length = sorted(tasks, key=lambda t: len((t.get("title") or "")), reverse=True)
            for item in by_length:
                title = (item.get("title") or "").strip()
                if title and title.lower() in prompt_lower:
                    target_title = title
                    break

        # If the user only typed the title in a follow-up turn, treat it as target.
        if not target_title and len(prompt.split()) <= 6:
            target_title = prompt

        if not target_title:
            return "Tell me the exact task title (or say 'first one') and I will mark it completed right away."

        target_item = None
        for item in tasks:
            title = (item.get("title") or "").strip().lower()
            if title == target_title.strip().lower():
                target_item = item
                break

        if target_item is None:
            return f"I could not find a pending task titled '{target_title}'. Want me to show your current list first?"

        updated = await asyncio.to_thread(
            update_task_tool_impl,
            task_id=target_item["task_id"],
            status="completed",
            task_list_id=target_item.get("task_list_id", "@default"),
            access_token=access_token,
            refresh_token=refresh_token,
        )
        done_title = updated.get("title") or target_item.get("title") or target_title
        return f"Done. Marked task as completed: {done_title}."

    async def _invoke_sub_agent(self, message: A2AMessage, card: Any) -> str:
        """
        Execute a sub-agent task and return its text output.

        In production this sends an HTTP JSON-RPC POST to ``card.url``.
        In development/testing it runs the ADK agent in-process.

        Returns
        -------
        str
            The sub-agent's natural-language response.
        """
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai.types import Content, Part

        # Select the right ADK agent
        task = message.params
        access_token = task.parameters.get("access_token")
        refresh_token = task.parameters.get("refresh_token")
        access_ctx = refresh_ctx = None
        if task.agent_name == "CalendarAgent":
            from agent_family.agents.calendar_agent import (
                calendar_agent,
                reset_runtime_tokens as reset_calendar_runtime_tokens,
                set_runtime_tokens as set_calendar_runtime_tokens,
            )
            agent = calendar_agent
            access_ctx, refresh_ctx = set_calendar_runtime_tokens(access_token, refresh_token)
        elif task.agent_name == "TaskAgent":
            from agent_family.agents.task_agent import (
                reset_runtime_tokens as reset_task_runtime_tokens,
                set_runtime_tokens as set_task_runtime_tokens,
                task_agent,
            )
            agent = task_agent
            access_ctx, refresh_ctx = set_task_runtime_tokens(access_token, refresh_token)
        else:
            raise ValueError(f"Unknown agent: {task.agent_name!r}")

        session_service = InMemorySessionService()
        runner = Runner(
            agent=agent,
            app_name=f"master_dispatch_{task.task_id}",
            session_service=session_service,
        )

        session = await session_service.create_session(
            app_name=f"master_dispatch_{task.task_id}",
            user_id="master_agent",
        )

        user_content = Content(
            role="user",
            parts=[Part(text=task.prompt)],
        )

        output_parts: list[str] = []
        try:
            async for event in runner.run_async(
                user_id="master_agent",
                session_id=session.id,
                new_message=user_content,
            ):
                if event.is_final_response():
                    content = getattr(event, "content", None)
                    parts = getattr(content, "parts", None) if content is not None else None
                    if not parts:
                        logger.warning(
                            "Final response from %s/%s had no content parts",
                            task.agent_name,
                            task.skill_id,
                        )
                        continue

                    for part in parts:
                        text = getattr(part, "text", None)
                        if text:
                            output_parts.append(text)
        finally:
            if task.agent_name == "CalendarAgent" and access_ctx is not None and refresh_ctx is not None:
                reset_calendar_runtime_tokens(access_ctx, refresh_ctx)
            if task.agent_name == "TaskAgent" and access_ctx is not None and refresh_ctx is not None:
                reset_task_runtime_tokens(access_ctx, refresh_ctx)

        return "\n".join(output_parts) or f"[{task.agent_name}] Task completed: {task.skill_id}"

    # ── Aggregation ───────────────────────────────────────────────────────────

    def _aggregate(
        self,
        original_prompt: str,
        decomposition: TaskDecomposition,
        results: list[SubAgentResult],
    ) -> MasterResponse:
        """Build the final MasterResponse from all sub-agent results."""
        success_count = sum(1 for r in results if r.status == TaskStatus.COMPLETED)
        total = len(results)

        if success_count == total:
            overall_status = "success"
        elif success_count == 0:
            overall_status = "failure"
        else:
            overall_status = "partial_failure"

        # Build a human-readable summary
        summary_parts = []
        for res in results:
            if res.status == TaskStatus.COMPLETED:
                summary_parts.append(
                    f"✅ [{res.agent_name}/{res.skill_id}] {res.output or 'Completed'}"
                )
            else:
                summary_parts.append(
                    f"❌ [{res.agent_name}/{res.skill_id}] Failed: {res.error}"
                )

        summary = "\n".join(summary_parts)

        return MasterResponse(
            original_prompt=original_prompt,
            decomposition_id=decomposition.decomposition_id,
            reasoning=decomposition.reasoning,
            results=results,
            overall_status=overall_status,
            summary=summary,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_registry_summary(self) -> str:
        """Build a compact text summary of registered agents and skills."""
        lines: list[str] = []
        for card in self.registry.list_all():
            lines.append(f"\n### {card.name}")
            lines.append(f"URL: {card.url}")
            lines.append("Skills:")
            for skill in card.skills:
                lines.append(f"  - {skill.id}: {skill.description}")
        return "\n".join(lines) if lines else "(No agents registered)"

    def __repr__(self) -> str:
        return (
            f"<MasterAgent model={self.model!r} "
            f"registry_size={len(self.registry)}>"
        )
