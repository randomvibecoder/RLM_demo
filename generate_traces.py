#!/usr/bin/env python3
"""Generate example traces with specific questions about Linux kernel"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv()

# Questions about the Linux kernel codebase
QUESTIONS = [
    {
        "name": "calc_delta_fair_trick",
        "question": "What exact arithmetic trick is used in calc_delta_fair() to avoid division in the hot path?",
        "context_start": 195,
        "context_end": 350,
    },
    {
        "name": "vruntime_explanation",
        "question": "Explain what vruntime is in CFS and how it's calculated. Cite the relevant code.",
        "context_start": 0,
        "context_end": 100,
    },
    {
        "name": "entity_weight",
        "question": "How does the scheduler handle entity weights and what is the relationship between weight and load?",
        "context_start": 150,
        "context_end": 250,
    },
    {
        "name": "sched_slice",
        "question": "What is sched_slice and how is it calculated in the CFS scheduler?",
        "context_start": 700,
        "context_end": 800,
    },
    {
        "name": "update_curr_explanation",
        "question": "Explain what update_curr() does in the CFS scheduler and how it updates virtual runtime.",
        "context_start": 1200,
        "context_end": 1300,
    },
]


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

        for attempt in range(3):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=120,
                )
                if response.status_code != 200:
                    print(f"Error: {response.status_code}")
                    continue
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
        return ""


def main():
    client = NanoGPTClient()

    # Load fair.c
    with open("linux/kernel/sched/fair.c") as f:
        context = f.read()
    lines = context.split("\n")

    for q in QUESTIONS:
        print(f"\n{'=' * 60}")
        print(f"Generating trace: {q['name']}")
        print(f"{'=' * 60}")

        # Get relevant code section
        relevant_code = "\n".join(lines[q["context_start"] : q["context_end"]])

        # Build prompt with citation request
        prompt = f"""You are analyzing Linux kernel code from kernel/sched/fair.c

IMPORTANT: When citing code, you MUST include:
- The file name: kernel/sched/fair.c
- The line numbers (approximate, e.g., "around line X")

Code section:
```
{relevant_code}
```

Question: {q["question"]}

Please provide a detailed answer citing the relevant code with file and line numbers."""

        messages = [
            {
                "role": "system",
                "content": "You are a Linux kernel expert. Always cite file names and line numbers.",
            },
            {"role": "user", "content": prompt},
        ]

        answer = client.chat(messages)

        # Create trace file
        trace = {
            "question": q["question"],
            "answer": answer,
            "file": "kernel/sched/fair.c",
            "context_lines": f"{q['context_start']}-{q['context_end']}",
        }

        # Save as JSON
        with open(f"example_traces/{q['name']}.json", "w") as f:
            json.dump(trace, f, indent=2)

        print(f"Saved: example_traces/{q['name']}.json")
        print(f"\nAnswer preview: {answer[:300]}...")


if __name__ == "__main__":
    main()
