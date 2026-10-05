"""Cost dashboard: $/run за скриптами й tool-ами та latency спанів (дані з Phoenix).

Ollama безкоштовна, тому використовується умовний тариф Claude Haiku 4.5.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from phoenix.client import Client

PRICE_IN, PRICE_OUT = 1.00 / 1e6, 5.00 / 1e6  # $/токен (Haiku 4.5)
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "lab1")
os.makedirs(OUT, exist_ok=True)

df = Client().spans.get_spans_dataframe(project_identifier=os.getenv("PHOENIX_PROJECT", "retention-agent"))
df["latency_s"] = (pd.to_datetime(df["end_time"]) - pd.to_datetime(df["start_time"])).dt.total_seconds()
df["tin"] = df["attributes.llm.token_count.prompt"].fillna(0)
df["tout"] = df["attributes.llm.token_count.completion"].fillna(0)
df["cost"] = df["tin"] * PRICE_IN + df["tout"] * PRICE_OUT

runs = df[df["name"] == "agent.run"].copy()
runs["script"] = runs["attributes.script"].apply(lambda v: v.get("name") if isinstance(v, dict) else v)
llm = df[df["span_kind"] == "LLM"]
run_cost = llm.groupby("context.trace_id")["cost"].sum().rename("cost_usd")
runs = runs.merge(run_cost, left_on="context.trace_id", right_index=True, how="left").fillna({"cost_usd": 0})
by_script = runs.groupby("script").agg(runs=("cost_usd", "size"), cost_per_run=("cost_usd", "mean"), latency_s=("latency_s", "mean"))

# вартість tool-а = вартість LLM-кроку, що його викликав; тут — середня latency та кількість викликів
tools = df[df["span_kind"] == "TOOL"].groupby("name").agg(calls=("latency_s", "size"), latency_s=("latency_s", "mean"))
spans = df[df["name"].isin(["agent.run", "ChatOpenAI", "list_directory", "read_file"])].groupby("name")["latency_s"].mean()

by_script.to_csv(f"{OUT}/cost_by_script.csv")
tools.to_csv(f"{OUT}/tools.csv")
print(f"Середня вартість run: ${runs['cost_usd'].mean():.6f} ({len(runs)} runs)")
print(by_script.round(6)); print(tools.round(3))

fig, ax = plt.subplots(1, 3, figsize=(17, 5))
by_script["cost_per_run"].plot.barh(ax=ax[0], color="#2a9d8f"); ax[0].set_title("$/run за скриптом (тариф Haiku 4.5)")
spans.sort_values().plot.barh(ax=ax[1], color="#e76f51"); ax[1].set_title("Середня latency спана, с")
tools["latency_s"].plot.barh(ax=ax[2], color="#264653"); ax[2].set_title("Latency tool-ів, с")
fig.suptitle(f"retention-agent: avg ${runs['cost_usd'].mean():.6f}/run, {len(runs)} runs")
fig.tight_layout(); fig.savefig(f"{OUT}/cost_dashboard.png", dpi=110)
