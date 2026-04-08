# 🤖 Agent Family — Google ADK Multi-Agent System

> **Master Agent** (Gemini 3.1 Flash Lite) · **A2A Protocol** · **Pydantic v2** · **asyncio concurrent dispatch**

A production-grade multi-agent system built with **Google ADK (Python)** that orchestrates specialist sub-agents using the **Agent-to-Agent (A2A) protocol**.

---

## Architecture

```
User Prompt
    │
    ▼
┌─────────────────────────────────────────────┐
│              MasterAgent                    │
│   model: gemini-2.0-flash-lite               │
│                                             │
│  1. Parse prompt → TaskDecomposition (JSON) │
│  2. Validate with Pydantic v2               │
│  3. asyncio.gather() → concurrent dispatch  │
└─────────┬────────────────────────┬──────────┘
          │  A2A message           │  A2A message
          ▼                        ▼
┌─────────────────┐    ┌─────────────────────┐
│  CalendarAgent  │    │     TaskAgent        │
│  gemini-2.0-    │    │  gemini-2.0-flash-lite    │
│  flash-lite     │    │                     │
│                 │    │                     │
│ ● schedule_event│    │ ● create_task        │
│ ● list_upcoming │    │ ● update_task        │
│ ● cancel_event  │    │ ● list_tasks         │
│ ● update_event  │    │ ● assign_task        │
└─────────────────┘    └─────────────────────┘
          │                        │
          └───────────┬────────────┘
                      ▼
             MasterResponse (aggregated)
```

### Key components

| Component | File | Purpose |
|---|---|---|
| **A2A Schemas** | `agent_family/a2a/schemas.py` | Pydantic v2 A2A message types |
| **AgentCard** | `agent_family/a2a/agent_card.py` | A2A discovery manifest |
| **AgentRegistry** | `agent_family/registry/registry.py` | Singleton agent directory |
| **CalendarAgent** | `agent_family/agents/calendar_agent.py` | ADK agent for calendar events |
| **TaskAgent** | `agent_family/agents/task_agent.py` | ADK agent for tasks/todos |
| **MasterAgent** | `agent_family/agents/master_agent.py` | Orchestrator with async dispatch |
| **CLI Runner** | `agent_family/runner.py` | Interactive REPL / single-shot |

---

## Quick Start

### 1. Install dependencies

```bash
cd "Agent Family"
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and set GOOGLE_API_KEY=your_key_here
```

### 3. Run the agent

```bash
# Interactive REPL
python -m agent_family.runner

# Single prompt
python -m agent_family.runner --prompt "Schedule a meeting tomorrow at 3pm and create a task to prepare slides"

# Via installed script
agent-family --prompt "Show my calendar for this week"

# List registered agents
agent-family --list-agents
```

### 4. Run tests

```bash
# All tests (no API key required)
pytest tests/ -v

# Only fast unit/routing tests
pytest tests/ -m "unit or routing" -v

# With coverage
pytest tests/ --cov=agent_family --cov-report=term-missing
```

---

## A2A Protocol

The system implements the [A2A (Agent-to-Agent) specification](https://github.com/google-a2a/A2A):

```json
{
  "jsonrpc": "2.0",
  "id": "uuid",
  "method": "tasks/send",
  "params": {
    "task_id": "uuid",
    "agent_name": "CalendarAgent",
    "skill_id": "schedule_event",
    "prompt": "Schedule a team standup every Monday at 9am",
    "parameters": { "recurring": true, "day": "Monday", "time": "09:00" },
    "priority": 7
  }
}
```

Each agent's AgentCard is accessible at `/.well-known/agent-card.json`:

```json
{
  "name": "CalendarAgent",
  "description": "Manages Google Calendar events",
  "url": "http://localhost:8001",
  "skills": [
    {
      "id": "schedule_event",
      "name": "Schedule Event",
      "tags": ["calendar", "meeting", "book"]
    }
  ]
}
```

---

## AgentRegistry

The `AgentRegistry` is a **thread-safe singleton** that maps agent names to their AgentCards and resolves intents:

```python
from agent_family.registry.registry import AgentRegistry
from agent_family.agents.calendar_agent import CALENDAR_AGENT_CARD

registry = AgentRegistry()                     # singleton
registry.register(CALENDAR_AGENT_CARD)

# Intent resolution (scored keyword matching)
agent_name, skill_id = registry.resolve_intent("schedule a meeting tomorrow")
# → ("CalendarAgent", "schedule_event")
```

---

## Pydantic v2 Schemas

All A2A messages are strictly validated:

```python
from agent_family.a2a.schemas import A2ATask, TaskDecomposition

task = A2ATask(
    agent_name="CalendarAgent",
    skill_id="schedule_event",          # validated snake_case
    prompt="Book a room at 3pm",
    parameters={"time": "15:00"},
    priority=8,                          # validated 1-10
)

decomp = TaskDecomposition(
    original_prompt="...",
    tasks=[task1, task2],               # unique task_ids validated
    reasoning="Two intents detected",
)
```

---

## Test Suite

```
tests/
├── test_schemas.py       — 40+ Pydantic v2 schema validation tests
├── test_registry.py      — Singleton, thread-safety, CRUD lifecycle
├── test_master_routing.py — 9 routing scenarios, 59 test cases
└── test_concurrent.py    — asyncio concurrency, failure isolation
```

All tests run without a Google API key.

---

## Extending the System

### Add a new sub-agent

```python
# 1. Create agent_family/agents/my_agent.py
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from agent_family.a2a.agent_card import AgentCard

def my_tool(input: str) -> dict: ...

my_agent = LlmAgent(name="MyAgent", model="gemini-2.0-flash-lite", tools=[FunctionTool(my_tool)])

MY_AGENT_CARD = AgentCard(
    name="MyAgent",
    description="...",
    url="http://localhost:8003",
    skills=[AgentSkill(id="my_skill", name="My Skill", description="...")]
)

# 2. Register in runner.py
registry.register(MY_AGENT_CARD)
```

---

## License

Apache 2.0
