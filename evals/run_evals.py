"""Eval regression suite: golden dataset -> агент -> метрики Accuracy/Relevance -> threshold gate (exit 1 при регресії).

Accuracy  — відповідь містить усі очікувані regex-и (expect_all).
Relevance — траєкторія релевантна: викликано всі expect_tools, лише з allowed_tools, не більше max_calls.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ACC_MIN = float(os.getenv("ACCURACY_THRESHOLD", "0.8"))
REL_MIN = float(os.getenv("RELEVANCE_THRESHOLD", "0.8"))
TIMEOUT = int(os.getenv("EVAL_CASE_TIMEOUT", "600"))
REPORT = os.path.join(HERE, "report.json")


def run_case(case: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        result_path = os.path.join(tmp, "result.json")
        env = {**os.environ, "TASK": case["question"], "RESULT_JSON": result_path, "TRACING": "0",
               "SCRIPT_NAME": f"eval_{case['id']}", "THREAD_ID": f"eval_{case['id']}_{os.getpid()}",
               "RECURSION_LIMIT": "12", "LLM_TIMEOUT": str(TIMEOUT)}
        env.pop("SYSTEM_PROMPT", None)  # оцінюється промпт із коду (його зміна — типова регресія)
        try:
            proc = subprocess.run([sys.executable, "-u", os.path.join(ROOT, "agent", "agent.py")],
                                  cwd=os.path.join(HERE, "fixtures"), env=env, capture_output=True,
                                  text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"error": "timeout", "answer": "", "tool_calls": []}
        if not os.path.exists(result_path):
            return {"error": f"agent exit {proc.returncode}: {proc.stderr[-300:]}", "answer": "", "tool_calls": []}
        return json.load(open(result_path, encoding="utf-8"))


def score(case: dict, res: dict) -> dict:
    answer = res["answer"]
    names = [c["name"] for c in res["tool_calls"]]
    accuracy = all(re.search(rx, answer, re.IGNORECASE) for rx in case["expect_all"])
    relevance = (all(t in names for t in case["expect_tools"])
                 and all(n in case["allowed_tools"] for n in names)
                 and len(names) <= case["max_calls"])
    return {"id": case["id"], "accuracy": int(accuracy), "relevance": int(relevance), "tools": names,
            "answer": answer[:300], "error": res.get("error", "")}


def main() -> int:
    cases = [json.loads(l) for l in open(os.path.join(HERE, "golden.jsonl"), encoding="utf-8") if l.strip()]
    rows = []
    for case in cases:
        row = score(case, run_case(case))
        rows.append(row)
        print(f"[{'PASS' if row['accuracy'] and row['relevance'] else 'FAIL'}] {row['id']}: "
              f"accuracy={row['accuracy']} relevance={row['relevance']} tools={row['tools']} "
              f"{row['error']}\n    answer: {row['answer']!r}", flush=True)
    acc = sum(r["accuracy"] for r in rows) / len(rows)
    rel = sum(r["relevance"] for r in rows) / len(rows)
    ok = acc >= ACC_MIN and rel >= REL_MIN
    json.dump({"accuracy": acc, "relevance": rel, "thresholds": {"accuracy": ACC_MIN, "relevance": REL_MIN},
               "passed": ok, "cases": rows}, open(REPORT, "w"), ensure_ascii=False, indent=2)

    md = [f"## Eval regression suite: {'✅ PASSED' if ok else '❌ FAILED (quality regression)'}",
          "", "| Metric | Score | Threshold |", "|---|---|---|",
          f"| Accuracy | {acc:.2f} | ≥ {ACC_MIN} |", f"| Relevance | {rel:.2f} | ≥ {REL_MIN} |", "",
          "| Case | Accuracy | Relevance | Tools |", "|---|---|---|---|"]
    md += [f"| {r['id']} | {'✅' if r['accuracy'] else '❌'} | {'✅' if r['relevance'] else '❌'} | {', '.join(r['tools']) or '—'} |"
           for r in rows]
    summary = "\n".join(md)
    print("\n" + summary)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(summary + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
