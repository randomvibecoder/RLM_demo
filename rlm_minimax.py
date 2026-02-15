#!/usr/bin/env python3
"""
Recursive Language Model (RLM) Implementation using NanoGPT API with minimax2.5

Based on the paper: "Recursive Language Models" by Zhang, Kraska, Khattab (2025)
https://arxiv.org/abs/2512.24601

This implementation features:
- Root LM (minimax2.5) that writes Python code to analyze context
- Sub LM (minimax2.5) called recursively by root to process chunks
- REPL environment that stores context and executes code
"""

import os
import sys
import json
import time
import traceback
from pathlib import Path
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()


class NanoGPTClient:
    """Client for NanoGPT API"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "minimax/minimax-m2.5",
    ):
        self.api_key = api_key or os.getenv("NANO_GPT_API_KEY")
        self.base_url = base_url or os.getenv(
            "NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1"
        )
        self.model = model

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        """Make a chat completion request"""
        import requests

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        print(f"DEBUG: Sending request to {self.base_url}/chat/completions")
        print(f"DEBUG: Model: {self.model}")
        print(
            f"DEBUG: API Key starts with: {self.api_key[:20] if self.api_key else 'None'}..."
        )

        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=120,
                )
                print(f"DEBUG: Response status: {response.status_code}")
                if response.status_code != 200:
                    print(f"DEBUG: Response body: {response.text[:500]}")
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)  # Wait before retry
                else:
                    raise

        return ""  # Should never reach here


class REPLEnvironment:
    """Python REPL environment that stores context and executes code"""

    def __init__(self, context: str):
        self.context = context
        self.context_lines = context.split("\n")
        self.globals = {
            "__name__": "__main__",
            "CONTEXT": context,
            "CONTEXT_LINES": self.context_lines,
            "len_CONTEXT": len(context),
            "len_CONTEXT_LINES": len(self.context_lines),
        }
        self.locals = {}
        self.outputs = []

    def execute(self, code: str) -> str:
        """Execute Python code and return output"""
        import io
        from contextlib import redirect_stdout, redirect_stderr

        self.outputs = []
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, self.globals, self.locals)

            stdout = stdout_capture.getvalue()
            stderr = stderr_capture.getvalue()

            result = stdout
            if stderr:
                result += "\n[STDERR]: " + stderr

            if not result.strip():
                result = "[Code executed successfully with no output]"

            return result
        except Exception as e:
            return f"[ERROR]: {type(e).__name__}: {str(e)}"

    def get_line(self, line_num: int) -> str:
        """Get a specific line from context"""
        if 0 <= line_num < len(self.context_lines):
            return self.context_lines[line_num]
        return ""

    def get_lines(self, start: int, end: int) -> str:
        """Get lines from start to end (inclusive)"""
        return "\n".join(self.context_lines[start:end])


class RLM:
    """
    Recursive Language Model implementation

    The root LM writes Python code to inspect the context and can recursively
    call sub-LMs on smaller chunks for deeper analysis.
    """

    def __init__(
        self,
        root_model: str = "minimax/minimax-m2.5",
        sub_model: str = "minimax/minimax-m2.5",
    ):
        self.root_client = NanoGPTClient(model=root_model)
        self.sub_client = NanoGPTClient(model=sub_model)

    def get_system_prompt(self) -> str:
        """Get the system prompt for the RLM"""
        return """You are analyzing Linux kernel source code. Your task is to find and explain the arithmetic trick in calc_delta_fair().

## How to interact with the context

Write Python code to search through the context. Available:
- CONTEXT: the full file as a string
- CONTEXT_LINES: list of lines (0-indexed)
- len_CONTEXT_LINES: number of lines

Example code to find calc_delta_fair:
```python
for i, line in enumerate(CONTEXT_LINES):
    if 'calc_delta_fair' in line:
        print(f"Line {i}: {line}")
```

