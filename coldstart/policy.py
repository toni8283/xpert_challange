"""Deterministic date handling and intervention boundaries shared by both modes."""
import re
from datetime import datetime, timedelta
from .data import IST

WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "wednesday": 2, "wed": 2,
            "thursday": 3, "thu": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}


def parse_due(body, ts):
    local = datetime.fromtimestamp(float(ts), IST)
    text = body.lower()
    explicit = re.search(r"\b(20\d\d-\d\d-\d\d)\b", text)
    if explicit:
        try:
            return datetime.strptime(explicit[1], "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    if re.search(r"\b(day after tomorrow|parso)\b", text):
        return (local.date() + timedelta(days=2)).isoformat()
    if re.search(r"\b(tomorrow|tmrw|tmr|kal)\b", text):
        # 'kal' alone can mean yesterday; only use it in an actionable future sentence.
        if "kal" not in text or not re.search(r"\b(tha|thi|kiya|gaya|yesterday)\b", text):
            return (local.date() + timedelta(days=1)).isoformat()
    if re.search(r"\b(today|tonight|aaj)\b", text):
        return local.date().isoformat()
    weekday = re.search(r"\b(" + "|".join(WEEKDAYS) + r")\b", text)
    if weekday:
        delta = (WEEKDAYS[weekday[1]] - local.weekday()) % 7
        if "next " + weekday[1] in text:
            delta = delta or 7
        return (local.date() + timedelta(days=delta)).isoformat()
    if re.search(r"\bthis week\b", text):
        return (local.date() + timedelta(days=6 - local.weekday())).isoformat()
    return None


def valid_date(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def reminder_time(due, corpus):
    now = corpus.local_time()
    day = datetime.strptime(due, "%Y-%m-%d").date() if valid_date(due) else now.date()
    result = datetime.combine(day, datetime.min.time(), IST).replace(hour=9)
    if result <= now:
        result = now + timedelta(hours=1)
    return result.isoformat(timespec="seconds")


def default_help(loop, corpus, people):
    if loop["status"] != "open":
        return None
    owner = loop["owner"]
    if owner != "ME":
        if people.get(owner, {}).get("circle") == "spouse":
            return {"action": "leave", "reason": "The spouse owns this independent plan or action."}
        due = valid_date(loop.get("due"))
        if due and due < corpus.local_time().date().isoformat() and loop["type"] == "followup":
            return {"action": "remind", "remind_at": reminder_time(due, corpus)}
        return {"action": "leave", "reason": "Someone else owns the next move; let them handle it."}
    text = loop["title"].lower()
    if re.search(r"\b(call|attend|meet|discuss|visit|decide|choose|approve|listen|pay|transfer|buy shares)\b", text):
        return {"action": "remind", "remind_at": reminder_time(loop.get("due"), corpus)}
    if re.search(r"\b(book|order|find|research|compare|send|share|write|draft|prepare|report|invite)\b", text):
        return {"action": "assist", "next_step": "Prepare a private draft or options for: " + loop["title"], "needs_yes": False}
    return {"action": "remind", "remind_at": reminder_time(loop.get("due"), corpus)}


def normalize_help(value, loop, corpus, people):
    fallback = default_help(loop, corpus, people)
    if loop["status"] != "open":
        return None
    if not isinstance(value, dict):
        return fallback
    action = value.get("action")
    if loop["owner"] != "ME" and people.get(loop["owner"], {}).get("circle") == "spouse":
        return fallback
    # Strong owner boundary; a spouse's personal plans and already-delegated work stay quiet.
    if loop["owner"] != "ME" and not (loop["type"] == "followup" and valid_date(loop.get("due")) and loop["due"] < corpus.local_time().date().isoformat()):
        return fallback
    if action == "leave":
        return {"action": action, "reason": str(value.get("reason") or "No useful intervention is needed.")[:300]}
    if action == "remind":
        proposed = value.get("remind_at")
        if isinstance(proposed, str):
            try:
                when = datetime.fromisoformat(proposed.replace("Z", "+00:00"))
                now = corpus.local_time()
                if when.tzinfo is not None and now < when <= now + timedelta(days=14):
                    due = valid_date(loop.get("due"))
                    if not due or when.astimezone(IST).date().isoformat() <= max(due, now.date().isoformat()):
                        return {"action": action, "remind_at": when.astimezone(IST).isoformat(timespec="seconds")}
            except ValueError:
                pass
        return {"action": action, "remind_at": reminder_time(loop.get("due"), corpus)}
    if action == "assist" and isinstance(value.get("next_step"), str) and value["next_step"].strip():
        step = value["next_step"].strip()[:400]
        private = bool(re.search(r"\b(draft|prepare|research|compare|find|list|summari[sz]e|calculate)\b", step, re.I))
        external = bool(re.search(r"\b(send|submit|book|purchase|pay|transfer|cancel|publish|delete|message|call)\b", step, re.I))
        # Mixed steps must split at the approval boundary. This program never executes them.
        if private and external:
            return {"action": action, "next_step": "Prepare privately for review: " + loop["title"], "needs_yes": False}
        needs_yes = bool(value.get("needs_yes")) or external
        return {"action": action, "next_step": step, "needs_yes": needs_yes}
    return fallback
