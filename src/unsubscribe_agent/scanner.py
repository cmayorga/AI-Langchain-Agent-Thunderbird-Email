"""Finds emails with an "Unsubscribe" link across every Thunderbird account.

All Thunderbird access goes through the Thunderbird-MCP server
(https://github.com/U-C4N/Thunderbird-MCP), driven over one MCP stdio session
so a scan of hundreds of messages does not spawn hundreds of processes.
"""

import asyncio
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp import ClientSession

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TBMCP_PYTHON = PROJECT_ROOT / "thunderbird-mcp" / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

# Words that mark an unsubscribe link, in the languages that show up in a mixed inbox.
UNSUBSCRIBE_WORDS = re.compile(
    r"unsubscribe|unsuscribe|unsubscription|opt[\s_-]?out|"
    r"darse de baja|darte de baja|date de baja|dar de baja|cancelar (la )?suscripci[oó]n|anular (la )?suscripci[oó]n|"
    r"d[ée]sabonner|d[ée]sinscri|abmelden|abbestellen|disiscriv|annulla iscrizione|cancelar inscri[cç][aã]o",
    re.IGNORECASE,
)
ANCHOR = re.compile(r"<a\b[^>]*?href\s*=\s*([\"'])(.*?)\1[^>]*>(.*?)</a\s*>", re.IGNORECASE | re.DOTALL)
TAG = re.compile(r"<[^>]+>")
URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
ANGLE_URI = re.compile(r"<\s*([^>]+?)\s*>")


def mcp_client() -> MultiServerMCPClient:
    """Client for the Thunderbird-MCP server, read-only: this agent never changes mail."""
    python = os.environ.get("TBMCP_PYTHON") or str(TBMCP_PYTHON)
    return MultiServerMCPClient(
        {
            "thunderbird": {
                "transport": "stdio",
                "command": python,
                "args": ["-m", "tbmcp", "serve", "--read-only", "--toolsets", "mail,folders,search,accounts"],
            }
        }
    )


async def call(session: ClientSession, tool: str, **arguments: Any) -> dict[str, Any]:
    """Call one MCP tool and return its JSON payload."""
    result = await session.call_tool(tool, {k: v for k, v in arguments.items() if v is not None})
    text = "\n".join(getattr(block, "text", "") for block in result.content)
    if result.isError:
        raise RuntimeError(f"{tool} failed: {text}")
    if isinstance(result.structuredContent, dict):
        payload = result.structuredContent
        # FastMCP wraps non-object returns as {"result": ...}
        return payload["result"] if set(payload) == {"result"} and isinstance(payload["result"], dict) else payload
    return json.loads(text) if text else {}


# ------------------------------------------------------------------ link parsing


def _header(headers: dict[str, Any], name: str) -> str:
    value = headers.get(name) or headers.get(name.title()) or []
    return " ".join(value) if isinstance(value, list) else str(value)


def _clean(url: str) -> str:
    return html.unescape(url).strip().rstrip(".,;")


