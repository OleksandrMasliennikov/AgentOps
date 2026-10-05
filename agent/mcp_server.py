import os
import sys
import urllib.request
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from guardrails_setup import check_injection, check_url

# MCP-сервер із транспортом stdio. Логи — лише в stderr (stdout зарезервований під протокол).
mcp = FastMCP("fs-tools-server")


@mcp.tool()
def read_file(
    path: Annotated[str, Field(description="Шлях до текстового файлу (абсолютний або відносний)")],
) -> str:
    """Зчитує текстовий файл (UTF-8) і повертає його вміст. Якщо файлу не існує — повертає повідомлення про помилку."""
    print(f"[MCP SERVER LOG] read_file(path={path!r})", file=sys.stderr)
    if not os.path.exists(path):
        return f"ПОМИЛКА: шлях '{path}' не існує."
    if not os.path.isfile(path):
        return f"ПОМИЛКА: '{path}' не є файлом."
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError:
        return f"ПОМИЛКА: '{path}' не є текстовим файлом у кодуванні UTF-8."
    except OSError as e:
        return f"ПОМИЛКА при читанні '{path}': {e}"
    reason = check_injection(text, source=f"read_file({path})")
    if reason:
        return f"ПОМИЛКА: вміст '{path}' заблоковано guardrails ({reason})."
    return text


@mcp.tool()
def fetch_url(
    url: Annotated[str, Field(description="https-URL сторінки з дозволеного домену, наприклад 'https://example.com'")],
) -> str:
    """Виконує HTTP GET і повертає перші 2000 символів відповіді. Дозволені лише домени з allowlist guardrails."""
    print(f"[MCP SERVER LOG] fetch_url(url={url!r})", file=sys.stderr)
    reason = check_url(url)
    if reason:
        return f"ПОМИЛКА: URL заблоковано guardrails ({reason})."
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            text = resp.read(20000).decode("utf-8", errors="replace")[:2000]
    except Exception as e:  # мережеві помилки повертаємо як текст, не виняток
        return f"ПОМИЛКА при запиті '{url}': {e}"
    reason = check_injection(text, source=f"fetch_url({url})")
    if reason:
        return f"ПОМИЛКА: відповідь '{url}' заблоковано guardrails ({reason})."
    return text


@mcp.tool()
def list_directory(
    path: Annotated[str, Field(description="Шлях до каталогу (абсолютний або відносний), наприклад '.'")],
) -> list[str]:
    """Повертає відсортований список файлів і підкаталогів у каталозі (підкаталоги мають суфікс '/'). Якщо шлях не існує — повертає список з одним повідомленням про помилку."""
    print(f"[MCP SERVER LOG] list_directory(path={path!r})", file=sys.stderr)
    if not os.path.exists(path):
        return [f"ПОМИЛКА: шлях '{path}' не існує."]
    if not os.path.isdir(path):
        return [f"ПОМИЛКА: '{path}' не є каталогом."]
    try:
        return sorted(
            name + "/" if os.path.isdir(os.path.join(path, name)) else name
            for name in os.listdir(path)
        )
    except OSError as e:
        return [f"ПОМИЛКА при читанні каталогу '{path}': {e}"]


if __name__ == "__main__":
    mcp.run(transport="stdio")
