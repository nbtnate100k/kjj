from __future__ import annotations

import json
import os
import queue
import threading
from typing import Any, Generator

from flask import Flask, Response, jsonify, request

# ----- lookup_service (inlined for Railway) -----

import html
import json
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

# --- cards ---

MAX_CARDS = 3000

CARD_RE_4 = re.compile(r"\d{13,19}\|\|\d{2}\|\|\d{2}\|\|\d{3}")
CARD_RE_3 = re.compile(r"\d{13,19}\|\|\d{2}\|\|\d{3}")
CARD_PATTERNS = (CARD_RE_4, CARD_RE_3)

RESULT_FIELDS = (
    "Card Scheme",
    "Card Type",
    "Brand",
    "Issuing Bank",
    "Country",
)

EMPTY_CONTACT: dict[str, str] = {
    "name": "",
    "address": "",
    "city": "",
    "state": "",
    "zip": "",
    "phone": "",
    "email": "",
}


@dataclass
class CardEntry:
    card: str
    line: str
    contact: dict[str, str] = field(default_factory=lambda: dict(EMPTY_CONTACT))


def input_lines(raw: str) -> list[str]:
    return [
        line.strip()
        for line in raw.replace("\r\n", "\n").split("\n")
        if line.strip() and line.strip().upper() != "DONE"
    ]


def pan_digits(part: str) -> str:
    return re.sub(r"\D", "", part)


def is_valid_pan(part: str) -> bool:
    digits = pan_digits(part)
    return 13 <= len(digits) <= 19


def normalize_card_for_display(card: str) -> str:
    parts = [p.strip() for p in card.split("|")]
    pan = parts[0] if parts else ""
    if (
        len(parts) >= 4
        and re.fullmatch(r"\d{2}", parts[1] or "")
        and re.fullmatch(r"\d{2}", parts[2] or "")
        and re.fullmatch(r"\d{3}", parts[3] or "")
    ):
        return f"{pan}|{parts[1]}|{parts[2]}|{parts[3]}"
    if len(parts) >= 3:
        exp = parts[1]
        cvv = parts[2].replace(" ", "")
        slash = re.match(r"^(\d{2})/(\d{2})$", exp)
        if slash:
            return f"{pan}|{slash.group(1)}|{slash.group(2)}|{cvv}"
    return card.strip()


def card_from_line(line: str) -> str | None:
    trimmed = line.strip()
    if not trimmed or trimmed.upper() == "DONE":
        return None
    for pattern in CARD_PATTERNS:
        match = pattern.search(trimmed)
        if match:
            return match.group(0)
    flex4 = re.search(r"(\d{13,19})\D+(\d{2})\D+(\d{2})\D+(\d{3})", trimmed)
    if flex4:
        return f"{flex4.group(1)}|{flex4.group(2)}|{flex4.group(3)}|{flex4.group(4)}"
    flex3 = re.search(r"(\d{13,19})\D+(\d{2,4})\D+(\d{3,4})", trimmed)
    if flex3:
        return f"{flex3.group(1)}|{flex3.group(2)}|{flex3.group(3)}"
    digits_only = re.sub(r"\D", "", trimmed)
    if 13 <= len(digits_only) <= 19:
        return digits_only
    return None


def contact_from_parts(parts: list[str], start: int) -> dict[str, str]:
    return {
        "name": parts[start] if start < len(parts) else "",
        "address": parts[start + 1] if start + 1 < len(parts) else "",
        "city": parts[start + 2] if start + 2 < len(parts) else "",
        "state": parts[start + 3] if start + 3 < len(parts) else "",
        "zip": parts[start + 4] if start + 4 < len(parts) else "",
        "phone": parts[start + 5] if start + 5 < len(parts) else "",
        "email": parts[start + 6] if start + 6 < len(parts) else "",
    }


def parse_line_entry(line: str) -> CardEntry | None:
    trimmed = line.strip()
    if not trimmed:
        return None
    parts = [p.strip() for p in trimmed.split("|")]

    if len(parts) >= 10 and is_valid_pan(parts[0]):
        return CardEntry(
            line=trimmed,
            card=f"{parts[0]}|{parts[1]}|{parts[2]}",
            contact=contact_from_parts(parts, 3),
        )

    if len(parts) >= 4 and is_valid_pan(parts[0]):
        four_part = (
            re.fullmatch(r"\d{2}", parts[1] or "")
            and re.fullmatch(r"\d{2}", parts[2] or "")
            and re.fullmatch(r"\d{3}", parts[3] or "")
        )
        if four_part:
            card = f"{parts[0]}|{parts[1]}|{parts[2]}|{parts[3]}"
            contact = contact_from_parts(parts, 4) if len(parts) > 4 else dict(EMPTY_CONTACT)
            return CardEntry(line=trimmed, card=card, contact=contact)

    if len(parts) >= 3 and is_valid_pan(parts[0]):
        card = f"{parts[0]}|{parts[1]}|{parts[2]}"
        contact = contact_from_parts(parts, 3) if len(parts) > 3 else dict(EMPTY_CONTACT)
        return CardEntry(line=trimmed, card=card, contact=contact)

    card = card_from_line(trimmed)
    if not card:
        return None
    card_index = trimmed.index(card)
    after = trimmed[card_index + len(card) :].lstrip("|,; \t")
    tail = [p.strip() for p in after.split("|")] if after else []
    return CardEntry(line=trimmed, card=card, contact=contact_from_parts(tail, 0))


