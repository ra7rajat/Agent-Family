# Scaling Agent Family: Adding New Agents & MCP Servers

This architectural guide details the exact steps required across the entire stack (Backend, Frontend, and OAuth2 Config) to introduce new Agent capabilities and connect additional FastMCP servers into the Agent Family framework.

Assuming integration with the **Google Ecosystem**, the process follows a strict pattern ensuring security (session-aware token injection), type-safety (Pydantic schema definitions), and frontend visibility.

---

## Part 1: Backend Implementation

When adding a new Google capability (e.g., Gmail), you must touch four main components in the Python backend.

### 1. Create the FastMCP Server (`agent_family/mcp_servers/gmail_server.py`)
The MCP server acts as the bridge executing the raw Google API calls.

*   **Define Scopes:** Declare necessary Google OAuth scopes (e.g., `["https://www.googleapis.com/auth/gmail.readonly"]`).
*   **Implement `_get_service`:** Use the shared `get_google_service()` utility from `base.py`, ensuring you explicitly accept and pass down the `access_token` and `refresh_token` so the tool is session-aware.
*   **Define Tools:** Create Python functions wrapped in `@mcp.tool()` and `@google_api_retry`. Ensure they take `access_token` and `refresh_token` optional kwargs.
*   **Return Schemas:** Use `model_dump()` from a structured Pydantic class to return type-safe dictionaries.

### 2. Define the ADK Agent (`agent_family/agents/gmail_agent.py`)
The Google ADK Agent provides the natural language translation layer.

*   **Define `AgentCard`:** Create an `AgentCard` with a unique name, description, and list of `SkillCard`s for each MCP tool.
*   **Define ADK `Agent`:** Initialize a `LlmAgent` containing the natural language instruction telling it how to use its tools. Register the MCP server tools dynamically via the standard registry pipeline.

### 3. Update the Master Agent Orchestrator (`agent_family/agents/master_agent.py`)
The `MasterAgent` must know about the new intent to decompose user prompts successfully.

*   **Update Keyword Fallback:** Edit `_rule_based_decomposition` mapping. Add keyword tuples (e.g., `("email", "GmailAgent", "read_emails")`) so that the fallback router can handle API outages.
*   **Update ADK Dispatch:** In `_invoke_sub_agent()`, add the new agent to the routing `if/elif` block. *(Note: If migrated fully to network HTTP JSON-RPC calls, this step disappears as it becomes dynamic via `card.url`).*

### 4. Register the Agent (`agent_family/server.py`)
Register the newly created Agent and AgentCard directly into the active `AgentRegistry`.

```python
from agent_family.agents.gmail_agent import gmail_agent, gmail_agent_card
_registry.register(gmail_agent_card, gmail_agent)
```

---

## Part 2: Configuration & OAuth Updates

A critical step when integrating new Google APIs is updating the permission surface.

### 1. Google Cloud Console
*   **Enable the API:** Navigate to **APIs & Services > Library** and enable the required API (e.g., *Gmail API*).
*   **Update OAuth Consent Screen:** Add the new scopes defined in your MCP server to your OAuth App configurations.

### 2. Update FastApi Server Auth (`agent_family/auth/oauth2.py`)
*   Add the new scopes to the `SCOPES` generation array or directly into the web flow flow initialization to guarantee the server asks the user for the right permissions upon login. *(If a user is already logged in when you push this update, their `refresh_token` will stop working for the new service until they re-authenticate).*

---

## Part 3: Frontend Implementation

The frontend is dynamically driven by the SSE stream, but certain aesthetic and user-flow elements must be updated to represent the new Agent gracefully.

### 1. Update the Sign-In Prompt (`web/src/components/SignInPrompt.tsx`)
Showcase the new capabilities to the user during onboarding.

*   **Import an Icon:** Get a semantic icon from `lucide-react` (e.g., `Mail`).
*   **Add to `AGENT_ENTRIES`:** Insert the new agent into the animation list with an appropriate delay.
    ```javascript
    {
      Icon: Mail,
      label: "Gmail",
      message: "I can draft and read your emails ✉️",
      delay: 1.5,
    }
    ```

### 2. Update the A2A Task Rendering (`web/src/components/MessageCard.tsx`)
Teach the UI how to visually represent tasks related to the new agent.

*   **Determine Color Branding:** Update standard mapping configurations to apply a distinct border/background color scheme for the new agent (e.g., Red/Pink for Gmail).
*   **Assign Icon:** Assign the appropriate Lucide icon to the visual card header when rendering completed messages.

---

## Future Scope: Sample Google Ecosystem Integrations

The architecture is highly extensible. Here are high-value additions to consider building next using the Google Ecosystem:

### 1. **GmailAgent**
*   **MCP Tools:** `read_recent_emails`, `draft_email`, `search_threads`
*   **Use Case:** *"Read my last email from Dave, extract the action items, and create tasks for tomorrow."*
*   **Required Scope:** `https://www.googleapis.com/auth/gmail.modify`

### 2. **DriveAgent**
*   **MCP Tools:** `search_drive`, `read_document_text`, `create_folder`
*   **Use Case:** *"Find the Q3 Architecture diagram in my drive and summarize the three bullet points into an email to my manager."*
*   **Required Scope:** `https://www.googleapis.com/auth/drive.readonly`

### 3. **KeepAgent (Notes)**
*   **MCP Tools:** `list_notes`, `create_note`, `append_to_note`
*   **Use Case:** *"Create a new note called 'Grocery List' and add milk and eggs to it."*
*   **Required Scope:** `https://www.googleapis.com/auth/keep`

### 4. **ContactsAgent**
*   **MCP Tools:** `search_contacts`, `get_contact_info`
*   **Use Case:** *"What is Sarah's phone number? Schedule a 15-minute call with her on Friday."* (Requires interaction between ContactsAgent and CalendarAgent).
*   **Required Scope:** `https://www.googleapis.com/auth/contacts.readonly`
