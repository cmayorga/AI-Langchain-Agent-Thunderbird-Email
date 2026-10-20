# AI Langchain Agent For Thunderbird Emails

A LangChain agent that scans every account configured in Thunderbird (through
[Thunderbird-MCP](https://github.com/U-C4N/Thunderbird-MCP)), finds the emails that have an
"Unsubscribe" link (the `List-Unsubscribe` header or a link in the body) and shows you a list
with a button for each sender that opens the unsubscribe page in another tab.

<img width="1470" height="898" alt="image" src="https://github.com/user-attachments/assets/7d0e7d7b-6397-4724-a941-290b3e9d701c" />

## Flow

```
model ──▶ UnsubscribeListUI.after_model ──▶ HumanInTheLoopMiddleware.after_model ──▶ tools
            (pushes the button card)          (interrupt: Approve / Edit / Reject)
```

1. `scan_unsubscribe_emails` connects to Thunderbird-MCP (stdio, `--read-only`) and walks
   `account_list` → `folder_list` → `mail_list` → `mail_get(detail="full")`, then groups the
   results by sender.
2. The model calls `open_unsubscribe_links` with every id. Before that tool runs:
   - `UnsubscribeListUI` attaches the `unsubscribe_list` card (`src/unsubscribe_agent/ui.tsx`)
     with a **"Unsubscribe ↗"** button per sender (`target=_blank`).
   - `HumanInTheLoopMiddleware` pauses the run so you can review it:
     - **Approve**: opens every listed unsubscribe link in your browser.
     - **Edit**: keep in `candidate_ids` only the ones you want opened.
     - **Reject**: opens nothing (you use the card's buttons yourself).

The agent never deletes or modifies mail: the MCP server runs with `--read-only`.

## Getting started

```powershell
.\run_dashboard.ps1
```

Or by hand:

```powershell
.venv\Scripts\langgraph.exe dev --allow-blocking          # API + LangGraph Studio
cd agent-chat-ui; npx pnpm@10 dev                         # dashboard at http://localhost:3000
```

- **Agent Chat UI** (http://localhost:3000, graph `unsubscribe_agent`): shows the button card
  and the review panel.
- **LangGraph Studio** (https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024):
  shows the graph and the interrupt; the list arrives as a markdown table in the description.

`--allow-blocking` is needed because starting the MCP stdio process on Windows makes blocking
calls (the scan runs on its own thread, so it doesn't freeze the server).

## One-time setup (already done)

```powershell
uv sync                                                   # agent dependencies
cd thunderbird-mcp; uv venv --python 3.13 .venv; uv pip install -e .
.venv\Scripts\tbmcp.exe install-addon --yes               # add-on inside Thunderbird (restarts it)
.venv\Scripts\tbmcp.exe doctor                            # checks the connection
```

`.env` holds `ANTHROPIC_API_KEY` and `AGENT_MODEL` (default `anthropic:claude-sonnet-5-5`; any
`provider:model` works with `init_chat_model`).

## Local tweaks to `agent-chat-ui`

- `next.config.mjs`: rewrite `/ui/*` → `http://localhost:2024/ui/*` (langgraph-api serves the
  card's bundle with a relative path).
- `src/app/layout.tsx`: system font instead of Google Fonts' `Inter` (the download timed out).
