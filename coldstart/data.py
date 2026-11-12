"""Input access is deliberately restricted to the three challenge input files."""
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
CIRCLES = set("spouse child parent in-law sibling relative friend colleague client vendor partner staff".split())
ORG_TYPES = {"company", "residence", "vacation home", "workspace", "society", "school", "other"}
ORG_ROLES = {"owner", "partner", "helper", "resident", "parent", "member", "other"}
AREAS = set("self spouse kids parents work friends experiences finances health home".split())
GOAL_TYPES = {"habit", "milestone", "experience"}
HORIZONS = {"3mo", "1yr", "3yr", "5yr"}
LOOP_TYPES = {"commitment", "followup", "deadline", "question"}
PLACEHOLDER = re.compile(r"^\s*(?:\[(?:photo|video|image|document|sticker|audio|gif)\]|image|<media omitted>)\s*$", re.I)
ACK = re.compile(r"^[\s.!,:;🙏👍❤️♥️😊✅👌]*((ok+a*y*|kk|yes|yep|sure|thanks?|thank you|noted|cool|haan|ha|ji|theek hai|accha|alright)[\s.!🙏👍❤️]*)?$", re.I)
ACTION = re.compile(
    r"\b(please|pls|plz|pl |can (?:you|u|we)|could (?:you|u)|will (?:you|u)|shall we|should (?:i|we)|"
    r"i['’]?ll|we['’]?ll|i will|we will|will (?:send|do|pay|book|call|check|complete|share|revert|connect|reply)|"
    r"need(?:s)?|send|share|pay|book|order|arrange|confirm|remind|follow.?up|revert|"
    r"waiting|pending|overdue|reverting|by tomorrow|due |deadline|let.?s|let me know|lmk|"
    r"bhej|bhejna|karo|karna|kar do|kar dena|karunga|kar dunga|de do|kab tak|baki|dunga)\b", re.I)


