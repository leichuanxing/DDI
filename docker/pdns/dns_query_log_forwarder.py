#!/usr/bin/env python3
"""
Read dnsmasq query lines from stdin (stderr piped from dnsmasq with log-queries + log-facility=-)
and POST each query to ddi-web /api/dns/query-logs/ingest/.

Typical line:
  dnsmasq[1]: query[A] example.com from 192.168.1.10
  dnsmasq[1]: tcp query[AAAA] example.com from 2001:db8::1#12345
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

INGEST_URL = os.environ.get(
    "DDI_WEB_INGEST_URL",
    "http://ddi-web:8000/api/dns/query-logs/ingest/",
)
TIMEOUT = float(os.environ.get("DDI_WEB_INGEST_TIMEOUT", "3"))
DISABLED = os.environ.get("DNS_QUERY_LOG_INGEST", "1").lower() in {"0", "false", "no"}

# dnsmasq: "dnsmasq[pid]: query[TYPE] name from client" or with "tcp " before query
_QUERY_RE = re.compile(
    r"dnsmasq\[\d+\]:\s*(?:tcp\s+)?query\[([^\]]+)\]\s+(\S+)\s+from\s+(.+?)\s*$",
    re.IGNORECASE,
)


def _normalize_client(raw: str) -> str:
    s = (raw or "").strip()
    if "#" in s and not s.startswith("["):
        s = s.split("#", 1)[0].strip()
    return s


def _post(payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        INGEST_URL,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        if resp.status >= 400:
            print(f"ingest HTTP {resp.status}", file=sys.stderr)


def main() -> None:
    if DISABLED:
        for _line in sys.stdin:
            pass
        return
    for line in sys.stdin:
        line = line.strip()
        if "query[" not in line or " from " not in line:
            continue
        m = _QUERY_RE.search(line)
        if not m:
            continue
        qtype, qname, client_raw = m.group(1), m.group(2), m.group(3)
        qname = (qname or "").strip().lower()
        client_ip = _normalize_client(client_raw)
        if not qname:
            continue
        payload = {
            "query_name": qname,
            "query_type": (qtype or "").strip().upper(),
            "client_ip": client_ip or None,
            "protocol": "TCP" if "tcp query[" in line.lower() else "UDP",
            "raw_message": line[:2000],
        }
        try:
            _post(payload)
        except urllib.error.HTTPError as e:
            print(f"ingest HTTPError {e.code}: {e.reason}", file=sys.stderr)
        except urllib.error.URLError as e:
            print(f"ingest URLError: {e.reason}", file=sys.stderr)
        except Exception as e:
            print(f"ingest error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
