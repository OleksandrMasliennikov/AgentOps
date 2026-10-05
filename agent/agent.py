import asyncio
import os
import sys

import tracing
from mcp import StdioServerParameters, stdio_client, ClientSession
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "checkpoints.db")
THREAD_ID = os.getenv("THREAD_ID", "task22_thread")
# Пауза після кожного кроку агента, щоб встигнути натиснути Ctrl+C (за замовчуванням 0)
STEP_DELAY = float(os.getenv("STEP_DELAY", "0"))
MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/v1")
# AgentOps: жорсткі ліміти, щоб агент не зациклився і не завис на Ollama
RECURSION_LIMIT = int(os.getenv("RECURSION_LIMIT", "10"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))

TASK = os.getenv("TASK", "Find all .py files in the current directory, "
                 "read the first file found, and report how many lines it contains")
SCRIPT_NAME = os.getenv("SCRIPT_NAME", "default")

SYSTEM_PROMPT = ("You are a file assistant. Use the tools list_directory and read_file. "
                 "Call each tool only when needed and never repeat an identical call. "
                 "When you have read the file, finish with one sentence naming the file you read. "
                 "Do not count lines and do not retell the file content.")

server_params = StdioServerParameters(
    command=sys.executable,
    args=[os.path.join(HERE, "mcp_server.py")],
)


def tool_text(msg) -> str:
    content = msg.content
    if isinstance(content, list):  # MCP повертає список текстових блоків
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def print_verified(messages) -> None:
    """Детермінований підрахунок рядків у коді (не LLM): беремо результат останнього read_file зі стану."""
    paths = {tc["id"]: tc["args"].get("path") for m in messages for tc in getattr(m, "tool_calls", None) or []}
    reads = [m for m in messages if m.__class__.__name__ == "ToolMessage" and m.name == "read_file"]
    if not reads:
        print("[VERIFIED] read_file не викликався — рахувати нічого.")
        return
    last = reads[-1]
    text = tool_text(last)
    if text.startswith("ПОМИЛКА"):
        print(f"[VERIFIED] read_file повернув помилку: {text}")
        return
    print(f"[VERIFIED] {paths.get(last.tool_call_id)} contains {len(text.splitlines())} lines (підраховано кодом)")


def print_update(update: dict) -> None:
    for node, payload in update.items():
        for msg in payload.get("messages", []):
            role = msg.__class__.__name__.replace("Message", "")
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    print(f"[TOOL CALL] {tc['name']}({tc['args']})")
            elif role == "Tool":
                content = msg.content
                if isinstance(content, list):  # MCP повертає список текстових блоків
                    content = ", ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
                text = str(content)
                print(f"[TOOL RESULT] {msg.name}: {text[:200]}{'...' if len(text) > 200 else ''}")
            else:
                print(f"[{role}] {msg.content}")


async def main():
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            print(f"[SYSTEM] Інструменти MCP: {[t.name for t in tools]}", file=sys.stderr)

            print(f"[SYSTEM] model={MODEL} url={BASE_URL} temperature=0.0 "
                  f"timeout={LLM_TIMEOUT}s recursion_limit={RECURSION_LIMIT} thread_id={THREAD_ID}",
                  file=sys.stderr)
            llm = ChatOpenAI(
                model=MODEL,
                base_url=BASE_URL,
                api_key="ollama",
                temperature=0.0,
                timeout=LLM_TIMEOUT,
                max_retries=0,
            )

            # SQLite-чекпоінтер зберігає стан на диску, тож він переживає перезапуск процесу
            async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
                agent = create_react_agent(model=llm, tools=tools, checkpointer=checkpointer, prompt=SYSTEM_PROMPT)
                config = {"configurable": {"thread_id": THREAD_ID}, "recursion_limit": RECURSION_LIMIT}

                state = await agent.aget_state(config)
                if state.next:
                    print(f"[SYSTEM] thread_id='{THREAD_ID}': знайдено незавершений стан "
                          f"({len(state.values['messages'])} повідомлень, наступний вузол: {state.next}). "
                          "ВІДНОВЛЕННЯ без повторного запиту.")
                    stream_input = None
                elif state.values.get("messages"):
                    print(f"[SYSTEM] thread_id='{THREAD_ID}' уже завершено. Остання відповідь:")
                    print(state.values["messages"][-1].content)
                    print_verified(state.values["messages"])
                    print("Щоб почати заново: THREAD_ID=<інший> python agent.py")
                    return
                else:
                    print(f"[SYSTEM] thread_id='{THREAD_ID}': новий запуск.\n[USER] {TASK}")
                    stream_input = {"messages": [("user", TASK)]}

                async for update in agent.astream(stream_input, config, stream_mode="updates"):
                    print_update(update)
                    if STEP_DELAY:
                        await asyncio.sleep(STEP_DELAY)
                print_verified((await agent.aget_state(config)).values["messages"])


async def traced_main():
    tracer = tracing.setup()
    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("openinference.span.kind", "AGENT")
        span.set_attribute("script.name", SCRIPT_NAME)
        span.set_attribute("session.id", THREAD_ID)
        span.set_attribute("input.value", TASK)
        await main()
    tracing.trace.get_tracer_provider().force_flush()


if __name__ == "__main__":
    try:
        asyncio.run(traced_main())
    except GraphRecursionError:
        print(f"[SYSTEM] Перевищено recursion_limit={RECURSION_LIMIT}: агент зупинено.", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print(f"\n[SYSTEM] Перервано (Ctrl+C). Стан збережено в {DB_PATH}; "
              f"перезапустіть з тим самим THREAD_ID='{THREAD_ID}'.", file=sys.stderr)
        sys.exit(130)
