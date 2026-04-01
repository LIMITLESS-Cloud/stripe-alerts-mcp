"""
Stripe Business Alerts MCP Server
===================================
Real-time business intelligence from your Stripe account: failed payments,
MRR tracking, subscription changes, and revenue snapshots — all as MCP tools.

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

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")
STRIPE_BASE = "https://api.stripe.com/v1"
HTTP_TIMEOUT = 20.0
DEFAULT_CURRENCY = os.environ.get("STRIPE_DEFAULT_CURRENCY", "eur")
DEFAULT_LOOKBACK_DAYS = int(os.environ.get("STRIPE_LOOKBACK_DAYS", "7"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stripe_alerts_mcp")

# ---------------------------------------------------------------------------
# FastMCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("stripe_alerts_mcp")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _stripe_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Authenticated GET request to Stripe API."""
    if not STRIPE_API_KEY:
        return {"error": "STRIPE_API_KEY not set. Get your key at https://dashboard.stripe.com/apikeys"}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(
            f"{STRIPE_BASE}/{endpoint}",
            params=params or {},
            auth=(STRIPE_API_KEY, ""),
        )
        resp.raise_for_status()
        return resp.json()


def _cents_to_amount(cents: int, currency: str = "eur") -> str:
    """Convert Stripe amount (cents) to human-readable format."""
    symbols = {
        "eur": "€", "usd": "$", "gbp": "£", "chf": "CHF ",
        "jpy": "¥", "cad": "CA$", "aud": "AU$",
    }
    symbol = symbols.get(currency.lower(), f"{currency.upper()} ")
    # JPY has no decimal places
    if currency.lower() == "jpy":
        return f"{symbol}{cents:,}"
    return f"{symbol}{cents / 100:,.2f}"


def _ts_to_date(timestamp: int) -> str:
    """Convert Unix timestamp to human-readable date."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _ts_to_short(timestamp: int) -> str:
    """Convert Unix timestamp to short date."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%d.%m.%Y")


def _days_ago_ts(days: int) -> int:
    """Get Unix timestamp for N days ago."""
    return int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())


def _status_emoji(status: str) -> str:
    """Map Stripe statuses to emoji."""
    mapping = {
        "succeeded": "✅", "paid": "✅",
        "failed": "❌", "incomplete": "⚠️",
        "past_due": "🔴", "canceled": "🚫",
        "active": "🟢", "trialing": "🔵",
        "unpaid": "🟡", "incomplete_expired": "⛔",
        "requires_payment_method": "💳", "requires_action": "⏳",
        "open": "📄", "draft": "📝", "void": "🗑️",
    }
    return mapping.get(status, "❓")


def _handle_stripe_error(e: Exception) -> str:
    """Format Stripe API errors into actionable messages."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        try:
            body = e.response.json()
            msg = body.get("error", {}).get("message", "Unknown error")
        except Exception:
            msg = str(e)

        if code == 401:
            return "Error: Invalid Stripe API key. Check STRIPE_API_KEY environment variable."
        elif code == 403:
            return f"Error: Insufficient permissions. Your API key may need more access. ({msg})"
        elif code == 429:
            return "Error: Stripe rate limit hit. Wait a moment and try again."
        return f"Error: Stripe API returned {code} — {msg}"
    elif isinstance(e, httpx.TimeoutException):
        return "Error: Stripe request timed out. Try again."
    return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Input Models
# ---------------------------------------------------------------------------

class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class OverviewInput(BaseModel):
    """Input for business health overview."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'.",
    )


class FailedPaymentsInput(BaseModel):
    """Input for failed payments check."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    days_back: int = Field(
        default=7,
        description="How many days back to look for failed payments (1-90).",
        ge=1, le=90,
    )
    limit: int = Field(default=25, description="Max results to return.", ge=1, le=100)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class RevenueInput(BaseModel):
    """Input for revenue snapshot."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    period: str = Field(
        default="today",
        description="Time period: 'today', 'yesterday', 'week', 'month'.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("period")
    @classmethod
    def validate_period(cls, v: str) -> str:
        allowed = ("today", "yesterday", "week", "month")
        if v not in allowed:
            raise ValueError(f"period must be one of: {', '.join(allowed)}")
        return v


