#!/usr/bin/env python3
"""Generate good traces - direct approach with better prompts"""

import os
import json
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
    """Run trace - direct answer with context"""

    client = NanoGPTClient()

    prompt = f"""You are analyzing Linux kernel code.

Context from kernel/sched/fair.c:
```
{context}
```

Question: {question}

IMPORTANT: 
- Answer based ONLY on the context above
- Cite specific line numbers from the context
- Format: "kernel/sched/fair.c line X" or "Line X"

FINAL_ANSWER:"""

    messages = [
        {
            "role": "system",
            "content": "You are a Linux kernel expert. Always cite line numbers.",
        },
        {"role": "user", "content": prompt},
    ]

    resp = client.chat(messages)

    answer = (
        resp.split("FINAL_ANSWER:")[-1].strip()
        if "FINAL_ANSWER:" in resp
        else resp.strip()
    )

    trace = {
        "question": question,
        "file": "kernel/sched/fair.c",
        "iterations": [{"iteration": 1, "type": "direct", "response": resp[:800]}],
        "final_answer": answer,
    }

    with open(f"example_traces/{filename}", "w") as f:
        json.dump(trace, f, indent=2)

    has_citation = "kernel/sched/fair.c" in answer and "line" in answer.lower()
    print(f"{filename}: citation={has_citation}")


def main():
    with open("linux/kernel/sched/fair.c") as f:
        full = f.read()
    lines = full.split("\n")

    traces = [
        (
            "calc_delta_trick_new",
            "What arithmetic trick in calc_delta_fair() avoids division? Explain WMULT_SHIFT.",
            "\n".join(lines[245:295]),
        ),
        (
            "vruntime_new",
            "What is vruntime in CFS? How is it calculated?",
            "\n".join(lines[1200:1280]),
        ),
        (
            "sched_slice_new",
            "How is sched_slice calculated?",
            "\n".join(lines[700:760]),
        ),
        ("update_curr_new", "What does update_curr() do?", "\n".join(lines[1200:1280])),
        (
            "min_vruntime_new",
            "What does min_vruntime function do?",
            "\n".join(lines[850:920]),
        ),
        (
            "entity_weight_new",
            "How does CFS use entity weights?",
            "\n".join(lines[35:65]),
        ),
        ("scale_load_new", "What does scale_load_down do?", "\n".join(lines[130:180])),
    ]

    for name, question, context in traces:
        print(f"Running: {name}")
        run_trace(question, context, f"{name}.json")


if __name__ == "__main__":
    main()
