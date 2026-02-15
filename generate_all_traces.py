#!/usr/bin/env python3
"""Generate multiple RLM traces with different questions"""

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
                {"CONTEXT": self.context, "CONTEXT_LINES": self.lines, "print": print},
            )
            sys.stdout = old
        except Exception as e:
            return f"ERROR: {e}"
        return out.getvalue() or "[No output]"


def generate_trace(question, context_lines, output_file, prompt_suffix=""):
    """Generate a single trace"""

    client = NanoGPTClient()
    repl = REPLEnvironment(context_lines)

    trace = {"question": question, "iterations": [], "final_answer": ""}

    system_prompt = """You are an RLM. Write Python code to analyze CONTEXT_LINES.
When you have answer, say FINAL_ANSWER: <answer>"""

    user_prompt = f"""Question: {question}

Search CONTEXT_LINES for relevant code. {prompt_suffix}"""

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
                {"iteration": i + 1, "type": "final", "output": resp[:300]}
            )
            break

        # Extract and execute code
        code = None
        for tag in ["```python", "```", "<invoke", "]~b]"]:
            if tag in resp:
                start = resp.find(tag) + len(tag)
                end = (
                    resp.find("</invoke>", start)
                    if "</invoke>" in resp
                    else resp.find("```", start)
                )
                if end > start:
                    code = resp[start:end].strip()
                    break

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
                {"role": "user", "content": f"Output: {out[:500]}. Now FINAL_ANSWER:"}
            )

    if not trace["final_answer"]:
        trace["final_answer"] = "[Exploration complete but no final answer]"

    with open(f"example_traces/{output_file}", "w") as f:
        json.dump(trace, f, indent=2)

    print(f"Saved: {output_file}")


def main():
    # Load fair.c
    with open("linux/kernel/sched/fair.c") as f:
        context = f.read()

    lines = context.split("\n")

    # Generate 5 traces
    traces = [
        (
            "calc_delta_fair_trick",
            "What arithmetic trick in calc_delta_fair() avoids division? Cite lines.",
            "\n".join(lines[195:350]),
            "calc_delta_fair_rlm_trace.json",
        ),
        (
            "vruntime",
            "What is vruntime in CFS? Cite the code.",
            "\n".join(lines[0:100]),
            "vruntime_rlm_trace.json",
        ),
        (
            "sched_entity",
            "What is struct sched_entity? Find its definition.",
            "\n".join(lines[0:200]),
            "sched_entity_rlm_trace.json",
        ),
        (
            "update_load_set",
            "What does update_load_set do? Find and explain.",
            "\n".join(lines[13600:13750]),
            "update_load_set_rlm_trace.json",
        ),
        (
            "scale_load_down",
            "What does scale_load_down do? Find and explain.",
            "\n".join(lines[100:200]),
            "scale_load_rlm_trace.json",
        ),
    ]

    for name, question, context, filename in traces:
        print(f"\nGenerating: {name}")
        generate_trace(question, context, filename)


if __name__ == "__main__":
    main()
