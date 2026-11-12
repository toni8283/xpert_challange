#!/usr/bin/env python3
"""Generate a fresh, non-private smoke input without overwriting existing inputs."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", default="example")
    folder = Path(parser.parse_args().folder)
    folder.mkdir(parents=True, exist_ok=True)
    names = ("chats.jsonl", "messages.jsonl", "seed.json")
    if any((folder / name).exists() for name in names):
        parser.error("Input files already exist; choose an empty folder")
    chat = {"chat_id": "conversation-a", "name": "Sam", "is_group": False, "participants": ["ME", "contact-a"]}
    items = [("ME", "I'll send the revised invoice tomorrow"), ("contact-a", "Okay, thanks"),
             ("ME", "I sent the revised invoice"), ("contact-a", "Please prepare a draft proposal for the next project")]
    messages = [{"id": "message-%d" % i, "chat_id": chat["chat_id"], "sender_id": sender,
                 "sender_name": "Reva" if sender == "ME" else "Sam", "ts": 1791160200 + i * 3600,
                 "kind": "text", "body": body, "quoted_id": None} for i, (sender, body) in enumerate(items)]
    (folder / "chats.jsonl").write_text(json.dumps(chat) + "\n", encoding="utf-8")
    (folder / "messages.jsonl").write_text("".join(json.dumps(m) + "\n" for m in messages), encoding="utf-8")
    (folder / "seed.json").write_text(json.dumps({"circles": {"contact-a": "client"}, "organisations": [], "goals": []}), encoding="utf-8")
    print("Generated synthetic example in " + str(folder))


if __name__ == "__main__":
    main()
