"""Schema and semantic guards. Invalid model IDs never enter the final output."""
import re
from .data import ACK, AREAS, CIRCLES, GOAL_TYPES, HORIZONS, LOOP_TYPES, ORG_ROLES, ORG_TYPES, tokens
from .policy import normalize_help, parse_due, valid_date


def member(value, choices):
    return isinstance(value, str) and value in choices


def array(value):
    return value if isinstance(value, list) else []


def normalize_graph(raw, fallback, corpus):
    raw = raw if isinstance(raw, dict) else {}
    orgs = []
    seen = set()
    for o in array(raw.get("organisations")):
        if not isinstance(o, dict) or not isinstance(o.get("id"), str) or not o["id"] or o["id"] in seen:
            continue
        if not isinstance(o.get("name"), str) or not o["name"].strip():
            continue
        if not member(o.get("type"), ORG_TYPES) or not member(o.get("side"), {"home", "work"}) or not member(o.get("role"), ORG_ROLES):
            continue
        orgs.append({k: o[k] for k in ("id", "name", "type", "side", "role")})
        seen.add(o["id"])
    if not orgs:
        orgs = fallback["organisations"]
        seen = {o["id"] for o in orgs}
    proposed = {}
    for tie in array(raw.get("chats")):
        if not isinstance(tie, dict) or not member(tie.get("chat_id"), corpus.chat):
            continue
        if member(tie.get("organisation"), seen) and "person" not in tie:
            proposed[tie["chat_id"]] = {"chat_id": tie["chat_id"], "organisation": tie["organisation"]}
        elif member(tie.get("person"), corpus.ids) and "organisation" not in tie:
            proposed[tie["chat_id"]] = {"chat_id": tie["chat_id"], "person": tie["person"]}
    ties = []
    for previous in fallback["chats"]:
        cid = previous["chat_id"]
        c = corpus.chat[cid]
        if cid in proposed:
            ties.append(proposed[cid])
        elif previous.get("organisation") in seen or "person" in previous:
            ties.append(previous)
        else:
            others = [p for p in c["participants"] if p != "ME"]
            if others:
                ties.append({"chat_id": cid, "person": others[0]})
            else:
                # A self-only notes chat still needs one valid assignment.
                note = next((o for o in fallback["organisations"] if o["id"] == previous.get("organisation")), None)
                if note and note["id"] not in seen:
                    orgs.append(note)
                    seen.add(note["id"])
                ties.append(previous)
    return {"organisations": orgs, "chats": ties}


def normalize_people(raw, fallback, corpus, graph, corrections):
    org_ids = {o["id"] for o in graph["organisations"]}
    people = {p["id"]: dict(p) for p in fallback}
    for p in array(raw):
        if not isinstance(p, dict) or not member(p.get("id"), corpus.ids) or not member(p.get("circle"), CIRCLES):
            continue
        person = {"id": p["id"], "circle": p["circle"]}
        links = []
        for link in array(p.get("links")):
            if isinstance(link, dict) and member(link.get("organisation"), org_ids) and member(link.get("link"), {"runs", "supports"}):
                item = {"organisation": link["organisation"], "link": link["link"]}
                if item not in links:
                    links.append(item)
        if links:
            person["links"] = links
        after = [v for v in array(p.get("looks_after")) if member(v, corpus.ids) and v != p["id"]]
        if after:
            person["looks_after"] = sorted(set(after))
        people[p["id"]] = person
    for pid, circle in corpus.seed.get("circles", {}).items():
        if pid in people and circle in CIRCLES:
            people[pid]["circle"] = circle
    for pid, correction in corrections.get("people", {}).items():
        people[pid]["circle"] = correction["circle"]
        # A correction away from staff/colleague must not retain inferred employment links.
        if correction["circle"] not in {"staff", "colleague", "partner"}:
            people[pid].pop("links", None)
            people[pid].pop("looks_after", None)
    return [people[pid] for pid in sorted(people)]


