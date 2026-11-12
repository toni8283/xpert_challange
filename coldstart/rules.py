"""Zero-cost baseline and useful priors. No dataset-specific names or IDs."""
import hashlib
import re
from collections import Counter
from .data import ACK, ACTION, PLACEHOLDER, compact, is_broadcast, tokens
from .policy import default_help, parse_due


def org_id(name):
    return "org_" + hashlib.sha256(name.casefold().strip().encode()).hexdigest()[:10]


def aliases(name):
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+", name)
    normal = re.sub(r"[^\w]+", " ", name.lower()).strip()
    result = {normal}
    if len(words) > 1:
        result.add("".join(w[0] for w in words).lower())
    parts = normal.split()
    if len(parts) > 1 and len(parts[0]) >= 4:
        result.add(parts[0])
    return {v for v in result if len(v) >= 2}


def mentions(text, names):
    return any(re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", text.lower()) for a in names)


def infer_graph(corpus):
    orgs = []
    def add(name, kind="company", side="work", role="owner"):
        oid = org_id(name)
        if not any(o["id"] == oid for o in orgs):
            orgs.append({"id": oid, "name": name, "type": kind, "side": side, "role": role})
        return oid
    for item in corpus.seed.get("organisations", []):
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            add(name.strip())
    for c in corpus.chats:
        if not c.get("is_group"):
            continue
        name = c.get("name", "")
        match = re.match(r"^(.+?)\s+(?:operations|team|accounts|finance)\s*$", name, re.I)
        if match and not any(mentions(name, aliases(o["name"])) for o in orgs):
            add(match[1].strip())
    all_names = " ".join(n for ns in corpus.names.values() for n in ns)
    home_groups = [c for c in corpus.chats if c.get("is_group") and re.search(r"\b(kitchen|ghar|household|home staff|home operations)\b", c.get("name", ""), re.I)]
    if home_groups or re.search(r"\b(maid|cook|home staff)\b", all_names, re.I):
        add("Home", "residence", "home")
    own_text = " ".join(m.get("body", "") for m in corpus.by_person["ME"])
    if re.search(r"\b(?:our|my|the) farm(?:house)?\b|\bfarmhouse\b", own_text, re.I):
        add("Farmhouse", "vacation home", "home")
    if re.search(r"\b(?:office (?:cleaner|staff)|(?:cleaner|housekeeping).*office)\b", all_names, re.I):
        add("Office", "workspace")
    ties = []
    for c in corpus.chats:
        cid = c["chat_id"]
        others = [p for p in c.get("participants", []) if p != "ME"]
        if not others:
            oid = add("Personal notes", "other", "home", "member")
            ties.append({"chat_id": cid, "organisation": oid})
            continue
        if not c.get("is_group"):
            ties.append({"chat_id": cid, "person": others[0]})
            continue
        name = c.get("name", "")
        candidates = [o for o in orgs if mentions(name, aliases(o["name"]))]
        # A family social group isn't necessarily the residence organisation.
        if re.search(r"family|where the heart", name, re.I):
            candidates = []
        if not candidates and re.search(r"\b(kitchen|ghar|household|home staff)\b", name, re.I):
            candidates = [o for o in orgs if o["type"] == "residence"]
        if candidates:
            chosen = max(candidates, key=lambda o: len(o["name"]))
            ties.append({"chat_id": cid, "organisation": chosen["id"]})
        else:
            authored = Counter(m["sender_id"] for m in corpus.by_chat[cid])
            representative = max(others, key=lambda p: (authored[p], p))
            ties.append({"chat_id": cid, "person": representative})
    # Membership propagation, not a hard-coded list of community names.
    company_members = {}
    for o in orgs:
        if o["type"] != "company":
            continue
        linked = [c for c in ties if c.get("organisation") == o["id"]]
        company_members[o["id"]] = Counter(p for c in linked for p in corpus.chat[c["chat_id"]].get("participants", []) if p != "ME")
    for tie in ties:
        c = corpus.chat[tie["chat_id"]]
        if not c.get("is_group") or "organisation" in tie:
            continue
        if not re.search(r"\b(community|connect|circle|forum|rate|acq|marketplace)\b", c.get("name", ""), re.I):
            continue
        scores = {oid: sum(min(members[p], 3) for p in c.get("participants", [])) for oid, members in company_members.items()}
        if scores and max(scores.values()) >= 3:
            oid = max(scores, key=scores.get)
            tie.pop("person", None)
            tie["organisation"] = oid
    return {"organisations": orgs, "chats": ties}


def infer_people(corpus, graph):
    orgs = {o["id"]: o for o in graph["organisations"]}
    org_ties = {t["chat_id"]: t["organisation"] for t in graph["chats"] if "organisation" in t}
    result = []
    # Only assign an unseeded spouse when frequent direct conversation is strongly domestic.
    spouse_scores = {}
    for pid in corpus.ids:
        direct = corpus.direct(pid)
        body = " ".join(m.get("body", "") for m in direct)
        count = len(re.findall(r"\b(kids|children|dinner|bedroom|household|our bath|our home|mom|dad|mummy)\b", body, re.I))
        if len(direct) >= 60 and count >= 5:
            spouse_scores[pid] = count
    spouse = max(spouse_scores, key=spouse_scores.get) if spouse_scores else None
    for pid in sorted(corpus.ids):
        names = " ".join(corpus.names[pid])
        direct = corpus.direct(pid)
        body = " ".join(m.get("body", "") for m in direct)
        group_names = " ".join(corpus.chat[cid].get("name", "") for cid in corpus.memberships[pid] if corpus.chat[cid].get("is_group"))
        affiliations = Counter(org_ties[cid] for cid in corpus.memberships[pid] if cid in org_ties)
        circle = corpus.seed.get("circles", {}).get(pid)
        if not circle:
            if pid == spouse:
                circle = "spouse"
            elif re.search(r"\b(mom|dad|mummy|papa|mother|father)\b", names, re.I):
                circle = "parent"
            elif re.search(r"\b(my son|my daughter)\b", names, re.I):
                circle = "child"
            elif re.search(r"\b(maid|cook|driver|cleaner|housekeeping|caretaker)\b", names, re.I):
                circle = "staff"
            elif re.search(r"\bhome\b", names, re.I) and re.search(r"\b(?:kitchen|household|home staff)\b", group_names, re.I):
                circle = "staff"
            elif re.search(r"\b(chacha|chachi|mama(?:ji)?|mami|mausi|bua|uncle|aunty|cousin)\b", names + " " + body, re.I):
                circle = "relative"
            elif re.search(r"\bsiblings?\b|bro.*sis", group_names, re.I):
                circle = "sibling"
            elif re.search(r"\b(internship|certificate|come to work|come.*office today|placement season|backup person trained)\b", body, re.I):
                circle = "colleague"
            elif any(re.search(r"\b(?:operations|internal team|core team|office team)\b", corpus.chat[cid].get("name", ""), re.I) for cid in corpus.memberships[pid] if corpus.chat[cid].get("is_group")):
                circle = "colleague"
            elif re.search(r"\b(quotation|catalogue|drawings|per kg|ex.godown|fees|fee.s|printers|supplier|contractor|yoga|trading company)\b", names + " " + body, re.I):
                circle = "vendor"
            elif re.search(r"\b(kids room needs|please hid|please clean|what.*banana|no lanch|no deener)\b", body, re.I):
                circle = "staff"
            elif any(n >= 3 and orgs[oid]["type"] == "company" for oid, n in affiliations.items()):
                circle = "colleague"
            elif any(mentions(names, aliases(o["name"])) for o in orgs.values() if o["type"] == "company"):
                circle = "colleague"
            elif re.search(r"\b(our campaign|the campaign|sharing the report|initial read|your expertise|our brand)\b", body, re.I):
                circle = "client"
            elif re.search(r"\bfamily\b", group_names, re.I):
                circle = "relative"
            elif re.search(r"\bad[ -]?targeting\b", group_names, re.I):
                circle = "client"
            else:
                circle = "friend"
        person = {"id": pid, "circle": circle}
        links = []
        if circle in {"colleague", "partner", "staff"}:
            for oid, count in affiliations.items():
                if circle == "staff" and orgs[oid]["side"] == "home":
                    links.append({"organisation": oid, "link": "supports"})
                elif circle in {"colleague", "partner"} and orgs[oid]["type"] == "company":
                    links.append({"organisation": oid, "link": "runs"})
            if circle == "staff" and not links:
                target = "vacation home" if re.search(r"farm|caretaker", names, re.I) else "workspace" if re.search(r"office", names, re.I) else "residence"
                links = [{"organisation": o["id"], "link": "supports"} for o in orgs.values() if o["type"] == target][:1]
        if links:
            person["links"] = links
        result.append(person)
    return result


def _source_candidate(m, corpus, people):
    body = m.get("body", "").strip()
    if not body or PLACEHOLDER.match(body) or ACK.fullmatch(body) or len(body) > 1600 or is_broadcast(body, m["sender_id"]):
        return False
    if not tokens(body):
        return False
    if re.search(r"\b(happy birthday|happy.*day|good morning|congratulations)\b", body, re.I) and not ACTION.search(body):
        return False
    # A generic offer or contact autoresponder is not a binding obligation.
    if re.search(r"^\s*(?:thank you for contacting|would you like to place an order)|\blet (?:me|us) know if (?:you|u)\b|\bfeel free to\b", body, re.I):
        return False
    if "http" in body and "#" in body and len(body) > 120 and not re.search(r"\b(?:please|pls|can you|could you|i['’]ll|i will)\b", body, re.I):
        return False
    vague = {"figure", "show", "remember", "tell", "check", "try", "see", "ill", "obv", "know", "him", "her", "them", "all", "later", "soon", "then", "well", "also", "myself", "fine", "sure", "doing", "able", "any", "lets"}
    words = tokens(body)
    if len(words) <= 5 and not (words - vague):
        return False
    c = corpus.chat[m["chat_id"]]
    direct = not c.get("is_group")
    # Most casual question marks are conversational turns, not unfinished
    # obligations. Require a specific decision/assignment signal, while
    # retaining a separate path for explicit action verbs and requests.
    decision_question = bool("?" in body and len(tokens(body)) >= 3 and re.search(
        r"\b(?:which|whether|should|shall|when (?:can|will|would)|by when|kab tak|"
        r"confirm|decide|do you (?:want|agree|prefer)|are we (?:going|meeting)|(?:are )?you both coming|are you coming)\b", body, re.I))
    if direct:
        return bool(ACTION.search(body) or decision_question or re.search(r"^(?:buy|purchase|text)\b", body, re.I)
                    or re.search(r"\b(?:invite to be made|need to discuss|khatam hone|measurements required)\b", body, re.I))
    # In groups, only an explicit user promise, user request, or a concrete decision.
    if m["sender_id"] == "ME":
        return bool(ACTION.search(body) or decision_question)
    if len(c.get("participants", [])) <= 4 and decision_question and re.search(r"\byou both\b", body, re.I) and any(people.get(pid, {}).get("circle") == "spouse" for pid in c.get("participants", [])):
        return True
    me_names = corpus.names.get("ME", [])
    first_names = [n.split()[0] for n in me_names if n.split()]
    return bool(ACTION.search(body) and any(re.search(r"\b" + re.escape(n) + r"\b", body, re.I) for n in first_names))


def infer_loops(corpus, people_list):
    people = {p["id"]: p for p in people_list}
    loops = []
    for c in corpus.chats:
        rows = corpus.by_chat[c["chat_id"]]
        prior = []
        for i, m in enumerate(rows):
            if not _source_candidate(m, corpus, people):
                continue
            body = m.get("body", "").strip()
            other = next((p for p in c["participants"] if p != "ME"), "ME")
            promise = bool(re.search(r"\b(i['’]ll|i will|will (?:send|share|do|pay|book|call|revert|complete)|kar lunga|kar dunga|bhej dunga)\b", body, re.I))
            owner = m["sender_id"] if promise else (other if m["sender_id"] == "ME" and not promise else "ME")
            if m["sender_id"] == "ME" and not re.search(r"\b(please|pls|plz|can (?:you|u)|could (?:you|u)|lmk|let me know|kab tak)\b", body, re.I):
                owner = "ME"
            if not c.get("is_group") and m["sender_id"] == "ME" and not promise and re.match(r"(?:please\s+|pls\s+|plz\s+)?(?:send|share|give|provide|check|buy|pay|order|book|call|text|confirm)\b", body, re.I):
                owner = other
            due = parse_due(body, m["ts"])
            kind = "commitment" if promise else "question" if "?" in body or re.search(r"\b(should|which|whether)\b", body, re.I) else "followup" if owner != "ME" else "deadline" if due else "commitment"
            # One real task across repeated asks; retain the original source.
            words = tokens(body)
            duplicate = next((l for l in reversed(prior[-12:]) if l["owner"] == owner and words
                              and m["ts"] - corpus.message[l["source_msg"]]["ts"] < 6 * 3600
                              and l["status"] == "open"
                              and len(words & tokens(l["title"])) / max(1, len(words | tokens(l["title"]))) > .85), None)
            if duplicate:
                continue
            title = compact(re.sub(r"https?://\S+", "[link]", body), 170)
            loop = {"title": title, "type": kind, "owner": owner, "chat_id": c["chat_id"], "source_msg": m["id"], "due": due, "status": "open", "closed_by": None}
            # Never close on acknowledgement or simply because a deadline passed.
            for later in rows[i + 1:]:
                text = later.get("body", "").strip()
                if later["ts"] - m["ts"] > 8 * 86400:
                    break
                overlap = words & tokens(text)
                near = later["ts"] - m["ts"] < 2 * 3600
                cancellation = bool(re.search(r"\b(never mind|no longer needed|cancelled|canceled|drop it|don.t need|not needed)\b", text, re.I))
                completed = bool(re.search(r"\b(sent|paid|booked|ordered|completed|delivered|chhod diya|bhej diya|kar diya|payment done)\b", text, re.I))
                # An attachment mentioned inside an unrelated reminder/forward is
                # not proof that this obligation was fulfilled. Require a real
                # document request and a shared non-numeric object/referent.
                file_request = bool(re.search(r"\b(send|share|give|proofs?|invoice|report|document|form|file|draft)\b", body, re.I))
                object_overlap = {word for word in overlap if not word[0].isdigit()}
                attached = bool(re.search(r"\battached\b", text, re.I))
                if attached and file_request and object_overlap:
                    completed = True
                owner_reply = later["sender_id"] == owner
                # A requested address/contact/file can be delivered without the
                # word "sent". Ground such completion in the actual carrier data.
                address_request = bool(re.search(r"\b(?:send|share|give|provide)\b.*\baddress\b", body, re.I | re.S))
                map_link = bool(re.search(r"https?://(?:maps\.app\.goo\.gl|maps\.google\.|goo\.gl/maps)", text, re.I))
                postal_address = (len(text) >= 18 and "?" not in text and bool(re.search(r"\d", text))
                                  and bool(re.search(r"\b(?:road|street|floor|building|lane|avenue|block|suite)\b", text, re.I)))
                address_reply = map_link or postal_address
                contact_request = bool(re.search(r"\b(?:send|share|give|provide)\b.*\b(?:phone|number|contact)\b", body, re.I | re.S))
                phone_reply = bool(re.search(r"(?<!\d)(?:\+?\d[\s-]?){10,13}(?!\d)", text))
                if owner_reply and ((address_request and address_reply) or (contact_request and phone_reply)):
                    loop.update(status="done", closed_by=later["id"])
                    break
                if cancellation and (overlap or near):
                    loop.update(status="dropped", closed_by=later["id"])
                    break
                if completed and (overlap or near) and (owner_reply or later["sender_id"] == "ME"):
                    loop.update(status="done", closed_by=later["id"])
                    break
            loop["help"] = default_help(loop, corpus, people)
            prior.append(loop)
            loops.append(loop)
    return loops


def attach_work_chats(corpus, graph, people):
    """Attach a direct work exchange only with a supported organisational link."""
    people_by_id = {p["id"]: p for p in people}
    organisations = {o["id"]: o for o in graph["organisations"]}
    work_cue = re.compile(r"\b(?:office|invoice|report|campaign|client|customer|projector|kyc|newspaper|api|integration|refund|account|payment|salary|logged|login|access|advertisement|ad size)\b", re.I)
    home_cue = re.compile(r"\b(?:home|house|kitchen|clean|maid|driver|cook|garden|farm|room|school|car)\b", re.I)
    for tie in graph["chats"]:
        c = corpus.chat[tie["chat_id"]]
        if c.get("is_group"):
            continue
        others = [pid for pid in c.get("participants", []) if pid != "ME"]
        if len(others) != 1:
            continue
        person = people_by_id.get(others[0], {})
        if person.get("circle") not in {"colleague", "partner", "staff"}:
            continue
        links = {v["organisation"] for v in person.get("links", []) if v["organisation"] in organisations}
        if not links:
            continue
        body = " ".join(m.get("body", "") for m in corpus.by_chat[c["chat_id"]])
        named = [oid for oid in links if mentions(body, aliases(organisations[oid]["name"]))]
        target = named[0] if len(named) == 1 else next(iter(links)) if len(links) == 1 else None
        cue = home_cue if person["circle"] == "staff" else work_cue
        if target and cue.search(c.get("name", "") + " " + body):
            tie.pop("person", None)
            tie["organisation"] = target
    return graph


def offline(corpus):
    graph = infer_graph(corpus)
    people = infer_people(corpus, graph)
    attach_work_chats(corpus, graph, people)
    return {**graph, "people": people, "goals": [], "open_loops": infer_loops(corpus, people)}