def parse_card_entries_from_input(raw: str) -> list[CardEntry]:
    entries: list[CardEntry] = []
    for line in input_lines(raw):
        entry = parse_line_entry(line)
        if entry:
            entries.append(entry)
    if not entries:
        raise ValueError(
            "No cards found. Paste one row per line, e.g.:\n"
            "  5343480605798163|01/31|998|Judi Bradley|2218 wessinger Rd|Chapin|SC|29036|8036067391|email@example.com"
        )
    if len(entries) > MAX_CARDS:
        raise ValueError(f"Maximum {MAX_CARDS} cards allowed (found {len(entries)}).")
    return entries


def bin_from_card(card: str) -> str:
    card_part = card.split("|", 1)[0]
    digits = re.sub(r"\D", "", card_part)
    if len(digits) < 6:
        raise ValueError(f"Card number too short: {card}")
    return digits[:6]


def unique_bins_from_entries(entries: list[CardEntry]) -> list[str]:
    bins: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        b = bin_from_card(entry.card)
        if b not in seen:
            seen.add(b)
            bins.append(b)
    return bins


def card_match_key_from_parts(card: str) -> str:
    return normalize_card_for_display(card)


def field_block(label: str, value: str) -> list[str]:
    return [label, value, ""]


def format_card_block(
    index: int,
    total: int,
    card: str,
    contact: dict[str, str],
    data: dict[str, Any],
) -> str:
    lines: list[str] = [
        "=" * 60,
        f"Card {index} of {total}",
        normalize_card_for_display(card),
        f"BIN: {bin_from_card(card)}",
        "=" * 60,
    ]
    if data.get("error"):
        lines.append(str(data["error"]))
    else:
        for label in RESULT_FIELDS:
            lines.extend(field_block(label, str(data.get(label, ""))))
        iso = data.get("ISO", "")
        if iso:
            lines.extend([iso, ""])
    lines.extend(field_block("Name", contact.get("name", "")))
    lines.extend(field_block("Address", contact.get("address", "")))
    lines.extend(field_block("City", contact.get("city", "")))
    lines.extend(field_block("State", contact.get("state", "")))
    lines.extend(field_block("ZIP", contact.get("zip", "")))
    lines.extend(field_block("Phone", contact.get("phone", "")))
    lines.extend(field_block("Email", contact.get("email", "")))
    lines.extend(field_block("Type", ""))
    lines.append("")
    return "\n".join(lines)


# --- lookup ---

MAX_WORKERS = 8
FIRST_PASS_ATTEMPTS = 6
REQUEST_DELAY_SEC = 0.2
RATE_LIMIT_BACKOFF_CAP_SEC = 45.0
NAMSO_API_URL = "https://namso.live/api/v1/bin.php?bin={bin}"

_request_semaphore = threading.Semaphore(3)
_cooldown_lock = threading.Lock()
_cooldown_until = 0.0


def _respect_global_cooldown() -> None:
    with _cooldown_lock:
        now = time.monotonic()
        if now < _cooldown_until:
            time.sleep(_cooldown_until - now)


def _extend_global_cooldown(attempt: int) -> None:
    global _cooldown_until
    extra = min(30.0, 1.5 * (2 ** min(attempt, 5)))
    with _cooldown_lock:
        _cooldown_until = max(_cooldown_until, time.monotonic() + extra)


def _is_rate_limit_message(text: str) -> bool:
    lowered = text.lower()
    return "too many request" in lowered or "rate limit" in lowered or "429" in lowered


def _is_rate_limited_result(data: dict[str, str]) -> bool:
    return _is_rate_limit_message(str(data.get("error", "")))


def _parse_namso_response(payload: dict[str, Any], bin_number: str) -> dict[str, str]:
    status = str(payload.get("Status") or "").upper()
    if status != "SUCCESS":
        message = payload.get("Message") or f"BIN {bin_number} not found."
        return {"error": str(message)}
    country = payload.get("Country") or {}
    alpha2 = str(country.get("A2") or "").upper()
    return {
        "Card Scheme": str(payload.get("Scheme") or "").upper(),
        "Card Type": str(payload.get("Type") or "").upper(),
        "Brand": str(payload.get("CardTier") or "").upper(),
        "Issuing Bank": str(payload.get("Issuer") or "UNKNOWN").upper(),
        "Country": str(country.get("Name") or "").upper(),
        "ISO": f"ISO: {alpha2} / {alpha2}" if alpha2 else "",
    }