def extract_unsubscribe(message: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the unsubscribe options out of one `mail_get(detail="full")` payload.

    The List-Unsubscribe header (RFC 2369) is the reliable signal; a link in the
    body whose href or text says "unsubscribe" is the fallback for senders that
    only put it in the footer.
    """
    headers = message.get("headers") or {}
    header_uris = [_clean(u) for u in ANGLE_URI.findall(_header(headers, "list-unsubscribe"))]
    one_click = "one-click" in _header(headers, "list-unsubscribe-post").lower()

    body_links: list[str] = []
    for body, is_html in (
        (message.get("htmlBody"), True),
        (message.get("body"), bool(message.get("bodyIsHtml"))),
    ):
        if not body:
            continue
        if is_html:
            for _, href, text in ANCHOR.findall(body):
                label = html.unescape(TAG.sub(" ", text))
                if href.lower().startswith(("http", "mailto:")) and (
                    UNSUBSCRIBE_WORDS.search(label) or UNSUBSCRIBE_WORDS.search(href)
                ):
                    body_links.append(_clean(href))
        else:
            for line in body.splitlines():
                for url in URL.findall(line):
                    if UNSUBSCRIBE_WORDS.search(line) or UNSUBSCRIBE_WORDS.search(url):
                        body_links.append(_clean(url))

    web = [u for u in header_uris if u.lower().startswith("http")] + [u for u in body_links if u.lower().startswith("http")]
    mailto = [u for u in header_uris + body_links if u.lower().startswith("mailto:")]
    if not web and not mailto:
        return None
    return {
        "unsubscribe_url": web[0] if web else mailto[0],
        "mailto": mailto[0] if mailto else None,
        "source": "header" if header_uris else "body",
        "one_click": one_click and bool(web) and web[0] in header_uris,
    }


# ------------------------------------------------------------------ scanning


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _folders(session: ClientSession, scope: str) -> list[dict[str, Any]]:
    if scope == "inbox":
        listing = await call(session, "folder_list", special_use="inbox", include_counts=False, limit=500)
        return listing.get("items", [])
    listing = await call(session, "folder_list", depth=20, include_counts=False, limit=500)
    skip = {"trash", "junk", "drafts", "sent", "templates", "outbox"}
    return [
        f
        for f in listing.get("items", [])
        if not f.get("isRoot") and not f.get("isVirtual") and not f.get("isTag") and not f.get("isUnified")
        and not skip.intersection(f.get("specialUse") or [])
    ]


async def _list_recent(session: ClientSession, folder_id: str, limit: int, since: datetime | None) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    cursor = None
    while len(messages) < limit:
        result = await call(session, "mail_list", folder_id=folder_id, limit=min(200, limit - len(messages)), cursor=cursor)
        for item in result.get("items", []):
            date = _parse_date(item.get("date"))
            if since and date and date < since:
                return messages
            messages.append(item)
        cursor = result.get("nextCursor")
        if not cursor:
            break
    return messages


async def scan(scope: str = "inbox", max_per_folder: int = 100, days: int | None = 90, concurrency: int = 6) -> dict[str, Any]:
    """Scan every account and group the unsubscribable mail by sender."""
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    async with mcp_client().session("thunderbird") as session:
        accounts = await call(session, "account_list", include_settings=False)
        account_names = {a.get("key") or a.get("id"): a.get("name") for a in accounts.get("items", [])}
        folders = await _folders(session, scope)

        headers: list[tuple[dict[str, Any], dict[str, Any]]] = []
        errors: list[str] = []
        for folder in folders:
            try:
                for msg in await _list_recent(session, folder["id"], max_per_folder, since):
                    headers.append((folder, msg))
            except Exception as exc:  # one broken folder must not sink the whole scan
                errors.append(f"{folder.get('path') or folder.get('name')}: {exc}")

        gate = asyncio.Semaphore(concurrency)

        async def inspect(folder: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any] | None:
            async with gate:
                try:
                    full = await call(session, "mail_get", message_id=summary["id"], detail="full", decrypt=False)
                except Exception as exc:
                    errors.append(f"message {summary.get('id')}: {exc}")
                    return None
            found = extract_unsubscribe(full)
            if not found:
                return None
            name, address = parseaddr(summary.get("author") or "")
            return {
                **found,
                "message_id": summary["id"],
                "subject": summary.get("subject") or "(sin asunto)",
                "sender_name": name or address,
                "sender_email": address.lower(),
                "date": summary.get("date"),
                "account": account_names.get(folder.get("accountId"), folder.get("accountId")),
                "folder": folder.get("path") or folder.get("name"),
            }

        hits = [h for h in await asyncio.gather(*(inspect(f, m) for f, m in headers)) if h]

    # One row per sender: the newest message's link, plus how many emails it sent.
    by_sender: dict[str, dict[str, Any]] = {}
    for hit in sorted(hits, key=lambda h: str(h.get("date") or ""), reverse=True):
        key = hit["sender_email"] or hit["unsubscribe_url"]
        if key in by_sender:
            by_sender[key]["email_count"] += 1
        else:
            by_sender[key] = {**hit, "email_count": 1}
    candidates = sorted(by_sender.values(), key=lambda c: c["email_count"], reverse=True)
    for n, candidate in enumerate(candidates, 1):
        candidate["id"] = f"u{n}"

    return {
        "accounts_scanned": len(account_names),
        "folders_scanned": len(folders),
        "emails_scanned": len(headers),
        "emails_with_unsubscribe": len(hits),
        "candidates": candidates,
        "errors": errors[:20],
    }