class SubscriptionChangesInput(BaseModel):
    """Input for subscription change tracking."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    days_back: int = Field(
        default=7,
        description="How many days back to check (1-90).",
        ge=1, le=90,
    )
    limit: int = Field(default=25, description="Max results.", ge=1, le=100)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class DailyDigestInput(BaseModel):
    """Input for complete daily business digest."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    include_failed: bool = Field(default=True, description="Include failed payments section.")
    include_revenue: bool = Field(default=True, description="Include revenue snapshot.")
    include_subscriptions: bool = Field(default=True, description="Include subscription changes.")
    include_overview: bool = Field(default=True, description="Include business health overview.")
    days_back: int = Field(default=1, description="Lookback period for changes (1-30).", ge=1, le=30)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

async def _fetch_active_subscriptions() -> Dict[str, Any]:
    """Fetch all active subscription counts and MRR."""
    subs = await _stripe_get("subscriptions", {
        "status": "active",
        "limit": 100,
    })
    return subs


async def _fetch_subscription_mrr(subscriptions: List[Dict]) -> Dict[str, float]:
    """Calculate MRR from subscription list, grouped by currency."""
    mrr: Dict[str, float] = {}
    for sub in subscriptions:
        currency = sub.get("currency", "eur")
        for item in sub.get("items", {}).get("data", []):
            price = item.get("price", {})
            amount = price.get("unit_amount", 0) * item.get("quantity", 1)
            interval = price.get("recurring", {}).get("interval", "month")
            interval_count = price.get("recurring", {}).get("interval_count", 1)

            # Normalize to monthly
            if interval == "year":
                amount = amount / (12 * interval_count)
            elif interval == "week":
                amount = amount * (52 / 12) / interval_count
            elif interval == "day":
                amount = amount * (365 / 12) / interval_count
            else:
                amount = amount / interval_count

            mrr[currency] = mrr.get(currency, 0) + amount

    return mrr


async def _fetch_failed_payments(since_ts: int, limit: int) -> List[Dict]:
    """Fetch failed and incomplete payment intents."""
    results = []

    for status in ("requires_payment_method", "requires_action"):
        data = await _stripe_get("payment_intents", {
            "created[gte]": since_ts,
            "limit": limit,
            "status": status,
        })
        results.extend(data.get("data", []))

    # Also check charges with failure
    charges = await _stripe_get("charges", {
        "created[gte]": since_ts,
        "limit": limit,
    })
    for charge in charges.get("data", []):
        if charge.get("status") == "failed":
            results.append({
                "id": charge["id"],
                "amount": charge.get("amount", 0),
                "currency": charge.get("currency", "eur"),
                "status": "failed",
                "created": charge.get("created", 0),
                "failure_message": charge.get("failure_message", "Unknown"),
                "customer": charge.get("customer"),
                "description": charge.get("description", ""),
            })

    return results


async def _fetch_charges_in_period(since_ts: int, until_ts: Optional[int] = None) -> List[Dict]:
    """Fetch successful charges in a time period."""
    params: Dict[str, Any] = {
        "created[gte]": since_ts,
        "limit": 100,
        "status": "succeeded",  # only for charges endpoint this doesn't exist, we filter below
    }
    if until_ts:
        params["created[lte]"] = until_ts

    # Remove status param, filter manually
    del params["status"]
    data = await _stripe_get("charges", params)
    return [c for c in data.get("data", []) if c.get("status") == "succeeded"]


async def _fetch_subscription_events(since_ts: int, limit: int) -> Dict[str, List]:
    """Fetch subscription-related events (created, canceled, updated)."""
    result: Dict[str, List] = {"created": [], "canceled": [], "updated": []}

    for event_type in (
        "customer.subscription.created",
        "customer.subscription.deleted",
        "customer.subscription.updated",
    ):
        data = await _stripe_get("events", {
            "type": event_type,
            "created[gte]": since_ts,
            "limit": limit,
        })
        events = data.get("data", [])
        if "created" in event_type:
            result["created"].extend(events)
        elif "deleted" in event_type:
            result["canceled"].extend(events)
        elif "updated" in event_type:
            result["updated"].extend(events)

    return result


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _format_overview_md(
    active_count: int,
    mrr: Dict[str, float],
    trialing_count: int,
    past_due_count: int,
) -> str:
    """Format business overview as Markdown."""
    lines = [
        "### 📊 Business Health Overview",
        "",
        f"🟢 **Active Subscriptions:** {active_count}",
    ]

    if mrr:
        mrr_parts = [_cents_to_amount(int(v), k) for k, v in mrr.items()]
        lines.append(f"💰 **Monthly Recurring Revenue (MRR):** {' + '.join(mrr_parts)}")
    else:
        lines.append("💰 **MRR:** No active subscriptions")

    if trialing_count:
        lines.append(f"🔵 **Trialing:** {trialing_count}")
    if past_due_count:
        lines.append(f"🔴 **Past Due:** {past_due_count} ⚠️ Attention needed!")

    return "\n".join(lines)


