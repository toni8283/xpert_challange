"""OpenAI-compatible client with bounded retries, disk cache and token accounting."""
import hashlib
import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class ModelError(RuntimeError):
    pass


class BudgetExceeded(ModelError):
    """Local resource limit: retain completed work and fall back for remaining batches."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError("Model endpoint redirected; configure its final API base URL explicitly")


def parse_object(text):
    if not isinstance(text, str):
        raise ValueError("Model returned no text content")
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    index = text.find("{")
    if index >= 0:
        try:
            value, _ = decoder.raw_decode(text[index:])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    raise ValueError("Model response is not a complete JSON object")


class Client:
    def __init__(self, run_dir, cache_dir, deadline, transport=None):
        self.base = os.environ["LLM_BASE_URL"].rstrip("/")
        parsed = urllib.parse.urlparse(self.base)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("LLM_BASE_URL must use HTTPS (HTTP is permitted for local tests)")
        self.key = os.environ["LLM_API_KEY"]
        self.model = os.environ["LLM_MODEL"]
        self.free_only = parsed.hostname == "openrouter.ai" and self.model.endswith(":free")
        self.run_dir = Path(run_dir)
        self.cache_dir = Path(cache_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.deadline = deadline
        self.lock = threading.Lock()
        self.calls = 0
        self.max_calls = int(os.getenv("XPERT_MAX_CALLS", "40" if self.free_only else "200"))
        self.min_interval = max(0.0, min(60.0, float(os.getenv("XPERT_MIN_REQUEST_INTERVAL", "3.2" if self.free_only else "0"))))
        self.next_request_at = 0.0
        self.json_format = os.getenv("LLM_JSON_MODE", "1") != "0"
        self.opener = urllib.request.build_opener(NoRedirect())
        self.transport = transport or self._request
        self.stats = {"api_calls": 0, "cache_hits": 0, "prompt_tokens": 0, "completion_tokens": 0, "usage_missing": 0, "retries": 0, "stages": {}}

    def _request(self, body, timeout):
        request = urllib.request.Request(self.base + "/chat/completions", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                         headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        with self.opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _log(self, entry):
        with self.lock:
            with (self.run_dir / "usage.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if entry.get("cached"):
                self.stats["cache_hits"] += 1
                return
            self.stats["api_calls"] += 1
            self.stats["prompt_tokens"] += entry.get("prompt_tokens") or 0
            self.stats["completion_tokens"] += entry.get("completion_tokens") or 0
            self.stats["usage_missing"] += int(entry.get("usage_missing", False))
            stage = self.stats["stages"].setdefault(entry["stage"], {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
            stage["calls"] += 1
            stage["prompt_tokens"] += entry.get("prompt_tokens") or 0
            stage["completion_tokens"] += entry.get("completion_tokens") or 0

    def json(self, stage, system, payload, max_tokens=9000):
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]
        body = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
        if self.free_only:
            # Never silently route a free test to a paid or data-collecting endpoint.
            body["provider"] = {"max_price": {"prompt": 0, "completion": 0},
                                "allow_fallbacks": False, "data_collection": "deny"}
        if self.json_format:
            body["response_format"] = {"type": "json_object"}
        if urllib.parse.urlparse(self.base).hostname == "openrouter.ai" and "gpt-oss" in self.model:
            body["reasoning"] = {"effort": "low"}
        # JSON mode is an optional transport feature, not part of the semantic task.
        cache_body = {k: v for k, v in body.items() if k != "response_format"}
        fingerprint = hashlib.sha256(json.dumps({"endpoint": self.base, "body": cache_body}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = self.cache_dir / (fingerprint + ".json")
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    self._log({"stage": stage, "request_hash": fingerprint, "model": self.model, "cached": True})
                    return value
            except (OSError, ValueError):
                pass
        last = None
        for attempt in range(4):
            remaining = self.deadline - time.monotonic()
            if remaining < 4:
                raise BudgetExceeded("Run time budget exhausted")
            with self.lock:
                if self.calls >= self.max_calls:
                    raise BudgetExceeded("Model call limit exhausted")
                now = time.monotonic()
                wait = max(0.0, self.next_request_at - now)
                if now + wait >= self.deadline - 4:
                    raise BudgetExceeded("Run time budget exhausted while pacing requests")
                self.next_request_at = max(now, self.next_request_at) + self.min_interval
                self.calls += 1
            if wait:
                time.sleep(wait)
            remaining = self.deadline - time.monotonic()
            started = time.monotonic()
            try:
                data = self.transport(body, min(75, remaining - 1))
                if data.get("error"):
                    error = data["error"]
                    code = error.get("code", 500) if isinstance(error, dict) else 500
                    try:
                        code = int(code)
                    except (ValueError, TypeError):
                        code = 500
                    raise urllib.error.HTTPError(self.base, code, "Model endpoint error", {}, None)
                choices = data.get("choices") or []
                if not choices:
                    raise ValueError("No choices in model response")
                choice = choices[0]
                usage = data.get("usage") or {}
                self._log({"stage": stage, "request_hash": fingerprint, "model": self.model,
                           "cached": False, "prompt_tokens": usage.get("prompt_tokens"),
                           "completion_tokens": usage.get("completion_tokens"),
                           "usage_missing": not ("prompt_tokens" in usage and "completion_tokens" in usage),
                           "seconds": round(time.monotonic() - started, 3), "finish_reason": choice.get("finish_reason")})
                if choice.get("finish_reason") in {"length", "max_tokens"}:
                    raise ValueError("Model output truncated; increase LLM_MAX_OUTPUT_TOKENS or reduce batch size")
                content = choice.get("message", {}).get("content")
                if isinstance(content, list):
                    content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
                value = parse_object(content)
                temporary = path.with_suffix(".%s.tmp" % threading.get_ident())
                temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                temporary.chmod(0o600)
                temporary.replace(path)
                return value
            except urllib.error.HTTPError as exc:
                if exc.code in {400, 422} and "response_format" in body:
                    body.pop("response_format", None)
                    self.json_format = False
                    last = "API rejected optional JSON-mode parameters"
                elif exc.code in {408, 409, 429, 500, 502, 503, 504}:
                    last = "Temporary model HTTP error %d" % exc.code
                else:
                    raise ModelError("Model HTTP error %d. Check key, credits, model ID and base URL; no offline substitution was made." % exc.code) from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = "Temporary model connection failure (%s)" % type(exc).__name__
            except (ValueError, KeyError, TypeError) as exc:
                last = str(exc)
                body["messages"][0]["content"] = system + "\nReturn a COMPLETE JSON object only. Be concise; no markdown or commentary."
            if attempt < 3:
                with self.lock:
                    self.stats["retries"] += 1
                delay = min(12, 2 ** attempt + random.random())
                if time.monotonic() + delay >= self.deadline:
                    break
                time.sleep(delay)
        raise ModelError("Model request failed after bounded retries: " + str(last))
