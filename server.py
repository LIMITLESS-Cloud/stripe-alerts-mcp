"""
Notion Task Autopilot MCP Server
==================================
Smart task management layer on top of Notion: automated status updates,
session summaries, daily standups, overdue detection, and priority sorting.

Not just another Notion wrapper — an opinionated productivity engine.

Built by LIMITLESS Automation | https://limitless-automation.com
"""

import json
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from enum import Enum

import httpx
from pydantic import BaseModel, Field, ConfigDict, field_validator
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_SUMMARIES_PAGE_ID = os.environ.get("NOTION_SUMMARIES_PAGE_ID", "")
NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"
HTTP_TIMEOUT = 20.0

# Configurable property names (every Notion DB is different)
PROP_TITLE = os.environ.get("NOTION_PROP_TITLE", "Name")
PROP_STATUS = os.environ.get("NOTION_PROP_STATUS", "Status")
PROP_PRIORITY = os.environ.get("NOTION_PROP_PRIORITY", "Priority")
PROP_DUE_DATE = os.environ.get("NOTION_PROP_DUE_DATE", "Due Date")
PROP_TAGS = os.environ.get("NOTION_PROP_TAGS", "Tags")
PROP_PROJECT = os.environ.get("NOTION_PROP_PROJECT", "Project")
PROP_ASSIGNEE = os.environ.get("NOTION_PROP_ASSIGNEE", "Assignee")

# Status values (configurable)
STATUS_TODO = os.environ.get("NOTION_STATUS_TODO", "To Do")
STATUS_IN_PROGRESS = os.environ.get("NOTION_STATUS_IN_PROGRESS", "In Progress")
STATUS_DONE = os.environ.get("NOTION_STATUS_DONE", "Done")
STATUS_BLOCKED = os.environ.get("NOTION_STATUS_BLOCKED", "Blocked")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notion_autopilot_mcp")

# ---------------------------------------------------------------------------
# FastMCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("notion_autopilot_mcp")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _notion_headers() -> Dict[str, str]:
    """Standard Notion API headers."""
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