def normalize_loop(value, corpus, people, allowed_sources=None):
    if not isinstance(value, dict):
        return None
    source = value.get("source_msg")
    if not isinstance(source, str) or source not in corpus.message or (allowed_sources is not None and source not in allowed_sources):
        return None
    m = corpus.message[source]
    if value.get("chat_id") != m["chat_id"] or not member(value.get("owner"), corpus.ids | {"ME"}) or not member(value.get("type"), LOOP_TYPES):
        return None
    if not isinstance(value.get("title"), str) or not value["title"].strip():
        return None
    loop = {"title": value["title"].strip()[:350], "type": value["type"], "owner": value["owner"],
            "chat_id": m["chat_id"], "source_msg": source, "due": valid_date(value.get("due")),
            "status": "open", "closed_by": None}
    if loop["due"] is None:
        loop["due"] = parse_due(m.get("body", ""), m["ts"])
    close = corpus.message.get(value.get("closed_by")) if isinstance(value.get("closed_by"), str) else None
    if member(value.get("status"), {"done", "dropped"}) and close and close["chat_id"] == m["chat_id"] and close["ts"] > m["ts"]:
        body = close.get("body", "").strip()
        acknowledgement = bool(ACK.fullmatch(body) or re.fullmatch(r"(?:done|sent|paid|will do|on it|working on it)[.!\s]*", body, re.I))
        decision_answer = (loop["type"] == "question" and close["sender_id"] == loop["owner"]
                           and re.search(r"\b(?:should (?:we|i)|shall we|can we|do you want|are you (?:coming|going))\b", m.get("body", ""), re.I)
                           and re.fullmatch(r"(?:yes|no|yes please|no thanks)[.!\s]*", body, re.I))
        future_or_negated = bool(re.search(r"\b(?:not|haven't|hasn't|didn't|isn't|wasn't|will|would|shall|going to)\b[^.!?\n]{0,45}\b(?:send|sent|pay|paid|deliver|delivered|complete|completed|done|order|ordered|book|booked|cancel|cancelled)\b", body, re.I))
        if (not acknowledgement or decision_answer) and not future_or_negated:
            loop["status"] = value["status"]
            loop["closed_by"] = close["id"]
    loop["help"] = normalize_help(value.get("help"), loop, corpus, people)
    return loop


def dedup_loops(loops, corpus):
    result = []
    for loop in sorted(loops, key=lambda v: (corpus.message[v["source_msg"]]["ts"], v["source_msg"], v["title"])):
        words = tokens(loop["title"])
        duplicate = None
        for old in reversed(result[-80:]):
            if old["chat_id"] != loop["chat_id"] or old["owner"] != loop["owner"]:
                continue
            similarity = len(words & tokens(old["title"])) / max(1, len(words | tokens(old["title"])))
            same_source = old["source_msg"] == loop["source_msg"]
            delta = corpus.message[loop["source_msg"]]["ts"] - corpus.message[old["source_msg"]]["ts"]
            if similarity >= (.65 if same_source else .88) and (same_source or (delta < 2 * 86400 and old["due"] == loop["due"] and old["status"] == "open")):
                duplicate = old
                break
        if duplicate:
            if loop["status"] != "open" and duplicate["status"] == "open":
                duplicate.update(status=loop["status"], closed_by=loop["closed_by"], help=None)
            continue
        result.append(loop)
    return result


def normalize_goals(raw, corpus, limit=10):
    result = []
    for g in array(raw):
        if not isinstance(g, dict) or not isinstance(g.get("title"), str) or not g["title"].strip():
            continue
        if not member(g.get("area"), AREAS) or not member(g.get("type"), GOAL_TYPES) or not member(g.get("horizon"), HORIZONS):
            continue
        evidence = [i for i in array(g.get("evidence")) if member(i, corpus.message)]
        if not evidence or not any(corpus.message[i]["sender_id"] == "ME" for i in evidence):
            continue
        goal = {"title": g["title"].strip()[:300], "area": g["area"], "type": g["type"], "horizon": g["horizon"], "evidence": sorted(set(evidence))}
        duplicate = next((old for old in result if goal["area"] == old["area"]
                          and len(tokens(goal["title"]) & tokens(old["title"])) / max(1, len(tokens(goal["title"]) | tokens(old["title"]))) > .65), None)
        if duplicate:
            duplicate["evidence"] = sorted(set(duplicate["evidence"]) | set(goal["evidence"]))
        else:
            result.append(goal)
    return result[:limit]
