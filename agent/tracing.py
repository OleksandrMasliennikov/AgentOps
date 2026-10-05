import os

from opentelemetry import trace

PROJECT = os.getenv("PHOENIX_PROJECT", "retention-agent")
ENDPOINT = os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006/v1/traces")


def setup():
    """Підключає Phoenix (OTLP) і автоінструментацію LangChain/LangGraph та MCP."""
    if os.getenv("TRACING", "1") == "0":  # CI/eval без Phoenix
        return trace.get_tracer("agentops")
    from phoenix.otel import register
    provider = register(project_name=PROJECT, endpoint=ENDPOINT, auto_instrument=True, batch=False)
    return provider.get_tracer("agentops")


def current_tracer():
    return trace.get_tracer("agentops")
