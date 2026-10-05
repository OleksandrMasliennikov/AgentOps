"""Запускає кілька сценаріїв агента; кожен — окремий trace у Phoenix."""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIOS = {
    "find_py": "Find all .py files in the current directory, read the first file found, and report how many lines it contains",
    "read_requirements": "Read the file requirements.txt and name the first dependency listed",
    "list_root": "List the contents of the current directory and say how many entries there are",
    "missing_path": "Read the file does_not_exist.txt and report what it contains",
    "list_docs": "List the directory docs and tell me which subdirectories it has",
    "read_compose": "Read docker-compose.yml and tell me which image is used",
}
tag = str(int(time.time()))
for name, task in SCENARIOS.items():
    print(f"=== {name} ===", flush=True)
    env = {**os.environ, "TASK": task, "SCRIPT_NAME": name, "THREAD_ID": f"{name}_{tag}",
           "LLM_TIMEOUT": "600", "RECURSION_LIMIT": "12"}
    subprocess.run([sys.executable, "-u", os.path.join(ROOT, "agent", "agent.py")], cwd=ROOT, env=env)