Use standard print() statements to see results. When done, answer with:
FINAL_ANSWER: <your explanation>"""

    def get_root_prompt(self, context_metadata: Dict[str, Any], question: str) -> str:
        """Get the prompt for the root LM"""
        return f"""You are analyzing a Linux kernel source file (kernel/sched/fair.c) from the CFS (Completely Fair Scheduler).

## Context Metadata

- File: kernel/sched/fair.c
- Total lines: {context_metadata["num_lines"]}
- Total characters: {context_metadata["num_chars"]}

## Question

{question}

## Task

Find calc_delta_fair() in the context, understand how it avoids division using reciprocal multiplication (the WMULT_SHIFT technique), and explain the arithmetic trick.

Write Python code to search CONTEXT_LINES for calc_delta_fair and related functions.
When you understand the answer, say: FINAL_ANSWER: <your answer>"""

    def run(self, context: str, question: str, max_iterations: int = 10) -> str:
        """Run the RLM to answer a question about the context"""

        # Create REPL environment
        repl = REPLEnvironment(context)

        # Add sub_call function to globals
        def sub_call(question: str, chunk: str) -> str:
            """Call sub-LLM on a chunk of context"""
            messages = [
                {
                    "role": "system",
                    "content": "You are a sub-LLM analyzing a specific chunk of code. Provide detailed analysis of the chunk in relation to the question.",
                },
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nCode chunk:\n{chunk}",
                },
            ]
            return self.sub_client.chat(messages, temperature=0.3)

        repl.globals["sub_call"] = sub_call
        repl.globals["get_line"] = repl.get_line
        repl.globals["get_lines"] = repl.get_lines

        # Get context metadata
        context_metadata = {
            "num_lines": len(repl.context_lines),
            "num_chars": len(context),
        }

        # Initial message to root LM
        messages = [
            {"role": "system", "content": self.get_system_prompt()},
            {
                "role": "user",
                "content": self.get_root_prompt(context_metadata, question),
            },
        ]

        print("=" * 60)
        print("RLM Started")
        print("=" * 60)
        print(
            f"Context size: {context_metadata['num_lines']} lines, {context_metadata['num_chars']} chars"
        )
        print(f"Question: {question[:100]}...")
        print("=" * 60)

        iteration = 0
        final_answer = None

        while iteration < max_iterations:
            iteration += 1
            print(f"\n--- Iteration {iteration} ---")

            # Get response from root LM
            response = self.root_client.chat(messages)
            print(f"Root LM response (first 500 chars):\n{response[:500]}...")

            # Check if this is a final answer
            if "FINAL_ANSWER:" in response:
                final_answer = response.split("FINAL_ANSWER:")[-1].strip()
                print(f"\n*** FINAL ANSWER FOUND ***\n{final_answer}")
                break

            # Extract Python code from response
            code = self._extract_code(response)

            if not code:
                # No code found, show what we got and ask for clarification
                print(f"\nNo Python code extracted. Response preview:")
                # Show more of the response to debug
                preview = response[:500]
                print(repr(preview))  # Use repr to see exact format
                messages.append({"role": "assistant", "content": response})
                messages.append(
                    {
                        "role": "user",
                        "content": "Please write Python code to analyze the context. Use the REPL functions like get_line(), get_lines(), or search through CONTEXT_LINES.",
                    }
                )
                continue

            print(f"\nExecuting code:\n{code[:200]}...")

            # Execute code in REPL
            output = repl.execute(code)
            print(f"REPL output:\n{output[:500]}...")

            # Add exchange to messages
            messages.append({"role": "assistant", "content": response})
            messages.append(
                {
                    "role": "user",
                    "content": f"Code output:\n{output}\n\nContinue analyzing or provide your final answer with FINAL_ANSWER:",
                }
            )

        if final_answer is None:
            final_answer = "Could not determine final answer within iteration limit"

        return final_answer

    def _extract_code(self, response: str) -> Optional[str]:
        """Extract Python code from response"""

        # Handle special function calls like ~~~eval, ~~~run_python
        if "~~~" in response:
            import re

            # Match patterns like ~~~eval or ~~~run_python followed by code and closing ~~~
            patterns = [
                r"~~~eval\s*\n(.*?)~~~",
                r"~~~run_python\s*\n(.*?)~~~",
                r"~~~REPL\s*\n(.*?)~~~",
                r"~~~python_repl\s*\n(.*?)~~~",
                r"~~~python\s*\n(.*?)~~~",
                r"~~~\w+\n(.*?)~~~",
            ]

            for pattern in patterns:
                match = re.search(pattern, response, re.DOTALL)
                if match:
                    return match.group(1).strip()

            # Fallback: look for any code between ~~~ markers
            lines = response.split("\n")
            code_lines = []
            in_block = False

            for line in lines:
                stripped = line.strip()
                if stripped.startswith("~~~"):
                    # Start of a special block - skip the marker line
                    in_block = True
                    continue
                elif stripped == "~~~":
                    # End of block
                    in_block = False
                    continue
                elif in_block:
                    code_lines.append(line)

            if code_lines:
                return "\n".join(code_lines)

        # Handle XML-like tool format: <filepath>...</think>
        if "python_repl" in response or "eval" in response:
            import re

            # Match <think> for python_repl, eval, etc.
            patterns = [
                r"</minimax:tool_call>\s*\n(.*?)</minimax:tool_call>",
                r"]~b]\s*\n(.*?)</minimax:tool_call>",
            ]

            for pattern in patterns:
                match = re.search(pattern, response, re.DOTALL)
                if match:
                    code = match.group(1).strip()
                    # Check if it looks like Python code
                    if "for" in code or "print" in code or "CONTEXT" in code:
                        return code

        # Handle opencode tool format: <filepath>
        if "invoke name=" in response:
            import re

            # Match content between <filepath> and </invoke>
            pattern = r"</minimax:tool_call>(.*?)</minimax:tool_call>"
            match = re.search(pattern, response, re.DOTALL)
            if match:
                code = match.group(1).strip()
                # Check if it looks like Python code
                if (
                    "for" in code
                    or "print" in code
                    or "CONTEXT" in code
                    or "enumerate" in code
                ):
                    return code

        # Look for code blocks
        if "```python" in response:
            start = response.find("```python") + len("```python")
            end = response.find("```", start)
            if end != -1:
                return response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end != -1:
                return response[start:end].strip()

        # If no code block, check if the entire response looks like code
        lines = response.split("\n")
        code_starts = (
            " ",
            "\t",
            "#",
            "import",
            "def",
            "for",
            "if",
            "return",
            "print",
            "CONTEXT",
        )
        if lines and all(
            line.startswith(code_starts) for line in lines if line.strip()
        ):
            return response.strip()

        return None


def load_context_from_file(filepath: str) -> str:
    """Load context from a file"""
    with open(filepath, "r") as f:
        return f.read()


def format_context_as_rlm(context: str, filename: str) -> str:
    """Format context in RLM style"""
    return f"==={filename}===\n{context}\n==="


def main():
    # Load the fair.c file
    fair_c_path = Path("linux/kernel/sched/fair.c")

    if not fair_c_path.exists():
        print(f"Error: {fair_c_path} not found!")
        print("Please ensure the Linux kernel repository is cloned.")
        sys.exit(1)

    print(f"Loading context from {fair_c_path}...")
    context = load_context_from_file(str(fair_c_path))

    # Format for RLM
    formatted_context = format_context_as_rlm(context, "kernel/sched/fair.c")

    # The question
    question = """what exact arithmetic trick is used in the function calc_delta_fair() (or nearby in the CFS bandwidth/throttling logic) to efficiently compute the scaled runtime delta while avoiding division in the hot path, and how does the use of div64_u64 or reciprocal multiplication optimization appear in that calculation?"""

    # Create RLM
    rlm = RLM(root_model="minimax/minimax-m2.5", sub_model="minimax/minimax-m2.5")

    # Run RLM
    answer = rlm.run(formatted_context, question)

    print("\n" + "=" * 60)
    print("FINAL RESULT")
    print("=" * 60)
    print(answer)


if __name__ == "__main__":
    main()