async def _notion_post(endpoint: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Authenticated POST to Notion API."""
    if not NOTION_API_KEY:
        return {"error": "NOTION_API_KEY not set. Create an integration at https://www.notion.so/my-integrations"}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{NOTION_BASE}/{endpoint}",
            headers=_notion_headers(),
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


async def _notion_patch(endpoint: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Authenticated PATCH to Notion API."""
    if not NOTION_API_KEY:
        return {"error": "NOTION_API_KEY not set."}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.patch(
            f"{NOTION_BASE}/{endpoint}",
            headers=_notion_headers(),
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


def _handle_notion_error(e: Exception) -> str:
    """Format Notion API errors into actionable messages."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        try:
            body = e.response.json()
            msg = body.get("message", "Unknown error")
        except Exception:
            msg = str(e)

        if code == 401:
            return "Error: Invalid Notion API key. Check NOTION_API_KEY."
        elif code == 403:
            return f"Error: Integration doesn't have access. Share the database with your integration. ({msg})"
        elif code == 404:
            return f"Error: Database or page not found. Check NOTION_DATABASE_ID. ({msg})"
        elif code == 429:
            return "Error: Notion rate limit hit. Wait a moment and retry."
        return f"Error: Notion API returned {code} — {msg}"
    elif isinstance(e, httpx.TimeoutException):
        return "Error: Notion request timed out. Try again."
    return f"Error: {type(e).__name__}: {e}"


def _extract_title(page: Dict) -> str:
    """Extract title text from a Notion page."""
    props = page.get("properties", {})
    title_prop = props.get(PROP_TITLE, {})
    title_arr = title_prop.get("title", [])
    if title_arr:
        return title_arr[0].get("plain_text", "Untitled")
    return "Untitled"


def _extract_prop_value(page: Dict, prop_name: str) -> Optional[str]:
    """Extract a property value from a Notion page (select, status, date, rich_text)."""
    props = page.get("properties", {})
    prop = props.get(prop_name, {})
    prop_type = prop.get("type", "")

    if prop_type == "select" and prop.get("select"):
        return prop["select"].get("name")
    elif prop_type == "status" and prop.get("status"):
        return prop["status"].get("name")
    elif prop_type == "date" and prop.get("date"):
        return prop["date"].get("start")
    elif prop_type == "rich_text" and prop.get("rich_text"):
        return prop["rich_text"][0].get("plain_text", "")
    elif prop_type == "multi_select":
        return ", ".join(s.get("name", "") for s in prop.get("multi_select", []))
    elif prop_type == "people":
        return ", ".join(p.get("name", "Unknown") for p in prop.get("people", []))
    return None


def _priority_emoji(priority: Optional[str]) -> str:
    """Map priority values to emoji."""
    if not priority:
        return "⚪"
    p = priority.lower()
    if p in ("high", "hoch", "urgent", "dringend", "critical"):
        return "🔴"
    elif p in ("medium", "mittel", "normal"):
        return "🟡"
    elif p in ("low", "niedrig", "gering"):
        return "🟢"
    return "⚪"


def _status_emoji(status: Optional[str]) -> str:
    """Map status values to emoji."""
    if not status:
        return "❓"
    s = status.lower()
    if s in ("done", "erledigt", "completed", "fertig"):
        return "✅"
    elif s in ("in progress", "in arbeit", "doing", "aktiv"):
        return "🔄"
    elif s in ("to do", "todo", "offen", "open", "geplant"):
        return "📋"
    elif s in ("blocked", "blockiert", "waiting"):
        return "🚫"
    return "📌"


def _is_overdue(date_str: Optional[str]) -> bool:
    """Check if a date string is in the past."""
    if not date_str:
        return False
    try:
        due = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        return due < datetime.now(timezone.utc)
    except (ValueError, AttributeError):
        return False


def _format_task_md(page: Dict, index: Optional[int] = None) -> str:
    """Format a single task as a Markdown line."""
    title = _extract_title(page)
    status = _extract_prop_value(page, PROP_STATUS)
    priority = _extract_prop_value(page, PROP_PRIORITY)
    due = _extract_prop_value(page, PROP_DUE_DATE)
    project = _extract_prop_value(page, PROP_PROJECT)

    prefix = f"{index}." if index else "-"
    line = f"{prefix} {_status_emoji(status)} {_priority_emoji(priority)} **{title}**"

    details = []
    if status:
        details.append(status)
    if due:
        overdue_tag = " ⚠️ OVERDUE" if _is_overdue(due) else ""
        details.append(f"Due: {due}{overdue_tag}")
    if project:
        details.append(f"Project: {project}")

    if details:
        line += f" — {' | '.join(details)}"

    return line


# ---------------------------------------------------------------------------
# Input Models
# ---------------------------------------------------------------------------

class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class ListTasksInput(BaseModel):
    """Input for listing tasks with smart filtering."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    filter_mode: str = Field(
        default="active",
        description="Filter: 'active' (To Do + In Progress), 'overdue', 'today', "
                    "'upcoming' (next 7 days), 'done', 'blocked', or 'all'.",
    )
    project: Optional[str] = Field(
        default=None,
        description="Filter by project name (optional).",
        max_length=100,
    )
    limit: int = Field(default=20, description="Max tasks to return.", ge=1, le=100)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("filter_mode")
    @classmethod
    def validate_filter(cls, v: str) -> str:
        allowed = ("active", "overdue", "today", "upcoming", "done", "blocked", "all")
        if v not in allowed:
            raise ValueError(f"filter_mode must be one of: {', '.join(allowed)}")
        return v


class CreateTaskInput(BaseModel):
    """Input for creating a new task."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(
        ..., description="Task title.", min_length=1, max_length=500,
    )
    status: Optional[str] = Field(
        default=None,
        description="Task status (e.g., 'To Do', 'In Progress'). Default: To Do.",
    )
    priority: Optional[str] = Field(
        default=None,
        description="Priority level (e.g., 'High', 'Medium', 'Low').",
    )
    due_date: Optional[str] = Field(
        default=None,
        description="Due date in ISO format (e.g., '2026-04-15').",
    )
    project: Optional[str] = Field(
        default=None,
        description="Project name to tag the task with.",
        max_length=100,
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Tags to apply to the task.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class UpdateStatusInput(BaseModel):
    """Input for updating task statuses."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    page_ids: List[str] = Field(
        ..., description="List of Notion page IDs to update.", min_length=1, max_length=20,
    )
    new_status: str = Field(
        ..., description="New status value (e.g., 'Done', 'In Progress', 'To Do').",
        min_length=1,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class SessionSummaryInput(BaseModel):
    """Input for creating a session summary page."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(
        ..., description="Summary title (e.g., 'NEXUS Session — April 1').",
        min_length=1, max_length=300,
    )
    content: str = Field(
        ..., description="Summary content in plain text or Markdown. "
                         "Will be split into Notion blocks automatically.",
        min_length=1,
    )
    parent_page_id: Optional[str] = Field(
        default=None,
        description="Parent page ID for the summary. "
                    "Default: NOTION_SUMMARIES_PAGE_ID environment variable.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class DailyStandupInput(BaseModel):
    """Input for daily standup generation."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    include_overdue: bool = Field(default=True, description="Highlight overdue tasks.")
    include_blocked: bool = Field(default=True, description="Show blocked tasks.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class OverdueCheckInput(BaseModel):
    """Input for overdue task detection."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------

def _build_filter(filter_mode: str, project: Optional[str] = None) -> Dict[str, Any]:
    """Build Notion database query filter."""
    conditions: List[Dict] = []

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    week_str = (now + timedelta(days=7)).strftime("%Y-%m-%d")

    if filter_mode == "active":
        conditions.append({
            "or": [
                {"property": PROP_STATUS, "status": {"equals": STATUS_TODO}},
                {"property": PROP_STATUS, "status": {"equals": STATUS_IN_PROGRESS}},
            ]
        })
    elif filter_mode == "overdue":
        conditions.append(
            {"property": PROP_DUE_DATE, "date": {"before": today_str}}
        )
        conditions.append({
            "or": [
                {"property": PROP_STATUS, "status": {"equals": STATUS_TODO}},
                {"property": PROP_STATUS, "status": {"equals": STATUS_IN_PROGRESS}},
                {"property": PROP_STATUS, "status": {"equals": STATUS_BLOCKED}},
            ]
        })
    elif filter_mode == "today":
        conditions.append(
            {"property": PROP_DUE_DATE, "date": {"equals": today_str}}
        )
    elif filter_mode == "upcoming":
        conditions.append(
            {"property": PROP_DUE_DATE, "date": {"on_or_after": today_str}}
        )
        conditions.append(
            {"property": PROP_DUE_DATE, "date": {"on_or_before": week_str}}
        )
    elif filter_mode == "done":
        conditions.append(
            {"property": PROP_STATUS, "status": {"equals": STATUS_DONE}}
        )
    elif filter_mode == "blocked":
        conditions.append(
            {"property": PROP_STATUS, "status": {"equals": STATUS_BLOCKED}}
        )
    # "all" → no status filter

    if project:
        conditions.append(
            {"property": PROP_PROJECT, "select": {"equals": project}}
        )

    if not conditions:
        return {}
    if len(conditions) == 1:
        return {"filter": conditions[0]}
    return {"filter": {"and": conditions}}


def _build_sorts() -> List[Dict]:
    """Default sorting: priority first, then due date."""
    return [
        {"property": PROP_DUE_DATE, "direction": "ascending"},
    ]


def _text_to_blocks(text: str) -> List[Dict]:
    """Convert plain text/markdown to Notion blocks (paragraphs + headings)."""
    blocks: List[Dict] = []
    lines = text.strip().split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Detect markdown headings
        if stripped.startswith("### "):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": stripped[4:]}}]
                },
            })
        elif stripped.startswith("## "):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": stripped[3:]}}]
                },
            })
        elif stripped.startswith("# "):
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": stripped[2:]}}]
                },
            })
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": stripped[2:]}}]
                },
            })
        elif stripped.startswith("---"):
            blocks.append({
                "object": "block",
                "type": "divider",
                "divider": {},
            })
        else:
            # Notion block content limit is 2000 chars
            content = stripped[:2000]
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                },
            })

    return blocks[:100]  # Notion limit: 100 blocks per request


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="notion_autopilot_list_tasks",
    annotations={
        "title": "List & Filter Tasks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def notion_autopilot_list_tasks(params: ListTasksInput) -> str:
    """List tasks from your Notion database with smart filtering.

    Supports multiple filter modes: active tasks, overdue items, today's tasks,
    upcoming (7 days), done, blocked, or all. Optionally filter by project.

    Args:
        params (ListTasksInput): Query parameters including:
            - filter_mode (str): 'active', 'overdue', 'today', 'upcoming', 'done', 'blocked', 'all'
            - project (str): Optional project name filter
            - limit (int): Max tasks (1-100)
            - response_format (str): Output format

    Returns:
        str: Filtered task list in the requested format
    """
    if not NOTION_DATABASE_ID:
        return "Error: NOTION_DATABASE_ID not set. Set the environment variable to your task database ID."

    query_body: Dict[str, Any] = {
        "page_size": params.limit,
        "sorts": _build_sorts(),
    }

    filter_obj = _build_filter(params.filter_mode, params.project)
    if "filter" in filter_obj:
        query_body["filter"] = filter_obj["filter"]

    try:
        data = await _notion_post(f"databases/{NOTION_DATABASE_ID}/query", query_body)
    except Exception as e:
        return _handle_notion_error(e)

    pages = data.get("results", [])

    if params.response_format == ResponseFormat.JSON:
        tasks = []
        for p in pages:
            tasks.append({
                "id": p["id"],
                "title": _extract_title(p),
                "status": _extract_prop_value(p, PROP_STATUS),
                "priority": _extract_prop_value(p, PROP_PRIORITY),
                "due_date": _extract_prop_value(p, PROP_DUE_DATE),
                "project": _extract_prop_value(p, PROP_PROJECT),
                "tags": _extract_prop_value(p, PROP_TAGS),
                "url": p.get("url", ""),
                "overdue": _is_overdue(_extract_prop_value(p, PROP_DUE_DATE)),
            })
        return json.dumps({"tasks": tasks, "count": len(tasks), "filter": params.filter_mode}, indent=2)

    # Markdown
    label_map = {
        "active": "Active Tasks", "overdue": "⚠️ Overdue Tasks",
        "today": "Today's Tasks", "upcoming": "Upcoming (7 Days)",
        "done": "Completed Tasks", "blocked": "Blocked Tasks", "all": "All Tasks",
    }
    label = label_map.get(params.filter_mode, "Tasks")
    if params.project:
        label += f" — {params.project}"

    if not pages:
        return f"### 📋 {label}\n\nNo tasks found."

    lines = [f"### 📋 {label} ({len(pages)})", ""]
    for i, p in enumerate(pages, 1):
        lines.append(_format_task_md(p, index=i))

    return "\n".join(lines)


@mcp.tool(
    name="notion_autopilot_create_task",
    annotations={
        "title": "Create New Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def notion_autopilot_create_task(params: CreateTaskInput) -> str:
    """Create a new task in your Notion database with smart defaults.

    Automatically sets status to 'To Do' if not specified. Supports priority,
    due dates, project tags, and custom tags.

    Args:
        params (CreateTaskInput): Task parameters including:
            - title (str): Task title (required)
            - status (str): Status value (default: To Do)
            - priority (str): Priority level
            - due_date (str): Due date in ISO format
            - project (str): Project name
            - tags (list): Tags to apply
            - response_format (str): Output format

    Returns:
        str: Confirmation with task details and Notion URL
    """
    if not NOTION_DATABASE_ID:
        return "Error: NOTION_DATABASE_ID not set."

    properties: Dict[str, Any] = {
        PROP_TITLE: {
            "title": [{"text": {"content": params.title}}]
        },
        PROP_STATUS: {
            "status": {"name": params.status or STATUS_TODO}
        },
    }

    if params.priority:
        properties[PROP_PRIORITY] = {"select": {"name": params.priority}}
    if params.due_date:
        properties[PROP_DUE_DATE] = {"date": {"start": params.due_date}}
    if params.project:
        properties[PROP_PROJECT] = {"select": {"name": params.project}}
    if params.tags:
        properties[PROP_TAGS] = {
            "multi_select": [{"name": t} for t in params.tags]
        }

    body = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
    }

    try:
        result = await _notion_post("pages", body)
    except Exception as e:
        return _handle_notion_error(e)

    page_id = result.get("id", "")
    url = result.get("url", "")

    if params.response_format == ResponseFormat.JSON:
        return json.dumps({
            "created": True,
            "page_id": page_id,
            "title": params.title,
            "status": params.status or STATUS_TODO,
            "url": url,
        }, indent=2)

    return (
        f"✅ **Task created:** {params.title}\n"
        f"Status: {_status_emoji(params.status or STATUS_TODO)} {params.status or STATUS_TODO}"
        + (f" | Priority: {_priority_emoji(params.priority)} {params.priority}" if params.priority else "")
        + (f" | Due: {params.due_date}" if params.due_date else "")
        + (f" | Project: {params.project}" if params.project else "")
        + f"\n🔗 {url}"
    )


@mcp.tool(
    name="notion_autopilot_update_status",
    annotations={
        "title": "Bulk Update Task Status",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def notion_autopilot_update_status(params: UpdateStatusInput) -> str:
    """Update the status of one or more tasks at once.

    Batch-update tasks — perfect for marking multiple items as done after a
    work session, or moving tasks from 'To Do' to 'In Progress'.

    Args:
        params (UpdateStatusInput): Update parameters including:
            - page_ids (list): Notion page IDs to update (1-20)
            - new_status (str): New status value
            - response_format (str): Output format

    Returns:
        str: Update confirmation with results per task
    """
    results = []
    for page_id in params.page_ids:
        try:
            resp = await _notion_patch(f"pages/{page_id}", {
                "properties": {
                    PROP_STATUS: {"status": {"name": params.new_status}}
                }
            })
            title = _extract_title(resp)
            results.append({"page_id": page_id, "title": title, "status": "updated", "new_status": params.new_status})
        except Exception as e:
            results.append({"page_id": page_id, "status": "failed", "error": _handle_notion_error(e)})

    if params.response_format == ResponseFormat.JSON:
        return json.dumps({"results": results, "updated": sum(1 for r in results if r["status"] == "updated")}, indent=2)

    lines = [f"### 🔄 Status Update → {params.new_status}", ""]
    for r in results:
        if r["status"] == "updated":
            lines.append(f"- ✅ **{r.get('title', r['page_id'])}** → {_status_emoji(params.new_status)} {params.new_status}")
        else:
            lines.append(f"- ❌ `{r['page_id']}` — {r.get('error', 'Unknown error')}")

    success = sum(1 for r in results if r["status"] == "updated")
    lines.append(f"\n**{success}/{len(results)}** tasks updated.")
    return "\n".join(lines)


@mcp.tool(
    name="notion_autopilot_session_summary",
    annotations={
        "title": "Create Session Summary",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def notion_autopilot_session_summary(params: SessionSummaryInput) -> str:
    """Create a session summary as a child page in Notion.

    Perfect for documenting work sessions, decisions, and next steps.
    Content is automatically converted to Notion blocks (headings, lists,
    paragraphs, dividers).

    Args:
        params (SessionSummaryInput): Summary parameters including:
            - title (str): Page title
            - content (str): Summary content (plain text or Markdown)
            - parent_page_id (str): Parent page for the summary
            - response_format (str): Output format

    Returns:
        str: Confirmation with the new page URL
    """
    parent_id = params.parent_page_id or NOTION_SUMMARIES_PAGE_ID
    if not parent_id:
        return "Error: No parent page ID. Set NOTION_SUMMARIES_PAGE_ID or provide parent_page_id."

    blocks = _text_to_blocks(params.content)

    # Add metadata footer
    now = datetime.now(timezone.utc)
    blocks.append({
        "object": "block", "type": "divider", "divider": {},
    })
    blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{
                "type": "text",
                "text": {"content": f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')} | Notion Autopilot MCP"},
                "annotations": {"italic": True, "color": "gray"},
            }]
        },
    })

    body = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {"title": [{"text": {"content": params.title}}]}
        },
        "children": blocks,
    }

    try:
        result = await _notion_post("pages", body)
    except Exception as e:
        return _handle_notion_error(e)

    url = result.get("url", "")
    page_id = result.get("id", "")

    if params.response_format == ResponseFormat.JSON:
        return json.dumps({
            "created": True,
            "page_id": page_id,
            "title": params.title,
            "url": url,
            "block_count": len(blocks),
        }, indent=2)

    return f"✅ **Session summary created:** {params.title}\n📄 {len(blocks)} blocks\n🔗 {url}"


@mcp.tool(
    name="notion_autopilot_daily_standup",
    annotations={
        "title": "Generate Daily Standup",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def notion_autopilot_daily_standup(params: DailyStandupInput) -> str:
    """Generate a daily standup report from your Notion tasks.

    Automatically compiles: what's in progress, what's due today, overdue items,
    and blocked tasks — the perfect morning briefing for productivity.

    Args:
        params (DailyStandupInput): Standup configuration including:
            - include_overdue (bool): Show overdue tasks
            - include_blocked (bool): Show blocked tasks
            - response_format (str): Output format

    Returns:
        str: Structured standup report
    """
    if not NOTION_DATABASE_ID:
        return "Error: NOTION_DATABASE_ID not set."

    standup_data: Dict[str, Any] = {}
    sections_md: List[str] = [
        "# 🚀 Daily Standup",
        f"**{datetime.now().strftime('%A, %B %d, %Y')}**",
        "",
        "---",
    ]

    # In Progress
    try:
        in_progress = await _notion_post(f"databases/{NOTION_DATABASE_ID}/query", {
            "filter": {"property": PROP_STATUS, "status": {"equals": STATUS_IN_PROGRESS}},
            "page_size": 20,
        })
        ip_pages = in_progress.get("results", [])
        standup_data["in_progress"] = len(ip_pages)

        sections_md.append(f"### 🔄 In Progress ({len(ip_pages)})")
        sections_md.append("")
        if ip_pages:
            for p in ip_pages:
                sections_md.append(_format_task_md(p))
        else:
            sections_md.append("Nothing in progress. Time to pick up a task!")
        sections_md.append("")
    except Exception as e:
        sections_md.append(f"⚠️ Could not fetch in-progress tasks: {_handle_notion_error(e)}")

    # Due Today
    try:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_tasks = await _notion_post(f"databases/{NOTION_DATABASE_ID}/query", {
            "filter": {"property": PROP_DUE_DATE, "date": {"equals": today_str}},
            "page_size": 20,
        })
        today_pages = today_tasks.get("results", [])
        standup_data["due_today"] = len(today_pages)

        sections_md.append(f"### 📅 Due Today ({len(today_pages)})")
        sections_md.append("")
        if today_pages:
            for p in today_pages:
                sections_md.append(_format_task_md(p))
        else:
            sections_md.append("No deadlines today. Focus on high-impact work!")
        sections_md.append("")
    except Exception as e:
        sections_md.append(f"⚠️ Could not fetch today's tasks: {_handle_notion_error(e)}")

    # Overdue
    if params.include_overdue:
        try:
            overdue_filter = _build_filter("overdue")
            overdue_query: Dict[str, Any] = {"page_size": 10}
            if "filter" in overdue_filter:
                overdue_query["filter"] = overdue_filter["filter"]

            overdue_data = await _notion_post(f"databases/{NOTION_DATABASE_ID}/query", overdue_query)
            overdue_pages = overdue_data.get("results", [])
            standup_data["overdue"] = len(overdue_pages)

            if overdue_pages:
                sections_md.append(f"### ⚠️ Overdue ({len(overdue_pages)})")
                sections_md.append("")
                for p in overdue_pages:
                    sections_md.append(_format_task_md(p))
                sections_md.append("")
        except Exception as e:
            sections_md.append(f"⚠️ Overdue check failed: {_handle_notion_error(e)}")

    # Blocked
    if params.include_blocked:
        try:
            blocked = await _notion_post(f"databases/{NOTION_DATABASE_ID}/query", {
                "filter": {"property": PROP_STATUS, "status": {"equals": STATUS_BLOCKED}},
                "page_size": 10,
            })
            blocked_pages = blocked.get("results", [])
            standup_data["blocked"] = len(blocked_pages)

            if blocked_pages:
                sections_md.append(f"### 🚫 Blocked ({len(blocked_pages)})")
                sections_md.append("")
                for p in blocked_pages:
                    sections_md.append(_format_task_md(p))
                sections_md.append("")
        except Exception as e:
            sections_md.append(f"⚠️ Blocked check failed: {_handle_notion_error(e)}")

    sections_md.extend([
        "---",
        "*Powered by Notion Task Autopilot MCP — LIMITLESS Automation*",
    ])

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(standup_data, indent=2)

    return "\n".join(sections_md)


@mcp.tool(
    name="notion_autopilot_overdue_check",
    annotations={
        "title": "Overdue Task Alert",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def notion_autopilot_overdue_check(params: OverdueCheckInput) -> str:
    """Check for overdue tasks that need immediate attention.

    Scans all non-completed tasks for past due dates and returns them
    sorted by urgency. Use this in automated alerts or morning briefings.

    Args:
        params (OverdueCheckInput): Check parameters including:
            - response_format (str): Output format

    Returns:
        str: List of overdue tasks or all-clear confirmation
    """
    if not NOTION_DATABASE_ID:
        return "Error: NOTION_DATABASE_ID not set."

    overdue_filter = _build_filter("overdue")
    query: Dict[str, Any] = {"page_size": 50, "sorts": _build_sorts()}
    if "filter" in overdue_filter:
        query["filter"] = overdue_filter["filter"]

    try:
        data = await _notion_post(f"databases/{NOTION_DATABASE_ID}/query", query)
    except Exception as e:
        return _handle_notion_error(e)

    pages = data.get("results", [])

    if params.response_format == ResponseFormat.JSON:
        tasks = [{
            "id": p["id"],
            "title": _extract_title(p),
            "due_date": _extract_prop_value(p, PROP_DUE_DATE),
            "status": _extract_prop_value(p, PROP_STATUS),
            "priority": _extract_prop_value(p, PROP_PRIORITY),
            "url": p.get("url", ""),
        } for p in pages]
        return json.dumps({"overdue_tasks": tasks, "count": len(tasks)}, indent=2)

    if not pages:
        return "### ✅ Overdue Check\n\nAll clear! No overdue tasks. Keep it up! 🎯"

    lines = [f"### ⚠️ Overdue Tasks ({len(pages)})", ""]
    for i, p in enumerate(pages, 1):
        lines.append(_format_task_md(p, index=i))

    lines.append(f"\n**{len(pages)} task(s) need attention.**")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
