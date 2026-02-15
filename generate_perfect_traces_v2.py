#!/usr/bin/env python3
"""Generate perfect RLM traces with citations - v2"""

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


class REPLEnvironment:
    def __init__(self, context):
        self.context = context
        self.lines = context.split("\n")

    def execute(self, code):
        import io, sys

        out = io.StringIO()
        try:
            old = sys.stdout
            sys.stdout = out
            exec(
                code,
                {
                    "CONTEXT": self.context,
                    "CONTEXT_LINES": self.lines,
                    "print": print,
                    "len": len,
                    "range": range,
                    "enumerate": enumerate,
                },
            )
            sys.stdout = old
        except Exception as e:
            return f"ERROR: {e}"
        return out.getvalue() or "[No output]"


def extract_answer(response):
    """Extract FINAL_ANSWER from response"""
    # Try different patterns
    patterns = [
        r"FINAL_ANSWER:\s*(.+)",
        r"Final Answer:\s*(.+)",
        r"Answer:\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def generate_trace(
    question, context_lines, output_file, file_name="kernel/sched/fair.c"
):
    """Generate a trace with multiple iterations and citations"""

    client = NanoGPTClient()
    repl = REPLEnvironment(context_lines)

    trace = {
        "question": question,
        "file": file_name,
        "iterations": [],
        "final_answer": "",
    }

    system_prompt = f"""You are analyzing Linux kernel code from {file_name}.

IMPORTANT: After exploring the code, ALWAYS end with:
FINAL_ANSWER: <your answer with citations like "kernel/sched/fair.c line X">
"""

    user_prompt = f"""Question: {question}

Search CONTEXT_LINES to find the answer. Then provide FINAL_ANSWER: with file name and line numbers."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for i in range(6):
        resp = client.chat(messages)

        # Check for final answer
        answer = extract_answer(resp)
        if answer:
            trace["final_answer"] = answer
            trace["iterations"].append(
                {"iteration": i + 1, "type": "final", "response": resp[:800]}
            )
            break

        # Extract Python code
        code = None

        # Try ```python block
        if "```python" in resp:
            start = resp.find("```python") + 9
            end = resp.find("```", start)
            if end > start:
                code = resp[start:end].strip()

        # Look for Python keywords
        if not code:
            lines = resp.split("\n")
            code_lines = []
            for line in lines:
                stripped = line.strip()
                if any(
                    stripped.startswith(kw)
                    for kw in [
                        "for ",
                        "if ",
                        "print(",
                        "def ",
                        "#",
                        "while ",
                        "return ",
                        "enumerate",
                    ]
                ):
                    code_lines.append(line)
            if len(code_lines) >= 2:
                code = "\n".join(code_lines)

        if code:
            out = repl.execute(code)
            trace["iterations"].append(
                {
                    "iteration": i + 1,
                    "type": "code_execution",
                    "code": code[:300],
                    "output": out[:800],
                }
            )
            messages.append({"role": "assistant", "content": resp})
            messages.append(
                {
                    "role": "user",
                    "content": f"Code output:\n{out[:800]}\n\nNow provide FINAL_ANSWER: with citations to {file_name} and line numbers.",
                }
            )
        else:
            messages.append({"role": "assistant", "content": resp})
            messages.append(
                {
                    "role": "user",
                    "content": "Write Python code to search CONTEXT_LINES. Then FINAL_ANSWER:",
                }
            )

    if not trace["final_answer"]:
        trace["final_answer"] = "[No answer found]"

    with open(f"example_traces/{output_file}", "w") as f:
        json.dump(trace, f, indent=2)

    has_citation = file_name in trace["final_answer"] and (
        "line" in trace["final_answer"].lower() or "Line" in trace["final_answer"]
    )
    print(
        f"Saved: {output_file} | Iterations: {len(trace['iterations'])} | Citation: {has_citation}"
    )


def main():
    with open("linux/kernel/sched/fair.c") as f:
        context = f.read()

    lines = context.split("\n")

    # 7 questions to run
    traces = [
        (
            "calc_delta_trick",
            "What arithmetic trick in calc_delta_fair() avoids division? Explain WMULT_SHIFT.",
            "\n".join(lines[245:295]),
            "calc_delta_trick.json",
        ),
        (
            "vruntime_cfs",
            "What is vruntime in CFS? How is it calculated?",
            "\n".join(lines[1200:1260]),
            "vruntime_cfs.json",
        ),
        (
            "sched_slice",
            "How is sched_slice calculated?",
            "\n".join(lines[700:760]),
            "sched_slice.json",
        ),
        (
            "update_curr",
            "What does update_curr() do? How does it update vruntime?",
            "\n".join(lines[1200:1280]),
            "update_curr.json",
        ),
        (
            "min_vruntime",
            "What does min_vruntime function do?",
            "\n".join(lines[850:920]),
            "min_vruntime.json",
        ),
        (
            "entity_weight",
            "How does CFS use entity weights? Relationship with nice values?",
            "\n".join(lines[35:65]),
            "entity_weight.json",
        ),
        (
            "scale_load",
            "What does scale_load_down do?",
            "\n".join(lines[130:180]),
            "scale_load.json",
        ),
    ]

    for name, question, context, filename in traces:
        print(f"\nGenerating: {name}")
        generate_trace(question, context, filename)


if __name__ == "__main__":
    main()
