#!/usr/bin/env python3
"""Summarize a HAR capture of the Crossplay app and redact credentials.

Usage:
    python3 -I tools/har_summary.py capture.har [--dump captures/redacted]

Prints every API endpoint seen (with IDs collapsed to {id}), which auth
headers/cookies each one sends (names only), and flags responses that look
like game state. With --dump, writes redacted JSON response bodies so they
can be shared or used as test fixtures without leaking tokens.
"""

import argparse
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

SECRET_HEADER_RE = re.compile(r"auth|cookie|token|session|secret|key|nyt-s|signature", re.I)
SECRET_FIELD_RE = re.compile(r"token|secret|session|password|cookie|auth|email|signature", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
ID_SEGMENT_RE = re.compile(r"^(\d{3,}|[0-9a-f]{8,}(-[0-9a-f]{4,})*|[A-Za-z0-9_-]{20,})$", re.I)
GAME_KEYS = {"board", "rack", "tiles", "moves", "score", "scores", "bag", "players", "turn", "letters"}
SKIP_TYPES = ("image/", "font/", "text/css", "javascript", "video/", "audio/")


def path_pattern(path):
    return "/".join("{id}" if ID_SEGMENT_RE.match(seg) else seg for seg in path.split("/"))


def redact_url(url):
    parts = urlsplit(url)
    query = [(k, "<redacted>" if SECRET_FIELD_RE.search(k) else v) for k, v in parse_qsl(parts.query)]
    q = f"?{urlencode(query)}" if query else ""
    return f"{parts.scheme}://{parts.netloc}{parts.path}{q}"


def redact(value):
    if isinstance(value, dict):
        return {k: "<redacted>" if SECRET_FIELD_RE.search(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return EMAIL_RE.sub("<email>", value)
    return value


def collect_keys(value, out, depth=0):
    if depth > 6:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(k.lower())
            collect_keys(v, out, depth + 1)
    elif isinstance(value, list):
        for v in value[:20]:
            collect_keys(v, out, depth + 1)


def body_json(entry):
    content = entry.get("response", {}).get("content", {})
    text = content.get("text")
    if not text:
        return None
    if content.get("encoding") == "base64":
        import base64
        try:
            text = base64.b64decode(text).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("har")
    ap.add_argument("--dump", help="directory for redacted JSON response bodies")
    ap.add_argument("--all", action="store_true", help="include static assets")
    args = ap.parse_args()

    entries = json.loads(Path(args.har).read_text())["log"]["entries"]
    endpoints = OrderedDict()
    dump_dir = Path(args.dump) if args.dump else None
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)

    for i, e in enumerate(entries):
        req, resp = e["request"], e["response"]
        mime = resp.get("content", {}).get("mimeType", "")
        if not args.all and any(t in mime for t in SKIP_TYPES):
            continue
        parts = urlsplit(req["url"])
        key = (req["method"], parts.netloc, path_pattern(parts.path))
        ep = endpoints.setdefault(key, {"count": 0, "statuses": set(), "auth": set(),
                                        "game_keys": set(), "example": redact_url(req["url"])})
        ep["count"] += 1
        ep["statuses"].add(resp.get("status"))
        for h in req.get("headers", []):
            if SECRET_HEADER_RE.search(h["name"]):
                ep["auth"].add(f"header:{h['name']}")
        for c in req.get("cookies", []):
            ep["auth"].add(f"cookie:{c['name']}")

        data = body_json(e)
        if data is None:
            continue
        keys = set()
        collect_keys(data, keys)
        ep["game_keys"] |= keys & GAME_KEYS
        if dump_dir:
            name = re.sub(r"[^A-Za-z0-9]+", "_", f"{req['method']}_{parts.netloc}{key[2]}").strip("_")
            (dump_dir / f"{i:04d}_{name[:120]}.json").write_text(json.dumps(redact(data), indent=2))

    ranked = sorted(endpoints.items(), key=lambda kv: (-len(kv[1]["game_keys"]), kv[0]))
    for (method, host, pattern), ep in ranked:
        flag = "  <-- looks like game state" if len(ep["game_keys"]) >= 2 else ""
        print(f"{method} {host}{pattern}  x{ep['count']}  status={sorted(ep['statuses'], key=str)}{flag}")
        print(f"    example: {ep['example']}")
        if ep["auth"]:
            print(f"    auth:    {', '.join(sorted(ep['auth']))}")
        if ep["game_keys"]:
            print(f"    keys:    {', '.join(sorted(ep['game_keys']))}")
    if dump_dir:
        print(f"\nRedacted bodies written to {dump_dir}/ — skim them for names before sharing.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