def _format_failed_md(payments: List[Dict]) -> str:
    """Format failed payments as Markdown."""
    if not payments:
        return "### ✅ Failed Payments\n\nNo failed payments found. All clear!"

    lines = [
        f"### ❌ Failed Payments ({len(payments)} found)",
        "",
    ]

    for p in payments[:20]:
        amount = _cents_to_amount(p.get("amount", 0), p.get("currency", "eur"))
        status = p.get("status", "unknown")
        created = _ts_to_date(p["created"]) if p.get("created") else "Unknown"
        failure = p.get("failure_message") or p.get("last_payment_error", {}).get("message", "")
        customer = p.get("customer") or "No customer"
        desc = p.get("description", "")

        line = f"- {_status_emoji(status)} **{amount}** — {status}"
        if failure:
            line += f" ({failure})"
        line += f"\n  Customer: `{customer}` | {created}"
        if desc:
            line += f" | {desc}"
        lines.append(line)

    return "\n".join(lines)


def _format_revenue_md(
    charges: List[Dict],
    period_label: str,
) -> str:
    """Format revenue snapshot as Markdown."""
    if not charges:
        return f"### 💰 Revenue — {period_label}\n\nNo successful charges in this period."

    # Group by currency
    totals: Dict[str, int] = {}
    for c in charges:
        cur = c.get("currency", "eur")
        totals[cur] = totals.get(cur, 0) + c.get("amount", 0)

    total_parts = [_cents_to_amount(v, k) for k, v in totals.items()]

    lines = [
        f"### 💰 Revenue — {period_label}",
        "",
        f"**Total:** {' + '.join(total_parts)}",
        f"**Transactions:** {len(charges)}",
        "",
    ]

    # Top 5 charges
    sorted_charges = sorted(charges, key=lambda x: x.get("amount", 0), reverse=True)
    if len(sorted_charges) > 1:
        lines.append("**Top transactions:**")
        for c in sorted_charges[:5]:
            amt = _cents_to_amount(c.get("amount", 0), c.get("currency", "eur"))
            desc = c.get("description") or c.get("statement_descriptor") or "No description"
            lines.append(f"- {amt} — {desc}")

    return "\n".join(lines)


