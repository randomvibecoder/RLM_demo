import os
import json
import re
import io
import contextlib
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

NANO_GPT_API_KEY = os.getenv("NANO_GPT_API_KEY")
NANO_GPT_BASE_URL = os.getenv("NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1")

ROOT_MODEL = "minimax/minimax-m2.5"
SUB_MODEL = "meta-llama/llama-4-maverick"

SYSTEM_PROMPT = """You are a Recursive Language Model (RLM). You have access to a Python REPL environment where the entire context is stored in a variable called `context`.

IMPORTANT: Write ONLY plain Python code in markdown code blocks. Do NOT use tool call formats.

Example format:
```python
# Analyze the context
print(context[:500])
lines = context.split('\\n')
print(f"Total lines: {len(lines)}")
```

To call a sub-LM, write code that calls `sub_call(prompt, chunk)` function - this is a real function that will execute and return the sub-LM's response.

Example:
```python
# Call sub-LM on first chunk
result = sub_call("What language is this?", context[:1000])
print(result)
```

After you've analyzed the context enough to answer the question, write your final answer in this format (as plain text, NOT in a code block):
FINAL_ANSWER: <your answer>

Otherwise, write Python code to analyze the context further."""

SUB_LM_SYSTEM_PROMPT = """You are a sub-LLM helping analyze a chunk of a larger context.
Analyze the provided chunk and answer the question as best as you can.
Just provide your answer - no need for extra explanation.
"""


def call_nano_gpt(prompt: str, model: str, system_prompt: Optional[str] = None) -> str:
    """Call nano-gpt API with a single prompt"""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return call_nano_gpt_messages(messages, model)


def call_nano_gpt_messages(messages: List[Dict[str, str]], model: str) -> str:
    """Call nano-gpt API with message history"""
    import requests

    headers = {
        "Authorization": f"Bearer {NANO_GPT_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {"model": model, "messages": messages, "max_tokens": 4096}

    response = requests.post(
        f"{NANO_GPT_BASE_URL}/chat/completions",
        headers=headers,
        json=payload,
        timeout=120,
    )

    if response.status_code != 200:
        raise Exception(f"API error: {response.status_code} - {response.text}")

    result = response.json()
    return result["choices"][0]["message"]["content"]


def parse_dangerous_code(code: str) -> bool:
    """Check if code contains dangerous operations"""
    dangerous_patterns = [
        r"import\s+os",
        r"import\s+subprocess",
        r"import\s+sys",
        r"from\s+os",
        r"from\s+subprocess",
        r"from\s+sys",
        r"os\.",
        r"subprocess\.",
        r"sys\.",
        r"eval\s*\(",
        r"exec\s*\(",
        r"__import__",
        r"open\s*\(",
        r"file\s*\(",
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, code):
            return True
    return False


def execute_code(code: str, context: str, sub_call_fn) -> str:
    """Execute code in a restricted environment"""
    if parse_dangerous_code(code):
        return (
            "ERROR: Code contains dangerous operations. Only string operations allowed."
        )

    local_vars = {"context": context, "re": __import__("re")}

    # Add sub_call function to namespace
    def sub_call(prompt: str, chunk: str) -> str:
        """Call sub-LM on a chunk"""
        return call_nano_gpt(
            f"{prompt}\n\nContext chunk:\n{chunk}", SUB_MODEL, SUB_LM_SYSTEM_PROMPT
        )

    local_vars["sub_call"] = sub_call

    # Add helper functions
    local_vars["len"] = len
    local_vars["str"] = str
    local_vars["list"] = list
    local_vars["dict"] = dict
    local_vars["int"] = int
    local_vars["print"] = print

    output = io.StringIO()

    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            exec(code, {"__builtins__": {}}, local_vars)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {str(e)}"

    result = output.getvalue()
    if not result:
        result = "Code executed successfully (no output)"
    return result


class RLM:
    def __init__(
        self,
        max_iterations: int = 10,
        root_model: str = ROOT_MODEL,
        sub_model: str = SUB_MODEL,
    ):
        self.max_iterations = max_iterations
        self.root_model = root_model
        self.sub_model = sub_model

    def ask(self, question: str, context: str) -> str:
        """Ask a question with the given context"""

        conversation = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""Question: {question}

Context length: {len(context)} characters

You are in a Python REPL. The entire context is stored in the `context` variable.
Write Python code to analyze the context and answer the question.

Available functions:
- `sub_call(prompt, chunk)` - Call sub-LM on a smaller chunk
- `re` - regex module for searching

After you have your answer, respond with:
FINAL_ANSWER: <your answer>

Otherwise, write Python code to analyze the context further.
Show your reasoning with print statements.""",
            },
        ]

        for iteration in range(self.max_iterations):
            # Get LLM response
            response = call_nano_gpt_messages(conversation, self.root_model)

            # Add assistant response to conversation
            conversation.append({"role": "assistant", "content": response})

            # Check for final answer
            final_match = re.search(r"FINAL_ANSWER:\s*(.+)", response, re.DOTALL)
            if final_match:
                return final_match.group(1).strip()

            # Extract code blocks
            code_blocks = re.findall(r"```python\n(.*?)```", response, re.DOTALL)
            if not code_blocks:
                # Try without python language specifier
                code_blocks = re.findall(r"```\n?(.*?)```", response, re.DOTALL)

            if not code_blocks:
                # No code found, treat response as final answer attempt
                conversation.append(
                    {
                        "role": "user",
                        "content": "Please provide your answer using FINAL_ANSWER format.",
                    }
                )
                continue

            # Execute each code block
            for code in code_blocks:
                result = execute_code(code, context, None)
                conversation.append(
                    {"role": "user", "content": f"Code output:\n{result}"}
                )

            print(f"Iteration {iteration + 1}: Executed code, checking for answer...")

        return "Max iterations reached without final answer"


def create_rlm() -> RLM:
    """Factory function to create RLM instance"""
    return RLM()
