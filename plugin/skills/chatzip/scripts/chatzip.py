#!/usr/bin/env python3
"""chatzip - turn AI data exports into one zip: a folder per AI, a text file per chat.

usage: python chatzip.py OUT.zip EXPORT [EXPORT ...] [--with-replies]

EXPORT is a data export (.zip or .json) from Claude, ChatGPT, Gemini (Google Takeout,
My Activity as JSON), Grok or DeepSeek, or a chatvault archive. Standard library only.
"""
import argparse
import html
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def iso(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc).isoformat()
    if isinstance(v, dict):
        d = v.get("$date")
        n = d.get("$numberLong") if isinstance(d, dict) else d
        if n is None:
            return None
        try:
            return iso(float(n))
        except (TypeError, ValueError):
            return str(n)
    return str(v)


def strip_html(s):
    s = re.sub(r"(?i)<br\s*/?>|</(p|li|h\d|div|tr|pre)>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]*>", "", s))
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def parse_mapping(data):
    """ChatGPT and DeepSeek both export a 'mapping' tree of messages."""
    deepseek, convs = False, []
    for c in data:
        mp = c.get("mapping") or {}
        chain, node = [], c.get("current_node")
        if node:
            while node and mp.get(node):
                chain.append(mp[node])
                node = mp[node].get("parent")
            chain.reverse()
        else:
            node = "root" if "root" in mp else next((k for k, v in mp.items() if not v.get("parent")), None)
            seen = set()
            while node and mp.get(node) and node not in seen:
                seen.add(node)
                chain.append(mp[node])
                kids = mp[node].get("children") or []
                node = kids[-1] if kids else None
        msgs = []
        for e in chain:
            m = e.get("message")
            if not m:
                continue
            if isinstance(m.get("fragments"), list):
                deepseek = True
                for f in m["fragments"]:
                    role = {"REQUEST": "user", "RESPONSE": "assistant"}.get(f.get("type"))
                    text = str(f.get("content") or "").strip()
                    if role and text:
                        msgs.append((role, text))
                continue
            role = (m.get("author") or {}).get("role")
            if role not in ("user", "assistant"):
                continue
            parts = (m.get("content") or {}).get("parts") or []
            text = "\n".join(p for p in parts if isinstance(p, str)).strip()
            if text:
                msgs.append((role, text))
        date = c.get("create_time") or c.get("inserted_at") or c.get("update_time") or c.get("updated_at")
        convs.append({"title": c.get("title"), "date": iso(date), "messages": msgs})
    return [("DeepSeek" if deepseek else "ChatGPT", convs)]


def parse_claude(data):
    convs = []
    for c in data:
        msgs = []
        for m in c.get("chat_messages", []):
            text = (m.get("text") or "").strip()
            if not text:
                text = "\n".join(b.get("text", "") for b in m.get("content", []) if b.get("type") == "text").strip()
            if text:
                msgs.append(("user" if m.get("sender") == "human" else "assistant", text))
        convs.append({"title": c.get("name"), "date": iso(c.get("created_at")), "messages": msgs})
    return [("Claude", convs)]


def parse_grok(data):
    convs = []
    for c in data["conversations"]:
        info, msgs = c.get("conversation") or {}, []
        for r in c.get("responses") or []:
            m = r.get("response") or r
            text = str(m.get("message") or "").strip()
            if text:
                who = str(m.get("sender") or "").lower()
                msgs.append(("user" if who in ("human", "user") else "assistant", text))
        convs.append({"title": info.get("title"), "date": iso(info.get("create_time") or info.get("created_at")), "messages": msgs})
    return [("Grok", convs)]


def parse_gemini(data):
    """Takeout 'My Activity' has one entry per prompt and no chat ids: group by day."""
    days = {}
    for it in data:
        if not re.search("gemini", it.get("header") or "", re.I) or not it.get("title"):
            continue
        t = str(it.get("time") or "")
        turn = [("user", re.sub(r"^Prompted\s+", "", str(it["title"])).strip())]
        reply = "\n".join(strip_html(h.get("html") or "") for h in it.get("safeHtmlItem") or []).strip()
        if reply:
            turn.append(("assistant", reply))
        days.setdefault(t[:10] or "undated", []).append((t, turn))
    convs = [{"title": "Gemini prompts", "date": None if day == "undated" else day,
              "messages": [m for _, turn in sorted(turns, key=lambda x: x[0]) for m in turn]}
             for day, turns in days.items()]
    return [("Gemini", convs)] if convs else []


