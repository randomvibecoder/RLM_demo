#!/usr/bin/env python3
"""Generate 5 new RLM traces with improved prompts"""

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
                },
            )
            sys.stdout = old
        except Exception as e:
            return f"ERROR: {e}"
        return out.getvalue() or "[No output]"


def generate_trace(question, context_lines, output_file):
    """Generate a single trace with improved prompting"""

    client = NanoGPTClient()
    repl = REPLEnvironment(context_lines)

    trace = {"question": question, "iterations": [], "final_answer": ""}

    system_prompt = """You are analyzing Linux kernel source code. 

IMPORTANT instructions:
1. First write and execute Python code to search CONTEXT_LINES for relevant code
2. Use for loops: for i, line in enumerate(CONTEXT_LINES): if 'keyword' in line: print(f"Line {i}: {line}")
3. After seeing the code output, provide your answer
4. When you have the answer, say FINAL_ANSWER: <your answer with citations>"""

    user_prompt = f"""Question: {question}

Context (CONTEXT_LINES) is provided. Search it to find the answer. Write Python code first."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for i in range(5):
        resp = client.chat(messages)

        # Check for final answer
        if "FINAL_ANSWER:" in resp:
            trace["final_answer"] = resp.split("FINAL_ANSWER:")[-1].strip()
            trace["iterations"].append(
                {"iteration": i + 1, "type": "final", "output": resp[:400]}
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

        # If no ```python, look for Python keywords
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
                        "import ",
                        "def ",
                        "#",
                        "CONTEXT",
                        "while ",
                        "return ",
                        "in ",
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
                    "type": "code",
                    "code": code[:200],
                    "output": out[:500],
                }
            )
            messages.append({"role": "assistant", "content": resp})
            messages.append(
                {
                    "role": "user",
                    "content": f"Code output:\n{out[:500]}\n\nNow provide FINAL_ANSWER:",
                }
            )

    if not trace["final_answer"]:
        trace["final_answer"] = "[No answer found]"

    with open(f"example_traces/{output_file}", "w") as f:
        json.dump(trace, f, indent=2)

    print(f"Saved: {output_file} - Answer: {trace['final_answer'][:80]}...")


def main():
    with open("linux/kernel/sched/fair.c") as f:
        context = f.read()

    lines = context.split("\n")

    # 5 new questions
    traces = [
        (
            "__calc_delta_analysis",
            "Explain __calc_delta function in detail - how does it use WMULT_SHIFT?",
            "\n".join(lines[245:290]),
            "calc_delta_detail_trace.json",
        ),
        (
            "entity_cfs_rq",
            "What is entity_cfs_rq and how does it update vruntime?",
            "\n".join(lines[1200:1250]),
            "entity_update_trace.json",
        ),
        (
            "min_vruntime",
            "What does min_vruntime function do? Find and explain it.",
            "\n".join(lines[850:920]),
            "min_vruntime_trace.json",
        ),
        (
            "niced_weight",
            "What is the relationship between nice value and weight in CFS?",
            "\n".join(lines[195:260]),
            "nice_weight_trace.json",
        ),
        (
            "sched_slice_calc",
            "How is sched_slice calculated? What factors affect it?",
            "\n".join(lines[700:760]),
            "sched_slice_trace.json",
        ),
    ]

    for name, question, context, filename in traces:
        print(f"\nGenerating: {name}")
        generate_trace(question, context, filename)


if __name__ == "__main__":
    main()
