#!/usr/bin/env python3
"""Generate perfect RLM traces - simple direct approach"""

import os
import json
import re
from dotenv import load_dotenv
import requests

load_dotenv()


class NanoGPTClient:
    def __init__(self, model: str = "minimax/minimax-m2.5"):
        self.api_key = os.getenv("NANO_GPT_API_KEY")
        self.base_url = os.getenv("NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1")
        self.model = model

    def chat(self, messages, temperature: float = 0.7) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4000,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(5):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=120,
                )
                if response.status_code != 200:
                    continue
                return response.json()["choices"][0]["message"]["content"]
            except:
                pass
        return ""


def run_trace(question, context, filename):
    """Run a single trace - simplified"""

    client = NanoGPTClient()

    trace = {
        "question": question,
        "file": "kernel/sched/fair.c",
        "iterations": [],
        "final_answer": "",
    }

    # First prompt with context
    prompt = f"""You are analyzing Linux kernel code from kernel/sched/fair.c.

Context from the file:
```
{context}
```

Question: {question}

Based on this context, provide your answer with citations. Include the file name and line numbers.

FINAL_ANSWER:"""

    messages = [
        {
            "role": "system",
            "content": "You are a Linux kernel expert. Always cite file names and line numbers.",
        },
        {"role": "user", "content": prompt},
    ]

    # Try multiple times to get good answer
    for i in range(3):
        resp = client.chat(messages)

        # Check for answer
        if "FINAL_ANSWER:" in resp or len(resp) > 100:
            answer = (
                resp.split("FINAL_ANSWER:")[-1].strip()
                if "FINAL_ANSWER:" in resp
                else resp.strip()
            )
            trace["final_answer"] = answer
            trace["iterations"].append(
                {"iteration": 1, "type": "direct", "response": resp[:1000]}
            )
            break
        messages.append({"role": "assistant", "content": resp})
        messages.append(
            {"role": "user", "content": "Please provide FINAL_ANSWER: with citations"}
        )

    if not trace["final_answer"]:
        trace["final_answer"] = "[No answer]"

    with open(f"example_traces/{filename}", "w") as f:
        json.dump(trace, f, indent=2)

    has_citation = "kernel/sched/fair.c" in trace["final_answer"] and (
        "line" in trace["final_answer"].lower() or "Line" in trace["final_answer"]
    )
    print(f"{filename}: citation={has_citation}")
    return trace


def main():
    with open("linux/kernel/sched/fair.c") as f:
        full_context = f.read()

    lines = full_context.split("\n")

    # Define questions with their context ranges
    traces = [
        (
            "calc_delta_trick",
            "What arithmetic trick in calc_delta_fair() avoids division? Explain WMULT_SHIFT and reciprocal multiplication.",
            "\n".join(lines[245:295]),
        ),
        (
            "vruntime_cfs",
            "What is vruntime in CFS? How is it calculated?",
            "\n".join(lines[1200:1280]),
        ),
        ("sched_slice", "How is sched_slice calculated?", "\n".join(lines[700:760])),
        ("update_curr", "What does update_curr() do?", "\n".join(lines[1200:1280])),
        (
            "min_vruntime",
            "What does min_vruntime function do?",
            "\n".join(lines[850:920]),
        ),
        ("entity_weight", "How does CFS use entity weights?", "\n".join(lines[35:65])),
        ("scale_load", "What does scale_load_down do?", "\n".join(lines[130:180])),
    ]

    for name, question, context in traces:
        print(f"Running: {name}")
        run_trace(question, context, f"{name}_trace.json")


if __name__ == "__main__":
    main()
