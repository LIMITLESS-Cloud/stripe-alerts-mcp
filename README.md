# 💼 Stripe Business Alerts MCP Server

**Never miss a failed payment again.** A real-time business intelligence MCP server that monitors your Stripe account for failed payments, tracks MRR, subscription changes, and revenue — all accessible from your AI assistant.

Built for SaaS founders, freelancers, and small business owners who want their AI to watch their revenue while they focus on building.

## ✨ Features

| Tool | What it does |
|------|-------------|
| `stripe_alerts_daily_digest` | Complete daily business digest — all metrics in one call |
| `stripe_alerts_overview` | Business health: active subs, MRR, past-due accounts |
| `stripe_alerts_failed_payments` | Find failed & incomplete payments that need attention |
| `stripe_alerts_revenue` | Revenue snapshot: today, yesterday, week, or month |
| `stripe_alerts_subscriptions` | Track new signups, cancellations, and plan changes |

### Why This Matters

- 💸 **Catch revenue leaks**: Failed payments silently drain SaaS revenue. This catches them immediately.
- 📊 **Know your MRR**: Automatic calculation from all active subscriptions, multi-currency support.
- 📉 **Track churn in real-time**: See cancellations the moment they happen, not at month-end.
- 🤖 **AI-native**: Designed for Claude, ChatGPT, Cursor — not another dashboard you won't check.

### Multi-Currency Support

Automatic detection and formatting for EUR, USD, GBP, CHF, JPY, CAD, AUD, and more.

## 🚀 Quick Start

### 1. Get Your Stripe API Key

Go to [Stripe Dashboard → API Keys](https://dashboard.stripe.com/apikeys) and copy your **Secret Key** (starts with `sk_live_` or `sk_test_`).

> ⚠️ Use a **Restricted Key** with read-only access for maximum security. Required permissions: Charges (Read), Payment Intents (Read), Subscriptions (Read), Events (Read).

### 2. Install

```bash
pip install stripe-alerts-mcp
```

### 3. Configure

```bash
export STRIPE_API_KEY="sk_live_your_key_here"
export STRIPE_DEFAULT_CURRENCY="eur"     # optional, default: eur
export STRIPE_LOOKBACK_DAYS="7"          # optional, default: 7
```

### 4. Add to your MCP client

**Claude Desktop / Cursor / VS Code:**

```json
{
  "mcpServers": {
    "stripe-alerts": {
      "command": "python",
      "args": ["-m", "server"],
      "env": {
        "STRIPE_API_KEY": "sk_live_your_key_here"
      }
    }
  }
}
```

## 📋 Example Output

### Daily Digest
```
# 💼 Stripe Daily Digest
**Tuesday, April 01, 2026** — Generated at 07:00 UTC

---

### 📊 Business Health Overview

🟢 **Active Subscriptions:** 47
💰 **Monthly Recurring Revenue (MRR):** €2,847.00
🔵 **Trialing:** 3
🔴 **Past Due:** 2 ⚠️ Attention needed!

### 💰 Revenue — Today (01.04.2026)

**Total:** €489.00
**Transactions:** 8

**Top transactions:**
- €149.00 — Enterprise Plan (Annual)
- €79.00 — Pro Plan
- €58.00 — LIMITLESS SPS Generator

### ✅ Failed Payments

No failed payments found. All clear!

### 🔄 Subscription Changes (3 events)

**🟢 New Subscriptions (2):**
  - Customer cus_abc123 — €29.99/mo
  - Customer cus_def456 — €14.99/mo

**🚫 Cancellations (1):**
  - Customer cus_ghi789 — Reason: too_expensive

**Net Change:** 📈 +1

---
*Powered by Stripe Business Alerts MCP — LIMITLESS Automation*
```

## 🛠️ Use Cases

- **Morning briefings**: "How's my business doing today?" — one tool call, full picture.
- **Failed payment alerts**: Pipe into Slack/Telegram via n8n for instant notifications.
- **Weekly reports**: Automate business reports with the daily digest tool.
- **Churn monitoring**: Track cancellations and reasons in real-time.
- **Revenue forecasting**: Feed JSON output into dashboards or spreadsheets.

## 🔒 Security

- Uses Stripe's official REST API with key-based auth
- All tools are **read-only** — no writes, no modifications, no risk
- Supports restricted API keys for minimal permissions
- No data stored — all queries are live

## 📄 License

MIT — Built by [LIMITLESS Automation](https://limitless-automation.com)

## 🚀 Get Pro

Free tier available on [MCPize](https://mcpize.com/mcp/stripe-alerts) — 50 requests/month, no credit card needed. Upgrade to Pro for daily digests and unlimited alerts.

[![Available on MCPize](https://img.shields.io/badge/MCPize-Available-purple)](https://mcpize.com/mcp/stripe-alerts)
