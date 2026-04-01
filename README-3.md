# 📋 Notion Task Autopilot MCP Server

**Your Notion database on autopilot.** A smart productivity layer that turns your Notion task database into an intelligent task management system — with daily standups, overdue alerts, session summaries, and bulk operations.

Not just another Notion wrapper. An opinionated productivity engine built for founders, freelancers, and teams who live in Notion.

## ✨ Features

| Tool | What it does |
|------|-------------|
| `notion_autopilot_daily_standup` | Auto-generated standup: in-progress, due today, overdue, blocked |
| `notion_autopilot_list_tasks` | Smart filtering: active, overdue, today, upcoming, done, blocked |
| `notion_autopilot_create_task` | Create tasks with smart defaults and auto-tagging |
| `notion_autopilot_update_status` | Bulk-update 1-20 tasks in a single call |
| `notion_autopilot_session_summary` | Create formatted session summaries as child pages |
| `notion_autopilot_overdue_check` | Dedicated overdue detection for alerts and automations |

### What Makes This Different

The official Notion MCP gives you raw CRUD. This gives you **workflows**:

- 🚀 **Daily Standup in one call** — not 4 separate queries you assemble yourself
- ⚠️ **Overdue detection** — scans non-completed tasks against due dates automatically
- 📝 **Session summaries** — Markdown content auto-converted to proper Notion blocks
- 🔄 **Bulk operations** — update 20 tasks in one call, not 20 separate API calls
- 🏷️ **Fully configurable** — property names, status values, all via environment variables

### Configurable Property Names

Every Notion database is different. Configure everything via env vars:

```bash
NOTION_PROP_TITLE="Name"              # or "Task", "Title", "Aufgabe"
NOTION_PROP_STATUS="Status"           # any status property
NOTION_PROP_PRIORITY="Priority"       # or "Priorität", "Urgency"
NOTION_PROP_DUE_DATE="Due Date"       # or "Deadline", "Fällig am"
NOTION_PROP_PROJECT="Project"         # or "Projekt", "Category"
NOTION_PROP_TAGS="Tags"               # multi-select property

NOTION_STATUS_TODO="To Do"            # or "Offen", "Open"
NOTION_STATUS_IN_PROGRESS="In Progress"  # or "In Arbeit", "Doing"
NOTION_STATUS_DONE="Done"             # or "Erledigt", "Completed"
NOTION_STATUS_BLOCKED="Blocked"       # or "Blockiert", "Waiting"
```

## 🚀 Quick Start

### 1. Create a Notion Integration

Go to [Notion Integrations](https://www.notion.so/my-integrations) → New Integration → Copy the API key.

**Then share your task database** with the integration (click ••• in the database → Add connections → select your integration).

### 2. Install

```bash
pip install notion-autopilot-mcp
```

### 3. Configure

```bash
export NOTION_API_KEY="ntn_your_key_here"
export NOTION_DATABASE_ID="your_database_id"
export NOTION_SUMMARIES_PAGE_ID="page_id_for_summaries"  # optional
```

### 4. Add to your MCP client

```json
{
  "mcpServers": {
    "notion-autopilot": {
      "command": "python",
      "args": ["-m", "server"],
      "env": {
        "NOTION_API_KEY": "ntn_your_key",
        "NOTION_DATABASE_ID": "your_db_id",
        "NOTION_PROP_STATUS": "Status",
        "NOTION_STATUS_TODO": "To Do",
        "NOTION_STATUS_DONE": "Done"
      }
    }
  }
}
```

## 📋 Example Output

### Daily Standup
```
# 🚀 Daily Standup
**Tuesday, April 01, 2026**

---

### 🔄 In Progress (3)
- 🔄 🔴 **Build Morning Briefing MCP** — In Progress | Due: 2026-04-02 | Project: NEXUS
- 🔄 🟡 **LinkedIn Profile Optimization** — In Progress | Project: Marketing
- 🔄 🟢 **Update SHOTVO landing page** — In Progress

### 📅 Due Today (1)
- 📋 🔴 **Send SCIO demo follow-up** — To Do | Due: 2026-04-01 | Project: SCIO

### ⚠️ Overdue (2)
- 📋 🔴 **Renew Meta Access Token** — To Do | Due: 2026-03-28 ⚠️ OVERDUE
- 🔄 🟡 **Fix n8n webhook timeout** — In Progress | Due: 2026-03-30 ⚠️ OVERDUE

---
*Powered by Notion Task Autopilot MCP — LIMITLESS Automation*
```

## 🛠️ Use Cases

- **Morning briefing**: Combine with Morning Briefing MCP for a complete daily overview
- **End-of-session sync**: Create a session summary and bulk-update task statuses
- **Slack/Telegram alerts**: Pipe overdue checks into messaging via n8n/Zapier
- **Weekly reviews**: List completed tasks and generate progress reports
- **Team standups**: Auto-generate standup notes from your shared Notion board

## 🔒 Security

- Uses Notion's official API with integration tokens
- Read and write operations clearly annotated (readOnlyHint)
- No data stored — all queries are live against your Notion workspace
- Supports granular integration permissions

## 📄 License

MIT — Built by [LIMITLESS Automation](https://limitless-automation.com)