def compact(text, limit=700):
    text = re.sub(r"[ \t]+", " ", str(text)).strip()
    if len(text) <= limit:
        return text
    return text[:limit * 3 // 4] + " …[truncated]… " + text[-limit // 4:]


def tokens(text):
    return set(re.findall(r"[a-z\u0900-\u097f\u0980-\u09ff]{3,}|\b\d[\d,.]*\b", str(text).lower())) - {
        "the", "and", "for", "you", "your", "please", "pls", "will", "can", "that", "this", "with",
        "have", "send", "from", "today", "tomorrow", "sir", "are", "was", "let", "need", "hello",
        "thanks", "thank", "not", "but", "get", "just", "when", "what", "would", "could", "should",
    }


def is_broadcast(body, sender):
    if sender == "ME":
        return False
    article = len(body) > 350 and "http" in body and re.search(r"\bread (?:more|the (?:full )?(?:story|article)|full (?:story|article))\b", body, re.I)
    bulk = len(body) > 1800 and not re.search(r"\b(?:can you|can u|pls|please|i['’]ll|i will)\b", body[:500], re.I)
    return bool(article or bulk)


def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError("Invalid JSON in %s at line %d" % (path.name, n)) from exc
    return rows


class Corpus:
    def __init__(self, folder):
        folder = Path(folder)
        self.chats = read_jsonl(folder / "chats.jsonl")
        self.messages = read_jsonl(folder / "messages.jsonl")
        self.seed = json.loads((folder / "seed.json").read_text(encoding="utf-8-sig")) if (folder / "seed.json").is_file() else {}
        self.chats.sort(key=lambda c: c["chat_id"])
        self.messages.sort(key=lambda m: (float(m["ts"]), m["id"]))
        self.chat = {c["chat_id"]: c for c in self.chats}
        self.message = {m["id"]: m for m in self.messages}
        if len(self.chat) != len(self.chats) or len(self.message) != len(self.messages):
            raise ValueError("Duplicate chat or message IDs in input")
        self.ids = set(p for c in self.chats for p in c.get("participants", []) if p != "ME")
        self.by_chat = defaultdict(list)
        self.by_person = defaultdict(list)
        self.memberships = defaultdict(list)
        self.names = defaultdict(list)
        for c in self.chats:
            for pid in c.get("participants", []):
                if pid != "ME":
                    self.memberships[pid].append(c["chat_id"])
                    if not c.get("is_group") and c.get("name"):
                        self.names[pid].append(c["name"])
        for m in self.messages:
            if m["chat_id"] not in self.chat:
                raise ValueError("Message references an unknown chat")
            self.by_chat[m["chat_id"]].append(m)
            self.by_person[m["sender_id"]].append(m)
            name = m.get("sender_name", "").strip()
            if name and name not in self.names[m["sender_id"]]:
                self.names[m["sender_id"]].append(name)
        self.now = max((float(m["ts"]) for m in self.messages), default=0)

    def local_time(self, ts=None):
        return datetime.fromtimestamp(self.now if ts is None else float(ts), IST)

    def record(self, m, limit=700):
        return [m["id"], self.local_time(m["ts"]).strftime("%Y-%m-%d %H:%M"),
                m["sender_id"], m.get("kind", "text"), compact(m.get("body", ""), limit)]

    def direct(self, pid):
        return [m for cid in self.memberships[pid] if not self.chat[cid].get("is_group") for m in self.by_chat[cid]]

    def sample(self, messages, count=6, limit=240):
        if len(messages) <= count:
            return [self.record(m, limit) for m in messages]
        # Evidence from the beginning, end, both speakers, and action-bearing turns.
        indices = {0, len(messages) - 1}
        ranked = sorted(range(len(messages)), key=lambda i: (
            bool(ACTION.search(messages[i].get("body", ""))) * 4
            + (messages[i]["sender_id"] == "ME") * 2
            - bool(PLACEHOLDER.match(messages[i].get("body", ""))) * 8,
            -i), reverse=True)
        for i in ranked:
            if len(indices) >= count:
                break
            indices.add(i)
        return [self.record(messages[i], limit) for i in sorted(indices)]

    def dossier(self, pid, ties=None):
        groups = [{"id": cid, "name": compact(self.chat[cid].get("name", ""), 100),
                   "organisation": (ties or {}).get(cid)}
                  for cid in self.memberships[pid] if self.chat[cid].get("is_group")]
        return {"id": pid, "names": self.names[pid][:4], "seed_circle": self.seed.get("circles", {}).get(pid),
                "groups": groups[:22], "direct": self.sample(self.direct(pid), 9, 320),
                "authored_in_groups": self.sample([m for m in self.by_person[pid] if self.chat[m["chat_id"]].get("is_group")], 4, 230)}

    def active_messages(self, chat_id):
        """Keep conversational turns, trim bulk forwards, retain nearby media context."""
        rows = self.by_chat[chat_id]
        if not rows:
            return []
        has_me = any(m["sender_id"] == "ME" for m in rows)
        keep = set()
        for i, m in enumerate(rows):
            body = str(m.get("body", ""))
            if PLACEHOLDER.match(body) or not body.strip():
                continue
            # One-way newsletters and long forwarded articles are context, not promises.
            if is_broadcast(body, m["sender_id"]):
                continue
            if has_me or ACTION.search(body) or "?" in body:
                keep.add(i)
                keep.update(j for j in range(max(0, i - 2), min(len(rows), i + 3)))
        return [m for i, m in enumerate(rows) if i in keep]

    def future_evidence(self, loop, limit=18):
        """Closure retrieval: local continuation, lexical matches, then end-of-history."""
        source = self.message[loop["source_msg"]]
        future = [m for m in self.by_chat[source["chat_id"]] if m["ts"] > source["ts"]]
        query = tokens(loop["title"] + " " + source.get("body", ""))
        selected = {m["id"] for m in future[:6] + future[-3:]}
        ranked = sorted(future, key=lambda m: (len(query & tokens(m.get("body", ""))), -float(m["ts"])), reverse=True)
        for m in ranked:
            if len(selected) >= limit:
                break
            if query & tokens(m.get("body", "")):
                selected.add(m["id"])
                idx = future.index(m)
                if idx + 1 < len(future) and len(selected) < limit:
                    selected.add(future[idx + 1]["id"])
        return [self.record(m, 480) for m in future if m["id"] in selected][:limit]


def load_corrections(path, corpus):
    if not path:
        return {}
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) - {"people", "chats"}:
        raise ValueError("Corrections must be an object with people/chats maps")
    for pid, correction in value.get("people", {}).items():
        if pid not in corpus.ids or not isinstance(correction, dict):
            raise ValueError("Invalid person in corrections: " + pid)
        if correction.get("circle") not in CIRCLES:
            raise ValueError("A person correction needs a valid circle")
    for cid, tie in value.get("chats", {}).items():
        if cid not in corpus.chat or not isinstance(tie, dict) or set(tie) not in ({"person"}, {"organisation"}):
            raise ValueError("Invalid chat correction: " + cid)
        if "person" in tie and tie["person"] not in corpus.ids:
            raise ValueError("Chat correction names an unknown person")
    return value
