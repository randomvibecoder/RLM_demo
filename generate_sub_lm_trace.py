#!/usr/bin/env python3
"""Generate RLM trace with explicit sub-LM demonstration"""

import os
import json
from pathlib import Path
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

        for attempt in range(3):
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


def main():
    # Load fair.c
    with open("linux/kernel/sched/fair.c") as f:
        context = f.read()

    lines = context.split("\n")

    question = """Explain the __calc_delta function - how does it use WMULT_SHIFT and reciprocal multiplication to avoid division?"""

    root_client = NanoGPTClient(model="minimax/minimax-m2.5")
    sub_client = NanoGPTClient(model="minimax/minimax-m2.5")

    trace = {
        "question": question,
        "root_model": "minimax/minimax-m2.5",
        "sub_model": "minimax/minimax-m2.5",
        "steps": [],
        "sub_lm_calls": [],
        "final_answer": "",
    }

    # === STEP 1: ROOT LM analyzes and identifies chunk ===
    print("Step 1: ROOT_LM analyzing...")
    root_prompt = f"""You are analyzing kernel/sched/fair.c

Question: {question}

The code has {len(lines)} lines. Identify which lines contain __calc_delta and explain the arithmetic trick.
Just provide your analysis now."""

    root_response = root_client.chat(
        [
            {
                "role": "system",
                "content": "You are an expert in Linux kernel scheduling.",
            },
            {"role": "user", "content": root_prompt},
        ]
    )

    trace["steps"].append(
        {
            "step": 1,
            "actor": "ROOT_LM",
            "action": "Analyzing context and identifying relevant code section",
            "prompt": root_prompt,
            "response": root_response[:800],
        }
    )

    # === SUB LM: Detailed analysis of __calc_delta (lines 245-285) ===
    print("Step 2: SUB_LM analyzing specific chunk...")
    chunk_start, chunk_end = 245, 285
    chunk_content = "\n".join(lines[chunk_start:chunk_end])

    sub_prompt = f"""You are a SUB-LM doing detailed analysis of a specific code chunk.

Question: {question}

Code from kernel/sched/fair.c lines {chunk_start}-{chunk_end}:
```
{chunk_content}
```

Explain in detail how this code avoids division using WMULT_SHIFT and reciprocal multiplication. Cite specific lines."""

    sub_response = sub_client.chat(
        [
            {
                "role": "system",
                "content": "You are a code analysis expert providing detailed technical explanation.",
            },
            {"role": "user", "content": sub_prompt},
        ]
    )

    trace["sub_lm_calls"].append(
        {
            "call_id": 1,
            "actor": "SUB_LM",
            "chunk_lines": f"{chunk_start}-{chunk_end}",
            "question": question,
            "prompt": sub_prompt,
            "response": sub_response,
        }
    )

    # === STEP 3: ROOT LM synthesizes final answer ===
    print("Step 3: ROOT_LM synthesizing final answer...")
    synthesis_prompt = f"""Based on the detailed SUB-LM analysis:

{sub_response[:1500]}

Provide a final answer to: {question}

Include file name and specific line numbers."""

    final_response = root_client.chat(
        [
            {
                "role": "system",
                "content": "Synthesize the analysis into a clear final answer.",
            },
            {"role": "user", "content": synthesis_prompt},
        ]
    )

    trace["steps"].append(
        {
            "step": 2,
            "actor": "ROOT_LM",
            "action": "Synthesizing final answer from sub-LM analysis",
            "prompt": synthesis_prompt,
            "response": final_response,
        }
    )

    trace["final_answer"] = final_response

    # Save trace
    with open("example_traces/sub_lm_trace.json", "w") as f:
        json.dump(trace, f, indent=2)

    print(f"\nSaved: example_traces/sub_lm_trace.json")
    print(f"Sub-LM calls: {len(trace['sub_lm_calls'])}")
    print(f"\nFinal answer preview:\n{trace['final_answer'][:500]}...")


if __name__ == "__main__":
    main()