def _fetch_bin_once(bin_number: str) -> dict[str, str]:
    with _request_semaphore:
        _respect_global_cooldown()
        request = urllib.request.Request(
            NAMSO_API_URL.format(bin=bin_number),
            headers={
                "User-Agent": "Mozilla/5.0 (BIN-Lookup)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            time.sleep(REQUEST_DELAY_SEC)
            return _parse_namso_response(payload, bin_number)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                return {"error": f"Too many requests for BIN {bin_number}."}
            return {"error": f"Lookup failed (HTTP {exc.code})."}
        except Exception as exc:
            return {"error": str(exc)}


def fetch_bin_quick(bin_number: str, max_attempts: int = FIRST_PASS_ATTEMPTS) -> dict[str, str]:
    for attempt in range(max_attempts):
        result = _fetch_bin_once(bin_number)
        if not _is_rate_limited_result(result):
            return result
        _extend_global_cooldown(attempt)
        time.sleep(min(RATE_LIMIT_BACKOFF_CAP_SEC, 0.75 * (2**min(attempt, 4))))
    return result


def fetch_bin_until_ok(bin_number: str) -> dict[str, str]:
    attempt = 0
    while True:
        result = _fetch_bin_once(bin_number)
        if not _is_rate_limited_result(result):
            return result
        _extend_global_cooldown(attempt)
        time.sleep(min(RATE_LIMIT_BACKOFF_CAP_SEC, 1.0 * (2 ** min(attempt, 8))))
        attempt += 1


def fetch_bin(bin_number: str) -> dict[str, str]:
    return fetch_bin_until_ok(bin_number)


def lookup_bins_with_progress(
    unique_bins: list[str],
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, dict[str, str]]:
    total = len(unique_bins)
    if total == 0:
        return {}

    cache: dict[str, dict[str, str]] = {}
    retry_queue: list[str] = []
    done = 0
    progress_lock = threading.Lock()

    def report() -> None:
        if on_progress:
            on_progress(done, total)

    def first_pass(bin_number: str) -> None:
        nonlocal done
        result = fetch_bin_quick(bin_number)
        with progress_lock:
            if _is_rate_limited_result(result):
                retry_queue.append(bin_number)
            else:
                cache[bin_number] = result
                done += 1
            report()

    workers = min(MAX_WORKERS, total)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(first_pass, unique_bins))

    for bin_number in retry_queue:
        cache[bin_number] = fetch_bin_until_ok(bin_number)
        done += 1
        report()

    return cache


# --- format_html ---

RESULT_HTML_STYLES = """
  body { font-family: ui-sans-serif, system-ui, sans-serif; background: #f4f4f5; color: #18181b; margin: 0; padding: 24px; }
  .result-document { max-width: 720px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }
  .result-card { background: #fff; border: 1px solid #e4e4e7; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,.06); }
  .result-header { background: #18181b; color: #fafafa; padding: 16px 20px; }
  .result-header h2 { margin: 0 0 8px; font-size: 1rem; font-weight: 600; }
  .result-header .pan { font-family: ui-monospace, monospace; font-size: 0.95rem; word-break: break-all; }
  .result-header .bin { margin-top: 6px; font-size: 0.85rem; color: #a1a1aa; }
  .result-body { padding: 16px 20px 20px; display: flex; flex-direction: column; gap: 12px; }
  .result-section-title { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #71717a; margin-top: 4px; }
  .result-field { display: grid; grid-template-columns: 140px 1fr; gap: 8px 16px; padding: 8px 0; border-bottom: 1px solid #f4f4f5; }
  .result-field:last-child { border-bottom: none; }
  .result-label { font-size: 0.8rem; font-weight: 600; color: #52525b; }
  .result-value { font-size: 0.9rem; word-break: break-word; }
  .result-error { color: #b91c1c; font-weight: 600; padding: 12px 20px; }
"""


def _field_row(label: str, value: str) -> str:
    return (
        f'<div class="result-field"><div class="result-label">{html.escape(label)}</div>'
        f'<div class="result-value">{html.escape(value)}</div></div>'
    )


def format_card_block_html(
    index: int,
    total: int,
    card: str,
    contact: dict[str, str],
    data: dict[str, Any],
) -> str:
    display = normalize_card_for_display(card)
    header = f"""<article class="result-card">
  <header class="result-header">
    <h2>Card {index} of {total}</h2>
    <div class="pan">{html.escape(display)}</div>
    <div class="bin">BIN: {html.escape(bin_from_card(card))}</div>
  </header>"""
    if data.get("error"):
        return f'{header}<div class="result-error">{html.escape(str(data["error"]))}</div></article>'

    issuer_fields = "".join(_field_row(label, str(data.get(label, ""))) for label in RESULT_FIELDS)
    iso = data.get("ISO", "")
    iso_html = _field_row("ISO", str(iso).replace("ISO: ", "", 1)) if iso else ""
    contact_fields = "".join(
        [
            _field_row("Name", contact.get("name", "")),
            _field_row("Address", contact.get("address", "")),
            _field_row("City", contact.get("city", "")),
            _field_row("State", contact.get("state", "")),
            _field_row("ZIP", contact.get("zip", "")),
            _field_row("Phone", contact.get("phone", "")),
            _field_row("Email", contact.get("email", "")),
            _field_row("Type", ""),
        ]
    )
    return f"""{header}
  <div class="result-body">
    <div class="result-section-title">Issuer</div>
    {issuer_fields}
    {iso_html}
    <div class="result-section-title">Contact</div>
    {contact_fields}
  </div>
</article>"""


def format_results_body_html(results: list[dict[str, Any]]) -> str:
    total = len(results)
    return "\n".join(
        format_card_block_html(r["index"], total, r["card"], r["contact"], r["data"])
        for r in results
    )


def wrap_results_document(body_html: str, title: str = "BIN Lookup Results") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>{RESULT_HTML_STYLES}</style>
</head>
<body>
  <div class="result-document">
    {body_html}
  </div>
</body>
</html>"""


def format_all_results_html(results: list[dict[str, Any]]) -> str:
    return wrap_results_document(format_results_body_html(results))


def format_results_preview_fragment(results: list[dict[str, Any]]) -> str:
    return f'<div class="result-document">{format_results_body_html(results)}</div>'


# --- combine ---


def _parse_summary_line(line: str) -> dict[str, Any] | None:
    trimmed = line.strip()
    if not trimmed:
        return None
    tab_parts = [p.strip() for p in trimmed.split("\t")]
    if len(tab_parts) < 2:
        return None
    card = tab_parts[0]
    name = tab_parts[1] if len(tab_parts) > 1 else ""
    key = card_match_key_from_parts(card)
    if len(tab_parts) > 2 and tab_parts[2].upper().startswith("ERROR"):
        return {"key": key, "card": card, "name": name, "data": {"error": " ".join(tab_parts[2:])}}
    country = tab_parts[6] if len(tab_parts) > 6 else ""
    return {
        "key": key,
        "card": card,
        "name": name,
        "data": {
            "Card Scheme": tab_parts[2] if len(tab_parts) > 2 else "",
            "Card Type": tab_parts[3] if len(tab_parts) > 3 else "",
            "Brand": tab_parts[4] if len(tab_parts) > 4 else "",
            "Issuing Bank": tab_parts[5] if len(tab_parts) > 5 else "",
            "Country": country,
            "ISO": f"ISO: {country} / {country}" if country else "",
        },
    }


def _parse_full_row_line(line: str) -> dict[str, Any] | None:
    trimmed = line.strip()
    if not trimmed:
        return None
    parts = [p.strip() for p in trimmed.split("|")]
    if len(parts) < 3:
        return None
    four_part = (
        len(parts) >= 4
        and re.fullmatch(r"\d{2}", parts[1] or "")
        and re.fullmatch(r"\d{2}", parts[2] or "")
        and re.fullmatch(r"\d{3}", parts[3] or "")
    )
    if four_part and is_valid_pan(parts[0]):
        card = f"{parts[0]}|{parts[1]}|{parts[2]}|{parts[3]}"
        contact = contact_from_parts(parts, 4) if len(parts) > 4 else contact_from_parts(parts, 3)
    else:
        card = f"{parts[0]}|{parts[1]}|{parts[2]}"
        contact = contact_from_parts(parts, 3)
    key = card_match_key_from_parts(card)
    if len(parts) >= 10 and is_valid_pan(parts[0]):
        contact = contact_from_parts(parts, 3)
    return {"key": key, "card": card, "contact": contact}


def combine_issuer_and_full_rows(summary_raw: str, full_raw: str) -> dict[str, Any]:
    summary_map: dict[str, dict[str, Any]] = {}
    for line in input_lines(summary_raw):
        parsed = _parse_summary_line(line)
        if parsed:
            summary_map[parsed["key"]] = {
                "card": parsed["card"],
                "name": parsed["name"],
                "data": parsed["data"],
            }

    full_lines = input_lines(full_raw)
    total = len(full_lines)
    blocks: list[str] = []
    merged: list[dict[str, Any]] = []
    warnings: list[str] = []
    matched_keys: set[str] = set()

    for index, line in enumerate(full_lines):
        full = _parse_full_row_line(line)
        if not full:
            warnings.append(f"Skipped invalid full row: {line[:40]}…")
            continue
        issuer = summary_map.get(full["key"])
        contact = dict(full["contact"])
        if contact.get("name", "") == "" and issuer:
            contact["name"] = issuer.get("name", "")
        data = issuer["data"] if issuer else {"error": "No issuer line matched."}
        if issuer:
            matched_keys.add(full["key"])
        else:
            warnings.append(f"No issuer line matched for {full['key']}")
        blocks.append(format_card_block(index + 1, total, full["card"], contact, data))
        merged.append(
            {
                "index": index + 1,
                "line": line,
                "card": full["card"],
                "contact": contact,
                "data": data,
            }
        )

    for key in summary_map:
        if key not in matched_keys:
            warnings.append(f"No full detail row matched for {key}")

    return {
        "blocks": blocks,
        "combined": "\n".join(blocks),
        "html": format_all_results_html(merged),
        "html_preview": format_results_preview_fragment(merged),
        "warnings": warnings,
    }


def format_all_results_blocks(results: list[dict[str, Any]]) -> str:
    total = len(results)
    return "\n".join(
        format_card_block(r["index"], total, r["card"], r["contact"], r["data"]) for r in results
    )


_INDEX_HTML = '<!DOCTYPE html>\n<html lang="en">\n  <head>\n    <meta charset="utf-8" />\n    <meta name="viewport" content="width=device-width, initial-scale=1" />\n    <title>BIN Card Lookup</title>\n    <link rel="stylesheet" href="/styles.css" />\n  </head>\n  <body>\n    <div class="wrap">\n      <header>\n        <p class="label">BIN card lookup</p>\n        <h1>One line per record — card, name, and issuer details</h1>\n        <p class="lead">\n          Paste up to 3,000 rows. Python on the server fetches BIN data from namso.live and returns\n          a table, plain text, and downloadable HTML.\n        </p>\n      </header>\n\n      <div class="grid two">\n        <section class="card">\n          <div class="card-head">\n            <h2>Input</h2>\n            <p>Pipe-separated full row per line.</p>\n          </div>\n          <div class="card-body">\n            <textarea id="input" aria-label="Card rows"></textarea>\n            <div class="row">\n              <button type="button" class="primary" id="runBtn">Run BIN lookup</button>\n              <button type="button" class="secondary" id="clearBtn">Clear</button>\n            </div>\n          </div>\n        </section>\n\n        <section class="card">\n          <div class="card-head">\n            <h2>Progress</h2>\n            <p>Parallel BIN lookups (max 25 workers).</p>\n          </div>\n          <div class="card-body">\n            <div id="progressSection" hidden>\n              <div class="stats" id="progressText">Waiting…</div>\n              <div class="progress-bar"><div id="progressFill"></div></div>\n            </div>\n            <p id="progressIdle" class="stats">Paste rows and click Run.</p>\n            <div id="errorBox" class="alert" hidden></div>\n            <div class="row" style="margin-top: 16px">\n              <button type="button" class="secondary" id="downloadTxt" disabled>\n                Download results.txt\n              </button>\n              <button type="button" class="secondary" id="downloadHtml" disabled>\n                Download results.html\n              </button>\n            </div>\n          </div>\n        </section>\n      </div>\n\n      <section class="card" style="margin-top: 20px">\n        <div class="card-head">\n          <h2>Results</h2>\n          <p># · Card · Name · scheme · type · brand · bank · country · status</p>\n        </div>\n        <div class="card-body">\n          <p id="resultsEmpty" class="stats">No results yet.</p>\n          <div id="resultsTable" hidden style="overflow-x: auto">\n            <table>\n              <thead>\n                <tr>\n                  <th>#</th>\n                  <th>Card</th>\n                  <th>Name</th>\n                  <th>Scheme</th>\n                  <th>Type</th>\n                  <th>Brand</th>\n                  <th>Bank</th>\n                  <th>Country</th>\n                  <th>Status</th>\n                </tr>\n              </thead>\n              <tbody id="resultsBody"></tbody>\n            </table>\n          </div>\n        </div>\n      </section>\n\n      <section class="card" style="margin-top: 20px">\n        <div class="card-head">\n          <h2>HTML preview</h2>\n          <p>Same layout as the downloaded <code>results.html</code> file.</p>\n        </div>\n        <div class="card-body">\n          <div id="htmlPreview" class="html-preview"></div>\n        </div>\n      </section>\n\n      <section class="card" style="margin-top: 20px">\n        <div class="card-head">\n          <h2>Combine</h2>\n          <p>Merge issuer summary with full detail rows into one export.</p>\n        </div>\n        <div class="card-body">\n          <label class="stats" for="issuerSummary">Issuer results (tab-separated)</label>\n          <textarea id="issuerSummary" style="min-height: 100px; margin-top: 6px"></textarea>\n          <label class="stats" for="fullDetailRows" style="display: block; margin-top: 12px"\n            >Full detail rows (pipe-separated)</label\n          >\n          <textarea id="fullDetailRows" style="min-height: 100px; margin-top: 6px"></textarea>\n          <div class="row">\n            <button type="button" class="secondary" id="combineBtn">Combine rows</button>\n            <button type="button" class="secondary" id="copyCombined">Copy plain text</button>\n          </div>\n          <ul id="combineWarnings" class="stats" style="margin-top: 8px"></ul>\n          <textarea\n            id="combinedOutput"\n            readonly\n            style="min-height: 160px; margin-top: 12px"\n            placeholder="Combined output appears here"\n          ></textarea>\n        </div>\n      </section>\n\n      <footer class="note">\n        Deploy on Railway with Python 3.11+. Root directory: this folder. Start command is in\n        Procfile.\n      </footer>\n    </div>\n    <script src="/app.js"></script>\n  </body>\n</html>\n'
_APP_JS = 'const ROW_PLACEHOLDER =\n  "5343480605798163|01/31|998|Judi Bradley|2218 wessinger Rd|Chapin|SC|29036|8036067391|email@example.com";\n\nconst ISSUER_PLACEHOLDER =\n  "5343480605798163|01/31|998\\tJudi Bradley\\tMASTERCARD\\tPREPAID\\tCANADA\\tBANK OF MONTREAL\\tCANADA";\n\nconst RESULT_FIELDS = [\n  "Card Scheme",\n  "Card Type",\n  "Brand",\n  "Issuing Bank",\n  "Country",\n];\n\nlet results = [];\nlet htmlDocument = "";\nlet htmlPreview = "";\nlet combinedOutput = "";\n\nfunction $(id) {\n  return document.getElementById(id);\n}\n\nfunction setRunning(running) {\n  $("runBtn").disabled = running;\n  $("clearBtn").disabled = running;\n  $("input").disabled = running;\n}\n\nfunction formatSummaryLine(row) {\n  if (row.data.error) {\n    return `${row.card}\\t${row.contact.name || ""}\\t${row.data.error}`;\n  }\n  const d = row.data;\n  return [\n    row.card,\n    row.contact.name || "",\n    d["Card Scheme"] || "",\n    d["Card Type"] || "",\n    d.Brand || "",\n    d["Issuing Bank"] || "",\n    d.Country || "",\n  ].join("\\t");\n}\n\nfunction formatAllBlocks(rows) {\n  return rows\n    .map((r) => {\n      const lines = [\n        "=".repeat(60),\n        `Card ${r.index} of ${rows.length}`,\n        r.card,\n        `BIN: ${r.card.split("|")[0].replace(/\\D/g, "").slice(0, 6)}`,\n        "=".repeat(60),\n      ];\n      if (r.data.error) {\n        lines.push(r.data.error);\n      } else {\n        for (const f of RESULT_FIELDS) {\n          lines.push(f, r.data[f] || "", "");\n        }\n        if (r.data.ISO) lines.push(r.data.ISO, "");\n      }\n      for (const [label, key] of [\n        ["Name", "name"],\n        ["Address", "address"],\n        ["City", "city"],\n        ["State", "state"],\n        ["ZIP", "zip"],\n        ["Phone", "phone"],\n        ["Email", "email"],\n      ]) {\n        lines.push(label, r.contact[key] || "", "");\n      }\n      lines.push("Type", "", "");\n      return lines.join("\\n");\n    })\n    .join("\\n");\n}\n\nfunction renderTable(rows) {\n  const tbody = $("resultsBody");\n  tbody.innerHTML = "";\n  if (!rows.length) {\n    $("resultsEmpty").hidden = false;\n    $("resultsTable").hidden = true;\n    return;\n  }\n  $("resultsEmpty").hidden = true;\n  $("resultsTable").hidden = false;\n  for (const row of rows) {\n    const tr = document.createElement("tr");\n    const cells = [\n      String(row.index),\n      row.card,\n      row.contact.name || "",\n      ...RESULT_FIELDS.map((f) => (row.data.error ? "—" : row.data[f] || "")),\n      row.data.error || "OK",\n    ];\n    tr.innerHTML = cells\n      .map((c, i) => {\n        const cls = i === 1 ? \' class="mono"\' : "";\n        return `<td${cls}>${escapeHtml(c)}</td>`;\n      })\n      .join("");\n    tbody.appendChild(tr);\n  }\n}\n\nfunction escapeHtml(s) {\n  return String(s)\n    .replace(/&/g, "&amp;")\n    .replace(/</g, "&lt;")\n    .replace(/>/g, "&gt;")\n    .replace(/"/g, "&quot;");\n}\n\nasync function runLookup() {\n  const raw = $("input").value;\n  if (!raw.trim()) return;\n\n  setRunning(true);\n  $("errorBox").hidden = true;\n  $("progressSection").hidden = false;\n  $("progressFill").style.width = "0%";\n  $("progressText").textContent = "Starting…";\n  results = [];\n  renderTable([]);\n  $("downloadTxt").disabled = true;\n  $("downloadHtml").disabled = true;\n\n  try {\n    const response = await fetch("/api/lookup", {\n      method: "POST",\n      headers: { "Content-Type": "application/json" },\n      body: JSON.stringify({ raw }),\n    });\n    if (!response.ok) {\n      const err = await response.json().catch(() => ({}));\n      throw new Error(err.error || "Request failed.");\n    }\n    const reader = response.body.getReader();\n    const decoder = new TextDecoder();\n    let buffer = "";\n\n    while (true) {\n      const { done, value } = await reader.read();\n      if (done) break;\n      buffer += decoder.decode(value, { stream: true });\n      const parts = buffer.split("\\n\\n");\n      buffer = parts.pop() || "";\n      for (const part of parts) {\n        const line = part.trim();\n        if (!line.startsWith("data:")) continue;\n        const event = JSON.parse(line.slice(5).trim());\n        if (event.type === "start") {\n          $("progressText").textContent = `${event.totalCards} row(s) · ${event.uniqueBins} BIN lookup(s)`;\n        } else if (event.type === "progress") {\n          const pct = event.total ? Math.round((event.done / event.total) * 100) : 0;\n          $("progressFill").style.width = `${pct}%`;\n          const retryHint =\n            event.done < event.total && event.done > 0\n              ? " (retrying throttled BINs — still working)"\n              : "";\n          $("progressText").textContent = `Done: ${event.done} / ${event.total}${retryHint}`;\n        } else if (event.type === "complete") {\n          results = event.results;\n          renderTable(results);\n          $("issuerSummary").value = results.map(formatSummaryLine).join("\\n");\n          $("fullDetailRows").value = raw;\n          combinedOutput = formatAllBlocks(results);\n          $("combinedOutput").value = combinedOutput;\n          await refreshHtmlFromResults(results);\n          $("downloadTxt").disabled = false;\n          $("downloadHtml").disabled = !htmlDocument;\n        } else if (event.type === "error") {\n          throw new Error(event.message);\n        }\n      }\n    }\n  } catch (err) {\n    $("errorBox").textContent = err.message || "Lookup failed.";\n    $("errorBox").hidden = false;\n  } finally {\n    setRunning(false);\n  }\n}\n\nasync function refreshHtmlFromResults(rows) {\n  const res = await fetch("/api/combine", {\n    method: "POST",\n    headers: { "Content-Type": "application/json" },\n    body: JSON.stringify({\n      issuerSummary: rows.map(formatSummaryLine).join("\\n"),\n      fullDetailRows: $("input").value,\n    }),\n  });\n  if (!res.ok) return;\n  const data = await res.json();\n  htmlDocument = data.html || "";\n  htmlPreview = data.html_preview || "";\n  $("htmlPreview").innerHTML = htmlPreview;\n}\n\nasync function runCombine() {\n  const issuerSummary = $("issuerSummary").value;\n  const fullDetailRows = $("fullDetailRows").value;\n  if (!issuerSummary.trim() || !fullDetailRows.trim()) return;\n  const res = await fetch("/api/combine", {\n    method: "POST",\n    headers: { "Content-Type": "application/json" },\n    body: JSON.stringify({ issuerSummary, fullDetailRows }),\n  });\n  const data = await res.json();\n  if (!res.ok) {\n    $("combineWarnings").innerHTML = `<li>${escapeHtml(data.error || "Combine failed")}</li>`;\n    return;\n  }\n  combinedOutput = data.combined || "";\n  htmlDocument = data.html || "";\n  htmlPreview = data.html_preview || "";\n  $("combinedOutput").value = combinedOutput;\n  $("htmlPreview").innerHTML = htmlPreview;\n  $("downloadHtml").disabled = !htmlDocument;\n  const ul = $("combineWarnings");\n  ul.innerHTML = (data.warnings || []).map((w) => `<li>${escapeHtml(w)}</li>`).join("");\n}\n\nfunction downloadText(filename, text) {\n  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });\n  const url = URL.createObjectURL(blob);\n  const a = document.createElement("a");\n  a.href = url;\n  a.download = filename;\n  a.click();\n  URL.revokeObjectURL(url);\n}\n\nfunction clearAll() {\n  $("input").value = "";\n  $("issuerSummary").value = "";\n  $("fullDetailRows").value = "";\n  $("combinedOutput").value = "";\n  $("htmlPreview").innerHTML = "";\n  results = [];\n  htmlDocument = "";\n  renderTable([]);\n  $("errorBox").hidden = true;\n  $("progressSection").hidden = true;\n}\n\n$("input").placeholder = ROW_PLACEHOLDER;\n$("issuerSummary").placeholder = ISSUER_PLACEHOLDER;\n$("fullDetailRows").placeholder = ROW_PLACEHOLDER;\n\n$("runBtn").addEventListener("click", runLookup);\n$("clearBtn").addEventListener("click", clearAll);\n$("combineBtn").addEventListener("click", runCombine);\n$("downloadTxt").addEventListener("click", () => {\n  if (combinedOutput) downloadText("results.txt", combinedOutput);\n});\n$("downloadHtml").addEventListener("click", () => {\n  if (htmlDocument) downloadText("results.html", htmlDocument);\n});\n$("copyCombined").addEventListener("click", async () => {\n  if (combinedOutput) await navigator.clipboard.writeText(combinedOutput);\n});\n'
_STYLES_CSS = ':root {\n  color-scheme: light dark;\n  --bg: #09090b;\n  --surface: #18181b;\n  --border: #3f3f46;\n  --text: #fafafa;\n  --muted: #a1a1aa;\n  --accent: #10b981;\n  --danger: #f87171;\n  --radius: 12px;\n  font-family: ui-sans-serif, system-ui, sans-serif;\n}\n\n* {\n  box-sizing: border-box;\n}\n\nbody {\n  margin: 0;\n  background: var(--bg);\n  color: var(--text);\n  line-height: 1.5;\n}\n\n.wrap {\n  max-width: 1100px;\n  margin: 0 auto;\n  padding: 24px 16px 48px;\n}\n\nheader {\n  margin-bottom: 24px;\n}\n\nheader p.label {\n  margin: 0 0 4px;\n  font-size: 0.875rem;\n  color: var(--accent);\n  font-weight: 600;\n}\n\nh1 {\n  margin: 0 0 8px;\n  font-size: 1.75rem;\n  font-weight: 650;\n}\n\n.lead {\n  margin: 0;\n  color: var(--muted);\n  max-width: 42rem;\n}\n\n.grid {\n  display: grid;\n  gap: 20px;\n}\n\n@media (min-width: 900px) {\n  .grid.two {\n    grid-template-columns: 1fr 320px;\n    align-items: start;\n  }\n}\n\n.card {\n  background: var(--surface);\n  border: 1px solid var(--border);\n  border-radius: var(--radius);\n  overflow: hidden;\n}\n\n.card-head {\n  padding: 16px 20px;\n  border-bottom: 1px solid var(--border);\n}\n\n.card-head h2 {\n  margin: 0 0 4px;\n  font-size: 1rem;\n}\n\n.card-head p {\n  margin: 0;\n  font-size: 0.85rem;\n  color: var(--muted);\n}\n\n.card-body {\n  padding: 16px 20px 20px;\n}\n\ntextarea {\n  width: 100%;\n  min-height: 220px;\n  padding: 12px;\n  border-radius: 8px;\n  border: 1px solid var(--border);\n  background: #0c0c0e;\n  color: var(--text);\n  font-family: ui-monospace, monospace;\n  font-size: 0.8rem;\n  resize: vertical;\n}\n\ntextarea:disabled {\n  opacity: 0.6;\n}\n\n.row {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 8px;\n  margin-top: 12px;\n}\n\nbutton {\n  border: none;\n  border-radius: 8px;\n  padding: 10px 16px;\n  font-size: 0.9rem;\n  font-weight: 600;\n  cursor: pointer;\n}\n\nbutton.primary {\n  background: var(--accent);\n  color: #052e16;\n}\n\nbutton.secondary {\n  background: transparent;\n  color: var(--text);\n  border: 1px solid var(--border);\n}\n\nbutton:disabled {\n  opacity: 0.5;\n  cursor: not-allowed;\n}\n\n.progress-bar {\n  height: 8px;\n  background: #27272a;\n  border-radius: 999px;\n  overflow: hidden;\n  margin-top: 8px;\n}\n\n.progress-bar > div {\n  height: 100%;\n  background: var(--accent);\n  width: 0%;\n  transition: width 0.2s ease;\n}\n\n.stats {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 8px;\n  font-size: 0.85rem;\n  color: var(--muted);\n}\n\n.badge {\n  display: inline-block;\n  padding: 2px 8px;\n  border-radius: 999px;\n  background: #27272a;\n  font-size: 0.75rem;\n}\n\n.alert {\n  margin-top: 12px;\n  padding: 10px 12px;\n  border-radius: 8px;\n  background: rgba(248, 113, 113, 0.12);\n  color: var(--danger);\n  font-size: 0.85rem;\n}\n\ntable {\n  width: 100%;\n  border-collapse: collapse;\n  font-size: 0.8rem;\n}\n\nth,\ntd {\n  text-align: left;\n  padding: 8px 10px;\n  border-bottom: 1px solid var(--border);\n  vertical-align: top;\n}\n\nth {\n  color: var(--muted);\n  font-weight: 600;\n}\n\ntd.mono {\n  font-family: ui-monospace, monospace;\n  white-space: nowrap;\n}\n\n.html-preview {\n  border: 1px solid var(--border);\n  border-radius: 8px;\n  padding: 12px;\n  background: #f4f4f5;\n  color: #18181b;\n  max-height: 360px;\n  overflow: auto;\n}\n\nfooter.note {\n  margin-top: 32px;\n  font-size: 0.8rem;\n  color: var(--muted);\n}\n'

app = Flask(__name__)


@app.get("/")
def index_page() -> Response:
    return Response(_INDEX_HTML, mimetype="text/html; charset=utf-8")


@app.get("/app.js")
def app_js_route() -> Response:
    return Response(_APP_JS, mimetype="application/javascript; charset=utf-8")


@app.get("/styles.css")
def styles_css_route() -> Response:
    return Response(_STYLES_CSS, mimetype="text/css; charset=utf-8")


def _result_row(entry_index: int, entry, cache: dict[str, dict[str, str]]) -> dict[str, Any]:
    b = bin_from_card(entry.card)
    data = cache.get(b) or {"error": "BIN not in cache."}
    return {
        "index": entry_index,
        "line": entry.line,
        "card": entry.card,
        "contact": entry.contact,
        "data": data,
    }


def _emit_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _stream_lookup(raw: str) -> Generator[str, None, None]:
    events: queue.Queue[tuple[str, Any]] = queue.Queue()

    def worker() -> None:
        try:
            entries = parse_card_entries_from_input(raw)
            bins = unique_bins_from_entries(entries)
            events.put(
                (
                    "event",
                    {
                        "type": "start",
                        "totalCards": len(entries),
                        "uniqueBins": len(bins),
                    },
                )
            )

            def on_progress(done: int, total: int) -> None:
                events.put(("event", {"type": "progress", "done": done, "total": total}))

            cache = lookup_bins_with_progress(bins, on_progress)
            results = [_result_row(i + 1, entry, cache) for i, entry in enumerate(entries)]
            events.put(("event", {"type": "complete", "results": results}))
        except Exception as exc:
            events.put(("event", {"type": "error", "message": str(exc)}))
        finally:
            events.put(("done", None))

    threading.Thread(target=worker, daemon=True).start()

    while True:
        kind, payload = events.get()
        if kind == "done":
            break
        yield _emit_sse(payload)


@app.post("/api/lookup")
def api_lookup() -> Response:
    body = request.get_json(silent=True) or {}
    raw = str(body.get("raw") or "")
    if not raw.strip():
        return jsonify({"error": "Paste at least one card line."}), 400

    return Response(
        _stream_lookup(raw),
        mimetype="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/lookup-sync")
def api_lookup_sync() -> Response:
    body = request.get_json(silent=True) or {}
    raw = str(body.get("raw") or "")
    if not raw.strip():
        return jsonify({"error": "Paste at least one card line."}), 400
    try:
        entries = parse_card_entries_from_input(raw)
        bins = unique_bins_from_entries(entries)
        cache = lookup_bins_with_progress(bins)
        results = [_result_row(i + 1, entry, cache) for i, entry in enumerate(entries)]
        return jsonify(
            {
                "totalCards": len(entries),
                "uniqueBins": len(bins),
                "results": results,
                "text": format_all_results_blocks(results),
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/combine")
def api_combine() -> Response:
    body = request.get_json(silent=True) or {}
    summary = str(body.get("issuerSummary") or "")
    full = str(body.get("fullDetailRows") or "")
    if not summary.strip() or not full.strip():
        return jsonify({"error": "Paste both issuer summary and full detail rows."}), 400
    try:
        return jsonify(combine_issuer_and_full_rows(summary, full))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "43123"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
