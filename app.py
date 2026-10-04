from __future__ import annotations

import json
import os
import queue
import threading
from typing import Any, Generator

from flask import Flask, Response, jsonify, request, send_from_directory

from bin_lookup.cards import (
    bin_from_card,
    format_card_block,
    parse_card_entries_from_input,
    unique_bins_from_entries,
)
from bin_lookup.combine import combine_issuer_and_full_rows, format_all_results_blocks
from bin_lookup.lookup import lookup_bins_with_progress

app = Flask(__name__, static_folder="static", static_url_path="")


@app.get("/")
def index() -> Response:
    return send_from_directory(app.static_folder, "index.html")


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
    """Non-streaming fallback for slow proxies."""
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
