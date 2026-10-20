import asyncio
import os
import webbrowser
from typing import Annotated, Any, Literal, NotRequired

from dotenv import load_dotenv
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware, HumanInTheLoopMiddleware
from langchain.messages import AIMessage, ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.graph.ui import AnyUIMessage, push_ui_message, ui_message_reducer
from langgraph.types import Command

from unsubscribe_agent.scanner import scan

load_dotenv()

REVIEW_TOOL = "open_unsubscribe_links"


class UnsubscribeState(AgentState):
    unsubscribe_candidates: NotRequired[list[dict[str, Any]]]
    scan_stats: NotRequired[dict[str, Any]]
    ui: NotRequired[Annotated[list[AnyUIMessage], ui_message_reducer]]


@tool
async def scan_unsubscribe_emails(
    runtime: ToolRuntime,
    scope: Literal["inbox", "all"] = "inbox",
    days: int = 90,
    max_per_folder: int = 100,
) -> Command:
    """Scan every Thunderbird account for emails that carry an Unsubscribe link.

    scope: "inbox" scans each account's inbox, "all" every folder except trash/junk/sent/drafts.
    days: only look at mail newer than this many days (0 = no limit).
    max_per_folder: newest messages to inspect per folder.
    """
    # Spawning the MCP stdio process makes blocking calls, which `langgraph dev` refuses
    # on the server loop, so the scan gets a loop of its own in a worker thread.
    result = await asyncio.to_thread(asyncio.run, scan(scope=scope, max_per_folder=max_per_folder, days=days or None))
    candidates = result.pop("candidates")
    lines = [
        f"{c['id']} | {c['sender_name']} <{c['sender_email']}> | {c['email_count']} emails | {c['account']} | {c['subject'][:80]}"
        for c in candidates
    ]
    summary = (
        f"Scanned {result['accounts_scanned']} accounts, {result['folders_scanned']} folders, "
        f"{result['emails_scanned']} emails. {result['emails_with_unsubscribe']} emails with an unsubscribe link "
        f"from {len(candidates)} senders.\n" + "\n".join(lines)
    )
    if result["errors"]:
        summary += "\nErrors:\n" + "\n".join(result["errors"])
    return Command(
        update={
            "unsubscribe_candidates": candidates,
            "scan_stats": result,
            "messages": [ToolMessage(summary, tool_call_id=runtime.tool_call_id)],
        }
    )


@tool(REVIEW_TOOL)
def open_unsubscribe_links(candidate_ids: list[str], runtime: ToolRuntime) -> str:
    """Show the user the unsubscribe list for review, then open the approved links in the browser.

    candidate_ids: the ids (u1, u2, ...) returned by scan_unsubscribe_emails.
    """
    by_id = {c["id"]: c for c in runtime.state.get("unsubscribe_candidates", [])}
    opened, unknown = [], []
    for cid in candidate_ids:
        candidate = by_id.get(cid)
        if not candidate:
            unknown.append(cid)
            continue
        webbrowser.open_new_tab(candidate["unsubscribe_url"])
        opened.append(f"{cid} {candidate['sender_email']}")
    report = f"Opened {len(opened)} unsubscribe links in new browser tabs: " + ", ".join(opened)
    if unknown:
        report += f". Unknown ids: {', '.join(unknown)}"
    return report


def describe_review(tool_call: dict[str, Any], state: UnsubscribeState, runtime: Any) -> str:
    """Markdown list for the human review, readable in Studio as well as Agent Chat UI."""
    by_id = {c["id"]: c for c in state.get("unsubscribe_candidates", [])}
    rows = [
        f"| {c['id']} | {c['sender_name']} | {c['email_count']} | {c['account']} | [Unsubscribe ↗]({c['unsubscribe_url']}) |"
        for cid in tool_call["args"].get("candidate_ids", [])
        if (c := by_id.get(cid))
    ]
    return (
        "**Emails with an unsubscribe link.** Use the card's buttons (or the links) to open each unsubscribe page in a new tab.\n\n"
        "- **Accept**: opens every unsubscribe link in the list in your browser.\n"
        "- **Edit**: keep in `candidate_ids` only the ones you want opened.\n"
        "- **Ignore/Reject**: opens nothing.\n\n"
        "| id | sender | emails | account | unsubscribe |\n|---|---|---|---|---|\n" + "\n".join(rows)
    )


class UnsubscribeListUI(AgentMiddleware[UnsubscribeState]):
    """Renders the candidate list as a card with one button per email.

    Runs as its own after_model node *before* the human-in-the-loop node, so the
    card is committed to state before the interrupt pauses the run.
    """

    state_schema = UnsubscribeState

    def after_model(self, state: UnsubscribeState, runtime: Any) -> dict[str, Any] | None:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or not any(tc["name"] == REVIEW_TOOL for tc in last.tool_calls):
            return None
        push_ui_message(
            "unsubscribe_list",
            {"candidates": state.get("unsubscribe_candidates", []), "stats": state.get("scan_stats", {})},
            id=f"unsubscribe-list-{last.id}",
            message=last,
        )
        return None


SYSTEM_PROMPT = """You are an assistant that helps the user unsubscribe from newsletters in Thunderbird.

1. Call scan_unsubscribe_emails to review every account (by default the inboxes from the last 90 days; use scope="all" or change days if the user asks).
2. Then ALWAYS call open_unsubscribe_links with ALL the ids found: that call shows the user the list with one button per email and waits for their review.
3. When the review comes back, summarize what was opened, or that the user preferred to do it by hand.

Never delete or modify emails. If no email has an unsubscribe link, say so and do not call open_unsubscribe_links."""


agent = create_agent(
    os.environ.get("AGENT_MODEL", "anthropic:claude-sonnet-5-5"),
    tools=[scan_unsubscribe_emails, open_unsubscribe_links],
    system_prompt=SYSTEM_PROMPT,
    state_schema=UnsubscribeState,
    middleware=[
        # after_model hooks run in reverse order: UnsubscribeListUI first, then the interrupt.
        HumanInTheLoopMiddleware(
            interrupt_on={
                "scan_unsubscribe_emails": False,
                REVIEW_TOOL: {"allowed_decisions": ["approve", "edit", "reject"], "description": describe_review},
            }
        ),
        UnsubscribeListUI(),
    ],
)
