"""Streaming agent traces into SQLite so a human can watch four agents at once.

The OpenAI Agents SDK emits traces and spans to its own dashboard. That is fine
for debugging one run, and useless for an operator watching a floor: you cannot
see, at a glance, that Cathie is mid-web-search while Ray is placing an order.
So a ``TracingProcessor`` is registered that mirrors every span into the ``logs``
table, and the dashboard tails it.

The one trick worth understanding is attribution. The processor is handed a span,
which knows its trace id but not which trader produced it. So the trader's name is
encoded *into* the trace id at creation time:

    trace_warren0k3f9a2b...     ->  "warren"

``make_trace_id`` writes ``trace_<name>0<random>`` and ``_owner`` reads back
everything before the ``0``. It is a small hack, and it is the kind of thing worth
being able to explain: the constraint is that trace ids must be 32 characters
after the prefix and are the only field that survives from the caller down to the
processor.
"""

from __future__ import annotations

import secrets
import string

from agents import Span, Trace, TracingProcessor

from trading_floor.core.database import write_log

ALPHANUM = string.ascii_lowercase + string.digits
ID_LENGTH = 32  # the SDK requires exactly this many characters after "trace_"
SEPARATOR = "0"  # not in the trader names, so it cannot appear inside one


def make_trace_id(tag: str) -> str:
    """A trace id of the form ``trace_<tag>0<random>``, 32 chars after the prefix."""
    tagged = tag + SEPARATOR
    if len(tagged) > ID_LENGTH:
        raise ValueError(f"Trace tag {tag!r} is too long to encode in a trace id.")
    suffix = "".join(secrets.choice(ALPHANUM) for _ in range(ID_LENGTH - len(tagged)))
    return f"trace_{tagged}{suffix}"


def _owner(trace_or_span: Trace | Span) -> str | None:
    """The trader name encoded in a trace id, or None for a trace we did not tag."""
    body = trace_or_span.trace_id.split("_", 1)[-1]
    return body.split(SEPARATOR)[0] if SEPARATOR in body else None


def _describe(span: Span, verb: str) -> tuple[str, str]:
    """A span's (type, human-readable line) for the log."""
    data = span.span_data
    kind = data.type if data else "span"
    parts = [verb]
    if data:
        parts += [
            str(value)
            for value in (getattr(data, "type", None), getattr(data, "name", None), getattr(data, "server", None))
            if value
        ]
    if span.error:
        parts.append(str(span.error))
    return kind, " ".join(parts)


class SQLiteLogTracer(TracingProcessor):
    """Mirror every trace and span for a tagged trader into the ``logs`` table."""

    def on_trace_start(self, trace: Trace) -> None:
        if name := _owner(trace):
            write_log(name, "trace", f"Started: {trace.name}")

    def on_trace_end(self, trace: Trace) -> None:
        if name := _owner(trace):
            write_log(name, "trace", f"Ended: {trace.name}")

    def on_span_start(self, span: Span) -> None:
        if name := _owner(span):
            write_log(name, *_describe(span, "Started"))

    def on_span_end(self, span: Span) -> None:
        if name := _owner(span):
            write_log(name, *_describe(span, "Ended"))

    def force_flush(self) -> None:
        """Nothing is buffered: every span is written synchronously."""

    def shutdown(self) -> None:
        """Nothing to release: connections are per-write and already closed."""
