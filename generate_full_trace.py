#!/usr/bin/env python3
"""Full RLM with detailed iteration tracing - saves complete trace of each step"""

import os
import json
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
                    print(f"Error: {response.status_code}")
                    time.sleep(3)
                    continue
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                time.sleep(3)
        return ""


class REPLEnvironment:
    def __init__(self, context: str):
        self.context = context
        self.context_lines = context.split("\n")

    def execute(self, code: str) -> str:
        import io
        from contextlib import redirect_stdout

        output = io.StringIO()
        try:
            with redirect_stdout(output):
                exec(
                    code,
                    {
                        "CONTEXT": self.context,
                        "CONTEXT_LINES": self.context_lines,
                        "len_CONTEXT_LINES": len(self.context_lines),
                        "print": print,
                    },
                )
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {str(e)}"
        return output.getvalue() or "[No output]"


class RLMWithFullTrace:
    """Full RLM that saves detailed trace of each iteration"""

    def __init__(
        self,
        root_model: str = "minimax/minimax-m2.5",
        sub_model: str = "minimax/minimax-m2.5",
    ):
        self.root_client = NanoGPTClient(model=root_model)
        self.sub_client = NanoGPTClient(model=sub_model)

    def run(self, context: str, question: str, max_iterations: int = 5) -> dict:
        """Run RLM and return complete trace"""

        trace = {
            "question": question,
            "context_info": {
                "file": "kernel/sched/fair.c",
                "total_lines": len(context.split("\n")),
                "total_chars": len(context),
            },
            "iterations": [],
            "final_answer": "",
        }

        repl = REPLEnvironment(context)

        system_prompt = """You are a Recursive Language Model (RLM). Write Python code to analyze the context.

Available in REPL:
- CONTEXT: full file text
- CONTEXT_LINES: list of lines
- len_CONTEXT_LINES: number of lines

Write code using for loops and print statements. When you have the answer, say FINAL_ANSWER: <answer>"""

        user_prompt = f"""Question: {question}

The context is in CONTEXT and CONTEXT_LINES. Write Python code to find and analyze the relevant code.
Start by searching for 'calc_delta_fair' in CONTEXT_LINES."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for iteration in range(1, max_iterations + 1):
            print(f"\n=== Iteration {iteration} ===")

            # Get model response
            response = self.root_client.chat(messages)
            print(f"Model response: {response[:200]}...")

            # Check for final answer
            if "FINAL_ANSWER:" in response:
                trace["final_answer"] = response.split("FINAL_ANSWER:")[-1].strip()
                trace["iterations"].append(
                    {
                        "iteration": iteration,
                        "type": "final_answer",
                        "model_output": response,
                    }
                )
                break

            # Extract code from response
            code = self._extract_code(response)

            if code:
                print(f"Executing code: {code[:100]}...")
                output = repl.execute(code)
                print(f"Output: {output[:200]}...")

                # Record this iteration
                trace["iterations"].append(
                    {
                        "iteration": iteration,
                        "type": "code_execution",
                        "model_output": response,
                        "code_executed": code,
                        "code_output": output,
                    }
                )

                # Continue conversation
                messages.append({"role": "assistant", "content": response})
                messages.append(
                    {
                        "role": "user",
                        "content": f"Code output:\n{output}\n\nYou have explored enough. Now provide your FINAL_ANSWER:",
                    }
                )
            else:
                # No code, just continue
                trace["iterations"].append(
                    {
                        "iteration": iteration,
                        "type": "no_code",
                        "model_output": response,
                    }
                )
                messages.append({"role": "assistant", "content": response})
                messages.append(
                    {
                        "role": "user",
                        "content": "Please write Python code to analyze the context.",
                    }
                )

        if not trace["final_answer"]:
            trace["final_answer"] = "Could not determine answer"

        return trace

    def _extract_code(self, response: str) -> Optional[str]:
        # Try various code block formats
        patterns = [
            ("```python", 9, "```"),
            ("```", 3, "```"),
            ("<function_code>", 14, "</function_code>"),
            ('<invoke name="write">', 20, "</invoke>"),
            ("<invoke name='write'>", 20, "</invoke>"),
        ]

        for start_tag, start_skip, end_tag in patterns:
            if start_tag in response:
                start = response.find(start_tag) + start_skip
                end = response.find(end_tag, start)
                if end != -1:
                    code = response[start:end].strip()
                    if code and len(code) > 10:
                        return code

        # Last resort: look for lines starting with code-like patterns
        lines = response.split("\n")
        code_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(
                (
                    "for ",
                    "if ",
                    "print(",
                    "import ",
                    "def ",
                    "#",
                    "CONTEXT",
                    "while ",
                    "return ",
                )
            ):
                code_lines.append(line)

        if len(code_lines) >= 2:
            return "\n".join(code_lines)

        return None

        # Check for lines that look like code
        lines = response.split("\n")
        code_lines = []
        for line in lines:
            if line.strip().startswith(
                ("for ", "if ", "print(", "import ", "def ", "#", "CONTEXT")
            ):
                code_lines.append(line)

        if len(code_lines) > 2:
            return "\n".join(code_lines)
        return None


def main():
    # Load fair.c
    with open("linux/kernel/sched/fair.c") as f:
        context = f.read()

    question = """What exact arithmetic trick is used in calc_delta_fair() to avoid division in the hot path? Include file name and line numbers in your answer.
    
IMPORTANT: After exploring the code, provide your final answer with FINAL_ANSWER:"""

    print("Running RLM with full tracing...")
    rlm = RLMWithFullTrace()
    trace = rlm.run(context, question)

    # Save trace
    with open("example_traces/calc_delta_fair_full_trace.json", "w") as f:
        json.dump(trace, f, indent=2)

    print(f"\n\nSaved trace with {len(trace['iterations'])} iterations")
    print("\n" + "=" * 60)
    print("FINAL ANSWER:")
    print("=" * 60)
    print(trace["final_answer"][:500])


if __name__ == "__main__":
    main()
