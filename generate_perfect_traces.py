#!/usr/bin/env python3
"""Generate perfect RLM traces with citations"""

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

Your job:
1. First, write Python code to search CONTEXT_LINES for relevant code
2. Execute the code and see the output
3. Write more code to explore further if needed
4. Finally, provide your answer with citations

IMPORTANT:
- Use for loops: for i, line in enumerate(CONTEXT_LINES): if 'keyword' in line: print(f"Line {{i}}: {{line}}")
- When citing, include: "{file_name}" and line numbers
- ALWAYS provide FINAL_ANSWER: at the end with your complete answer"""

    user_prompt = f"""Question: {question}

Write Python code to search CONTEXT_LINES for the answer. Explore the code, then provide FINAL_ANSWER: with citations."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for i in range(6):
        resp = client.chat(messages)

        # Check for final answer FIRST
        if "FINAL_ANSWER:" in resp:
            answer = resp.split("FINAL_ANSWER:")[-1].strip()
            trace["final_answer"] = answer
            trace["iterations"].append(
                {"iteration": i + 1, "type": "final", "response": resp[:600]}
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

        # If no ```python, look for actual Python code
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
                    "type": "code_execution",
                    "code": code[:300],
                    "output": out[:800],
                }
            )
            messages.append({"role": "assistant", "content": resp})
            messages.append(
                {
                    "role": "user",
                    "content": f"Code output:\n{out[:800]}\n\nContinue exploring or provide FINAL_ANSWER: with citations to {file_name} and line numbers.",
                }
            )
        else:
            # No code extracted, continue conversation
            messages.append({"role": "assistant", "content": resp})
            messages.append(
                {
                    "role": "user",
                    "content": "Please write Python code to search CONTEXT_LINES. Use for loops with enumerate().",
                }
            )

    if not trace["final_answer"]:
        trace["final_answer"] = "[No answer found]"

    with open(f"example_traces/{output_file}", "w") as f:
        json.dump(trace, f, indent=2)

    has_citation = (
        file_name in trace["final_answer"] and "Line" in trace["final_answer"]
    )
    print(
        f"Saved: {output_file} | Iterations: {len(trace['iterations'])} | Has citation: {has_citation}"
    )


def main():
    with open("linux/kernel/sched/fair.c") as f:
        context = f.read()

    lines = context.split("\n")

    # Questions to re-run (need perfect traces)
    traces = [
        (
            "calc_delta_trick",
            "What arithmetic trick in calc_delta_fair() avoids division? Explain WMULT_SHIFT and reciprocal multiplication.",
            "\n".join(lines[245:295]),
            "calc_delta_trick.json",
        ),
        (
            "vruntime_cfs",
            "What is vruntime in CFS scheduler? How is it calculated?",
            "\n".join(lines[1200:1260]),
            "vruntime_cfs.json",
        ),
        (
            "sched_slice",
            "How is sched_slice calculated? What factors affect it?",
            "\n".join(lines[700:760]),
            "sched_slice.json",
        ),
        (
            "update_curr",
            "What does update_curr() do in CFS? How does it update vruntime?",
            "\n".join(lines[1200:1280]),
            "update_curr.json",
        ),
        (
            "min_vruntime",
            "What does min_vruntime function do? Find its implementation.",
            "\n".join(lines[850:920]),
            "min_vruntime.json",
        ),
        (
            "entity_weight",
            "How does CFS use entity weights? What is the relationship with nice values?",
            "\n".join(lines[35:65]),
            "entity_weight.json",
        ),
        (
            "scale_load",
            "What does scale_load_down do? Explain its purpose.",
            "\n".join(lines[130:180]),
            "scale_load.json",
        ),
    ]

    for name, question, context, filename in traces:
        print(f"\nGenerating: {name}")
        generate_trace(question, context, filename)


if __name__ == "__main__":
    main()
