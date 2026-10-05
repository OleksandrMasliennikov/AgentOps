import os

from opentelemetry import trace
from phoenix.otel import register

PROJECT = os.getenv("PHOENIX_PROJECT", "retention-agent")
ENDPOINT = os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006/v1/traces")


def setup():
    """Підключає Phoenix (OTLP) і автоінструментацію LangChain/LangGraph та MCP."""
    provider = register(project_name=PROJECT, endpoint=ENDPOINT, auto_instrument=True, batch=False)
    return provider.get_tracer("agentops")


def current_tracer():
    return trace.get_tracer("agentops")
