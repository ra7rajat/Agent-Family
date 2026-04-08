# AI Agent Handover & Context Document

> **Target Audience:** Future iterations of this AI agent (or other agents) resuming work on the **Agent Family** project.
> **Purpose:** To provide immediate context restoration, detailed architectural understanding, and an evaluation baseline for continuing development on this system without having to blindly read through dozen of files.

---

## 1. Project Overview

**Agent Family** is a multi-agent orchestration system that acts as a unified facade for managing Google Calendar and Google Tasks. 
It uses a **Next.js** React frontend and a **FastAPI** Python backend. The backend manages a structured Agent-to-Agent (A2A) protocol where a `MasterAgent` decomposes user intent and concurrently orchestrates specialized sub-agents (`CalendarAgent`, `TaskAgent`). Those sub-agents execute real Google API calls via `FastMCP` servers.

---

## 2. Core Architecture

### Backend (Python / FastAPI / ADK)
*   **API Layer (`server.py`)**: Hosts the SSE (Server-Sent Events) endpoint `/api/v1/chat` and OAuth2 callback routes (`/auth/*`).
*   **Master Agent (`agents/master_agent.py`)**: Uses `gemini-2.0-flash-lite` with structured JSON output requirements. It receives unstructured user text, infers multiple intents, models them as a `TaskDecomposition` object (using `pydantic`), and dispatches tasks asynchronously via `asyncio.gather`. Crucially, it passes the user's `access_token` and `refresh_token` down to every task through `parameters`.
*   **Sub-Agents (`agents/calendar_agent.py`, `agents/task_agent.py`)**: Domain-specific agents registered in the `AgentRegistry`. They act on the decomposed prompts.
*   **MCP Servers (`mcp_servers/`)**: Execute the actual Google API calls. Tools define an explicit interface structure and inject dynamic credentials dynamically per-request (`_get_service(access_token)`).
*   **A2A Protocol (`a2a/schemas.py`)**: Typed JSON-RPC style wrappers passed between the master and sub-agents. Ensures standard attributes like `task_id`, `agent_name`, and `skill_id`.

### Frontend (Next.js + React)
*   **Chat Interface (`web/src/components/ChatInterface.tsx`)**: Streams responses from FastAPI via Server-Sent Events. Manages sequential agent rendering logic using `framer-motion` for animations.
*   **Authentication Flow (`web/src/context/AuthContext.tsx`, `AuthGuard.tsx`)**: Enforces authentication states. Unauthenticated users see an animated `SignInPrompt`. Uses `credentials="include"` during `fetch` strictly to send standard `HTTPOnly` cookies.

---

## 3. High-Stakes Authentication Design

The system explicitly avoids managing OAuth2 tokens in the browser DOM/JS environment to optimize for strict security against XSS.

1.  **Google OAuth2**: Authorized with `prompt=consent` and `access_type=offline`.
2.  **Session Mapping (`auth/session_store.py`)**: When the backend receives an authorization code, an in-memory session is generated. The `access_token` and `refresh_token` are symmetrically encrypted in Python memory using `cryptography.fernet.Fernet`.
3.  **Cookies**: The Server generates an `HTTPOnly` `SameSite=Lax` cookie (`agent_session_id`).
4.  **SSO Auto-Refresh**: If an access token expires during the chat processing, `_maybe_refresh()` uses the securely held refresh token to get a new one, updates the Fernet-encrypted store, and resumes the action uninterrupted.

---

## 4. Current State (As of Last Session)

**Stability**: Rock-solid.
*   Next.js build succeeds (`npm run build`).
*   Frontend test suite passes exactly `15/15` tests using Jest and React Testing Library.
*   Backend test suite passes all routing, concurrent execution, and resilient backoff tests.
*   Linting and formatting are clean, though local IDE representations of sub-module resolutions sometimes miss `.venv` paths.

**Completed Milestones**:
*   Replaced the CLI-environment authentication with dynamic web sessions context injection.
*   Built the interactive Front-End NextJS UI.

---

## 5. Agent Evaluation Baseline & Next Steps

When resuming work, focus on the following evaluation metrics and gaps established in the latest review (`PROJECT_EVALUATION.md`):

### Top Priorities to Address Next:
1.  **Persistent Storage (Security/Efficiency)** 
    *   *Current Gap*: `SessionStore` lives in Python memory. Server restart forces all active users out.
    *   *Next Step*: Migrate `SessionStore` to use SQLite (for local) or Redis/Postgres (cloud-ready). Maintain the Fernet encryption over the raw database values.
2.  **OAuth State Verification (Security)**
    *   *Current Gap*: A random `state` parameter is passed to Google and echoed back, but currently not validated inside `/auth/callback`.
    *   *Next Step*: Store `state` in an encrypted, short-lived cookie during `/auth/login` and verify it in the callback to harden against CSRF attacks.
3.  **End-to-End Testing Pipeline (Testing)**
    *   *Current Gap*: The backend unit tests and frontend component tests are separated. Heavily mocking `fetch` works for unit isolation but hides integration bugs.
    *   *Next Step*: Introduce Cypress or Playwright to boot both servers and execute a full simulated login and agent query sequence.
4.  **Background Token Refresh (Efficiency)**
    *   *Current Gap*: Tokens refresh inline with user API requests.
    *   *Next Step*: Move token expiry evaluation into an asynchronous background service task.

---

## 6. Important References to Keep Handy

*   **Google Auth Docs:** [OAuth 2.0 Web Server Apps](https://developers.google.com/identity/protocols/oauth2/web-server)
*   **FastMCP Architecture:** Review the existing dependency structure in `agent_family/mcp_servers/` ensuring no static `.env` dependencies remain there.
*   **Startup CLI Commands:**
    ```bash
    # Tab 1: Backend
    source .venv/bin/activate
    uvicorn agent_family.server:app --reload --port 8000
    
    # Tab 2: Frontend
    cd web && npm run dev
    ```
