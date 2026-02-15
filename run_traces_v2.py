#!/usr/bin/env python3
"""Generate perfect RLM traces with code exploration"""

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
        return out.getvalue()


def run_trace_v2(question, context, filename, file_name="kernel/sched/fair.c"):
    """Run trace with forced code exploration"""

    client = NanoGPTClient()
    repl = REPLEnvironment(context)

    trace = {
        "question": question,
        "file": file_name,
        "iterations": [],
        "final_answer": "",
    }

    # STRONG system prompt - force code exploration FIRST
    system_prompt = f"""You are an RLM (Recursive Language Model). Your job is to EXPLORE the code first, then answer.

CRITICAL INSTRUCTIONS:
1. You MUST write Python code to search CONTEXT_LINES before answering
2. Use for loops: for i, line in enumerate(CONTEXT_LINES): if 'keyword' in line: print(f"Line {{i}}: {{line}}")
3. After seeing code output, THEN provide your answer
4. Your response must contain Python code in ```python blocks
5. After code execution, provide FINAL_ANSWER: with citations

DO NOT give direct answers - you must explore first!"""

    user_prompt = f"""Context is in CONTEXT_LINES (list of strings).

Question: {question}

STEP 1: Write Python code to search CONTEXT_LINES for relevant code
STEP 2: Execute the code
STEP 3: Then provide FINAL_ANSWER: with citations to {file_name}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for i in range(5):
        resp = client.chat(messages)

        # Check for final answer
        if "FINAL_ANSWER:" in resp:
            answer = resp.split("FINAL_ANSWER:")[-1].strip()
            trace["final_answer"] = answer
            trace["iterations"].append(
                {"iteration": i + 1, "type": "final", "response": resp[:600]}
            )
            break

        # Extract Python code
        code = None
        if "```python" in resp:
            start = resp.find("```python") + 9
            end = resp.find("```", start)
            if end > start:
                code = resp[start:end].strip()

        if code:
            out = repl.execute(code)
            trace["iterations"].append(
                {
                    "iteration": i + 1,
                    "type": "code_execution",
                    "code": code[:300],
                    "output": out[:600],
                }
            )
            messages.append({"role": "assistant", "content": resp})
            messages.append(
                {
                    "role": "user",
                    "content": f"Code output:\n{out[:600]}\n\nNow write more code or provide FINAL_ANSWER: with citations",
                }
            )
        else:
            messages.append({"role": "assistant", "content": resp})
            messages.append(
                {
                    "role": "user",
                    "content": "You MUST write Python code first. Use: for i, line in enumerate(CONTEXT_LINES): if 'keyword' in line: print(...)",
                }
            )

    if not trace["final_answer"]:
        trace["final_answer"] = "[No answer]"

    with open(f"example_traces/{filename}", "w") as f:
        json.dump(trace, f, indent=2)

    has_citation = (
        file_name in trace["final_answer"] and "line" in trace["final_answer"].lower()
    )
    print(f"{filename}: iters={len(trace['iterations'])}, citation={has_citation}")


def main():
    with open("linux/kernel/sched/fair.c") as f:
        full_context = f.read()

    lines = full_context.split("\n")

    traces = [
        (
            "calc_delta_trick_v2",
            "What arithmetic trick in calc_delta_fair() avoids division? Explain WMULT_SHIFT and reciprocal multiplication.",
            "\n".join(lines[245:295]),
        ),
        (
            "vruntime_cfs_v2",
            "What is vruntime in CFS? How is it calculated?",
            "\n".join(lines[1200:1280]),
        ),
        ("sched_slice_v2", "How is sched_slice calculated?", "\n".join(lines[700:760])),
        ("update_curr_v2", "What does update_curr() do?", "\n".join(lines[1200:1280])),
        (
            "min_vruntime_v2",
            "What does min_vruntime function do?",
            "\n".join(lines[850:920]),
        ),
        (
            "entity_weight_v2",
            "How does CFS use entity weights?",
            "\n".join(lines[35:65]),
        ),
        ("scale_load_v2", "What does scale_load_down do?", "\n".join(lines[130:180])),
    ]

    for name, question, context in traces:
        print(f"Running: {name}")
        run_trace_v2(question, context, f"{name}.json")


if __name__ == "__main__":
    main()