def _format_sub_changes_md(events: Dict[str, List]) -> str:
    """Format subscription changes as Markdown."""
    created = events.get("created", [])
    canceled = events.get("canceled", [])
    updated = events.get("updated", [])

    total = len(created) + len(canceled) + len(updated)
    if total == 0:
        return "### 🔄 Subscription Changes\n\nNo subscription changes in this period."

    lines = [
        f"### 🔄 Subscription Changes ({total} events)",
        "",
    ]

    if created:
        lines.append(f"**🟢 New Subscriptions ({len(created)}):**")
        for e in created[:10]:
            sub = e.get("data", {}).get("object", {})
            customer = sub.get("customer", "Unknown")
            plan_items = sub.get("items", {}).get("data", [])
            amount_str = ""
            if plan_items:
                p = plan_items[0].get("price", {})
                amount_str = f" — {_cents_to_amount(p.get('unit_amount', 0), p.get('currency', 'eur'))}/mo"
            lines.append(f"  - Customer `{customer}`{amount_str}")
        lines.append("")

    if canceled:
        lines.append(f"**🚫 Cancellations ({len(canceled)}):**")
        for e in canceled[:10]:
            sub = e.get("data", {}).get("object", {})
            customer = sub.get("customer", "Unknown")
            reason = sub.get("cancellation_details", {}).get("reason", "not specified")
            lines.append(f"  - Customer `{customer}` — Reason: {reason}")
        lines.append("")

    if updated:
        lines.append(f"**🔄 Updates ({len(updated)}):**")
        lines.append(f"  {len(updated)} subscription(s) modified")

    # Net change
    net = len(created) - len(canceled)
    emoji = "📈" if net > 0 else "📉" if net < 0 else "➡️"
    lines.append(f"\n**Net Change:** {emoji} {'+' if net > 0 else ''}{net}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="stripe_alerts_overview",
    annotations={
        "title": "Business Health Overview",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def stripe_alerts_overview(params: OverviewInput) -> str:
    """Get a complete business health snapshot: active subscriptions, MRR, trialing and past-due counts.

    Provides an instant overview of your Stripe business metrics.

    Args:
        params (OverviewInput): Configuration including:
            - response_format (str): 'markdown' or 'json'

    Returns:
        str: Business health metrics in the requested format
    """
    try:
        active_data = await _stripe_get("subscriptions", {"status": "active", "limit": 100})
        trialing_data = await _stripe_get("subscriptions", {"status": "trialing", "limit": 100})
        past_due_data = await _stripe_get("subscriptions", {"status": "past_due", "limit": 100})
    except Exception as e:
        return _handle_stripe_error(e)

    active_subs = active_data.get("data", [])
    active_count = len(active_subs)
    trialing_count = len(trialing_data.get("data", []))
    past_due_count = len(past_due_data.get("data", []))
    mrr = await _fetch_subscription_mrr(active_subs)

    if params.response_format == ResponseFormat.JSON:
        return json.dumps({
            "active_subscriptions": active_count,
            "trialing": trialing_count,
            "past_due": past_due_count,
            "mrr": {k: round(v / 100, 2) for k, v in mrr.items()},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2)

    return _format_overview_md(active_count, mrr, trialing_count, past_due_count)


@mcp.tool(
    name="stripe_alerts_failed_payments",
    annotations={
        "title": "Check Failed Payments",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def stripe_alerts_failed_payments(params: FailedPaymentsInput) -> str:
    """Find failed and incomplete payments that need attention.

    Checks payment intents and charges for failures, showing amount, customer,
    failure reason, and timestamp. Essential for catching revenue leaks.

    Args:
        params (FailedPaymentsInput): Query parameters including:
            - days_back (int): Lookback period in days (1-90)
            - limit (int): Max results (1-100)
            - response_format (str): Output format

    Returns:
        str: Failed payments list in the requested format
    """
    since = _days_ago_ts(params.days_back)

    try:
        payments = await _fetch_failed_payments(since, params.limit)
    except Exception as e:
        return _handle_stripe_error(e)

    if params.response_format == ResponseFormat.JSON:
        return json.dumps({
            "failed_payments": payments,
            "count": len(payments),
            "period_days": params.days_back,
        }, indent=2, default=str)

    return _format_failed_md(payments)


@mcp.tool(
    name="stripe_alerts_revenue",
    annotations={
        "title": "Revenue Snapshot",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def stripe_alerts_revenue(params: RevenueInput) -> str:
    """Get a revenue snapshot for today, yesterday, this week, or this month.

    Shows total revenue, transaction count, and top transactions by amount.
    Supports multiple currencies.

    Args:
        params (RevenueInput): Revenue query parameters including:
            - period (str): 'today', 'yesterday', 'week', or 'month'
            - response_format (str): Output format

    Returns:
        str: Revenue data in the requested format
    """
    now = datetime.now(timezone.utc)
    until_ts: Optional[int] = None

    if params.period == "today":
        since = int(now.replace(hour=0, minute=0, second=0).timestamp())
        label = f"Today ({now.strftime('%d.%m.%Y')})"
    elif params.period == "yesterday":
        yesterday = now - timedelta(days=1)
        since = int(yesterday.replace(hour=0, minute=0, second=0).timestamp())
        until_ts = int(now.replace(hour=0, minute=0, second=0).timestamp())
        label = f"Yesterday ({yesterday.strftime('%d.%m.%Y')})"
    elif params.period == "week":
        since = _days_ago_ts(7)
        label = "Last 7 Days"
    else:  # month
        since = _days_ago_ts(30)
        label = "Last 30 Days"

    try:
        charges = await _fetch_charges_in_period(since, until_ts)
    except Exception as e:
        return _handle_stripe_error(e)

    if params.response_format == ResponseFormat.JSON:
        totals: Dict[str, int] = {}
        for c in charges:
            cur = c.get("currency", "eur")
            totals[cur] = totals.get(cur, 0) + c.get("amount", 0)
        return json.dumps({
            "period": params.period,
            "label": label,
            "totals": {k: round(v / 100, 2) for k, v in totals.items()},
            "transaction_count": len(charges),
            "charges": charges[:20],
        }, indent=2, default=str)

    return _format_revenue_md(charges, label)


@mcp.tool(
    name="stripe_alerts_subscriptions",
    annotations={
        "title": "Subscription Changes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def stripe_alerts_subscriptions(params: SubscriptionChangesInput) -> str:
    """Track subscription changes: new signups, cancellations, and plan updates.

    Shows net change and details for each event. Critical for understanding
    churn and growth trends.

    Args:
        params (SubscriptionChangesInput): Query parameters including:
            - days_back (int): Lookback period in days (1-90)
            - limit (int): Max results per category (1-100)
            - response_format (str): Output format

    Returns:
        str: Subscription changes in the requested format
    """
    since = _days_ago_ts(params.days_back)

    try:
        events = await _fetch_subscription_events(since, params.limit)
    except Exception as e:
        return _handle_stripe_error(e)

    if params.response_format == ResponseFormat.JSON:
        return json.dumps({
            "period_days": params.days_back,
            "new": len(events["created"]),
            "canceled": len(events["canceled"]),
            "updated": len(events["updated"]),
            "net_change": len(events["created"]) - len(events["canceled"]),
            "events": events,
        }, indent=2, default=str)

    return _format_sub_changes_md(events)


@mcp.tool(
    name="stripe_alerts_daily_digest",
    annotations={
        "title": "Daily Business Digest",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def stripe_alerts_daily_digest(params: DailyDigestInput) -> str:
    """Generate a complete daily business digest combining all alerts.

    The all-in-one tool: revenue snapshot, failed payments, subscription changes,
    and business health — in a single call. Perfect for morning briefings or
    automated daily reports.

    Args:
        params (DailyDigestInput): Digest configuration including:
            - include_failed (bool): Include failed payments section
            - include_revenue (bool): Include revenue snapshot
            - include_subscriptions (bool): Include subscription changes
            - include_overview (bool): Include business health overview
            - days_back (int): Lookback period (1-30)
            - response_format (str): Output format

    Returns:
        str: Complete business digest in the requested format
    """
    now = datetime.now(timezone.utc)
    since = _days_ago_ts(params.days_back)
    digest_data: Dict[str, Any] = {"generated_at": now.isoformat()}

    sections_md: List[str] = [
        "# 💼 Stripe Daily Digest",
        f"**{now.strftime('%A, %B %d, %Y')}** — Generated at {now.strftime('%H:%M UTC')}",
        "",
        "---",
    ]

    # Overview
    if params.include_overview:
        try:
            active_data = await _stripe_get("subscriptions", {"status": "active", "limit": 100})
            trialing_data = await _stripe_get("subscriptions", {"status": "trialing", "limit": 100})
            past_due_data = await _stripe_get("subscriptions", {"status": "past_due", "limit": 100})

            active_subs = active_data.get("data", [])
            mrr = await _fetch_subscription_mrr(active_subs)
            trialing_count = len(trialing_data.get("data", []))
            past_due_count = len(past_due_data.get("data", []))

            digest_data["overview"] = {
                "active": len(active_subs),
                "trialing": trialing_count,
                "past_due": past_due_count,
                "mrr": {k: round(v / 100, 2) for k, v in mrr.items()},
            }
            sections_md.append(_format_overview_md(len(active_subs), mrr, trialing_count, past_due_count))
            sections_md.append("")
        except Exception as e:
            sections_md.append(f"⚠️ Overview unavailable: {_handle_stripe_error(e)}")

    # Revenue
    if params.include_revenue:
        try:
            today_start = int(now.replace(hour=0, minute=0, second=0).timestamp())
            charges = await _fetch_charges_in_period(today_start)
            digest_data["revenue_today"] = {
                "count": len(charges),
                "charges": charges[:10],
            }
            sections_md.append(_format_revenue_md(charges, f"Today ({now.strftime('%d.%m.%Y')})"))
            sections_md.append("")
        except Exception as e:
            sections_md.append(f"⚠️ Revenue data unavailable: {_handle_stripe_error(e)}")

    # Failed payments
    if params.include_failed:
        try:
            failed = await _fetch_failed_payments(since, 25)
            digest_data["failed_payments"] = {"count": len(failed)}
            sections_md.append(_format_failed_md(failed))
            sections_md.append("")
        except Exception as e:
            sections_md.append(f"⚠️ Failed payments check unavailable: {_handle_stripe_error(e)}")

    # Subscription changes
    if params.include_subscriptions:
        try:
            sub_events = await _fetch_subscription_events(since, 25)
            digest_data["subscriptions"] = {
                "new": len(sub_events["created"]),
                "canceled": len(sub_events["canceled"]),
                "updated": len(sub_events["updated"]),
            }
            sections_md.append(_format_sub_changes_md(sub_events))
            sections_md.append("")
        except Exception as e:
            sections_md.append(f"⚠️ Subscription data unavailable: {_handle_stripe_error(e)}")

    # Footer
    sections_md.extend([
        "---",
        "*Powered by Stripe Business Alerts MCP — LIMITLESS Automation*",
    ])

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(digest_data, indent=2, default=str)

    return "\n".join(sections_md)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