def parse_archive(data):
    names, by = {"claude": "Claude", "chatgpt": "ChatGPT"}, {}
    for c in data:
        src = str(c.get("source") or "other")
        by.setdefault(names.get(src, src[:1].upper() + src[1:]), []).append({
            "title": c.get("title"), "date": iso(c.get("created_at") or c.get("updated_at")),
            "messages": [(m["role"], m["text"]) for m in c.get("messages", []) if (m.get("text") or "").strip()]})
    return list(by.items())


def detect(doc):
    """Return [(ai_name, conversations)] for one parsed JSON document, or [] if it isn't a chat export."""
    if isinstance(doc, list) and doc and isinstance(doc[0], dict):
        f = doc[0]
        if "mapping" in f:
            return parse_mapping(doc)
        if "chat_messages" in f:
            return parse_claude(doc)
        if "header" in f and "title" in f and "time" in f:
            return parse_gemini(doc)
        if "messages" in f and "source" in f:
            return parse_archive(doc)
    if isinstance(doc, dict) and isinstance(doc.get("conversations"), list) \
            and any(isinstance(c, dict) and c.get("responses") for c in doc["conversations"]):
        return parse_grok(doc)
    return []


def read_export(path):
    path = Path(path)
    if zipfile.is_zipfile(path):
        docs = []
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                m = re.search(r"(^|/)(conversations[^/]*|prod-grok-backend|MyActivity)\.json$", n, re.I)
                if not m or (m.group(2).lower() == "myactivity" and not re.search("gemini", n, re.I)):
                    continue
                docs.append(json.loads(z.read(n)))
        return docs
    return [json.loads(path.read_text(encoding="utf-8"))]


def build_files(groups, with_replies=False):
    files, used, seen = [], set(), set()
    for ai, convs in groups:
        for c in convs:
            msgs = c["messages"] if with_replies else [m for m in c["messages"] if m[0] == "user"]
            if not any(r == "user" for r, _ in msgs):
                continue
            day = (c["date"] or "")[:10]
            title = re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", str(c["title"] or "Untitled"))).strip()[:80].rstrip(". ") or "Untitled"
            if with_replies:
                body = "\n\n".join(f"{'You' if r == 'user' else ai}:\n{t}" for r, t in msgs)
            else:
                body = "\n\n---\n\n".join(t for _, t in msgs)
            base = f"{ai}/{day + ' ' if day else ''}{title}"
            if (base, body) in seen:  # same chat given twice
                continue
            seen.add((base, body))
            name, n = base + ".txt", 2
            while name.lower() in used:
                name, n = f"{base} ({n}).txt", n + 1
            used.add(name.lower())
            files.append((name, f"Title: {c['title'] or 'Untitled'}\nAI: {ai}\nDate: {day or 'unknown'}\n\n{body}\n"))
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", help="zip file to write")
    ap.add_argument("exports", nargs="+", help="export files (.zip or .json)")
    ap.add_argument("--with-replies", action="store_true", help="include the AI's replies (default: only your messages)")
    a = ap.parse_args(argv)
    groups, failed = [], False
    for f in a.exports:
        try:
            found = [g for doc in read_export(f) for g in detect(doc)]
        except (OSError, ValueError, KeyError, TypeError) as e:
            found, failed = None, True
            print(f"{f}: could not read ({e})", file=sys.stderr)
        if found == []:
            failed = True
            print(f"{f}: no chats recognised", file=sys.stderr)
        groups += found or []
    files = build_files(groups, a.with_replies)
    if not files:
        print("No chats found; nothing written.", file=sys.stderr)
        return 1
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files:
            z.writestr(name, text)
    counts = {}
    for name, _ in files:
        counts[name.split("/")[0]] = counts.get(name.split("/")[0], 0) + 1
    print(f"wrote {a.out}: " + ", ".join(f"{ai} {n}" for ai, n in counts.items()))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
