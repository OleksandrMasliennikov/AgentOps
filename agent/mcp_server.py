import os
import sys
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

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
            return f.read()
    except UnicodeDecodeError:
        return f"ПОМИЛКА: '{path}' не є текстовим файлом у кодуванні UTF-8."
    except OSError as e:
        return f"ПОМИЛКА при читанні '{path}': {e}"


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
