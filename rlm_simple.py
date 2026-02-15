#!/usr/bin/env python3
"""
Simplified RLM for Linux kernel code analysis
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()


class NanoGPTClient:
    def __init__(self, model: str = "minimax/minimax-m2.5"):
        self.api_key = os.getenv("NANO_GPT_API_KEY")
        self.base_url = os.getenv("NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1")
        self.model = model

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        import requests

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4000,
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
                    print(f"Error: {response.status_code} - {response.text[:200]}")
                    time.sleep(5)
                    continue
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                time.sleep(5)
        return ""


def main():
    # Load fair.c
    fair_c_path = Path("linux/kernel/sched/fair.c")
    if not fair_c_path.exists():
        print("Error: fair.c not found!")
        sys.exit(1)

    with open(fair_c_path) as f:
        context = f.read()

    # Get key sections for calc_delta_fair
    lines = context.split("\n")
    key_functions = []
    for i, line in enumerate(lines):
        if (
            "calc_delta_fair" in line
            or "__calc_delta" in line
            or "mul_u64_u32_shr" in line
            or "WMULT_SHIFT" in line
        ):
            key_functions.append((i, line))

    # Extract relevant code section (lines 200-350)
    relevant_code = "\n".join(lines[195:350])

    print(f"Context loaded: {len(lines)} lines")
    print(f"Found {len(key_functions)} relevant lines")
    print("\nRelevant code section:")
    print(relevant_code[:2000])
    print("...")

    # Ask the question directly with the relevant code
    client = NanoGPTClient()

    question = """In the Linux CFS scheduler (kernel/sched/fair.c), what exact arithmetic trick is used in calc_delta_fair() to efficiently compute the scaled runtime delta while avoiding division in the hot path? Explain how __calc_delta uses reciprocal multiplication with WMULT_SHIFT and mul_u64_u32_shr to avoid expensive division operations."""

    messages = [
        {
            "role": "system",
            "content": "You are a kernel expert. Analyze the code and explain the arithmetic optimization.",
        },
        {
            "role": "user",
            "content": f"Code from kernel/sched/fair.c:\n\n{relevant_code}\n\nQuestion: {question}",
        },
    ]

    print("\n" + "=" * 60)
    print("Getting answer from model...")
    print("=" * 60)

    answer = client.chat(messages)

    print("\n" + "=" * 60)
    print("FINAL ANSWER:")
    print("=" * 60)
    print(answer)


if __name__ == "__main__":
    main()
