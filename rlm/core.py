import os
import json
import re
import io
import contextlib
import logging
import datetime
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

NANO_GPT_API_KEY = os.getenv("NANO_GPT_API_KEY")
NANO_GPT_BASE_URL = os.getenv("NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1")

ROOT_MODEL = "minimax/minimax-m2.5"
SUB_MODEL = "meta-llama/llama-4-maverick"

SYSTEM_PROMPT = """You are tasked with answering a query with associated context. You can access, transform, and analyze this context interactively in a REPL environment that can recursively query sub-LLMs, which you are strongly encouraged to use as much as possible. You will be queried iteratively until you provide a final answer.

The REPL environment is initialized with:
1. A 'context' variable that contains the context as a string
2. A 'llm_query' function that allows you to query an LLM (that can handle around 500K chars) inside your REPL environment.
3. The ability to use 'print()' statements to view the output of your REPL code and continue your reasoning.

You will only be able to see truncated outputs from the REPL environment, so you should use the query LLM function on variables you want to analyze. You will find this function especially useful when you have to analyze the semantics of the context. Use these variables as buffers to build up your final answer.

Make sure to explicitly look through the entire context in REPL before answering your query. An example strategy is to first look at the context and figure out a chunking strategy, then break up the context into smart chunks, and query an LLM per chunk with a particular question and save the answers to a buffer, then query an LLM with all the buffers to produce your final answer.

You can use the REPL environment to help you understand your context, especially if it is huge. Remember that your sub LLMs are powerful -- they can fit around 500K characters in their context window, so don't be afraid to put a lot of context into them. For example, a viable strategy is to feed 10 documents per sub-LLM query. Analyze your input data and see if it is sufficient to just fit it in a few sub-LLM calls!

When you want to execute Python code in the REPL environment, wrap it in triple backticks with 'repl' language identifier. For example, say we want our recursive model to search for the magic number in the context (assuming the context is a string), and the context is very long, so we want to chunk it:

```repl
# Look at the first 1000 chars
print(context[:1000])
```

IMPORTANT: 
1. Use print() statements to see intermediate outputs
2. Use FINAL_VAR(variable_name) to return a variable you have created in the REPL environment as your final output

Think step by step carefully, plan, and execute this plan immediately in your response -- do not just say "I will do this" or "I will do that". Output to the REPL environment and recursive LLMs as much as possible. Remember to explicitly answer the original query in your final answer.
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

    logger.info(f"Calling {model} API...")

    response = requests.post(
        f"{NANO_GPT_BASE_URL}/chat/completions",
        headers=headers,
        json=payload,
        timeout=120,
    )

    if response.status_code != 200:
        logger.error(f"API error: {response.status_code} - {response.text}")
        raise Exception(f"API error: {response.status_code} - {response.text}")

    result = response.json()
    content = result["choices"][0]["message"]["content"]
    logger.info(f"API response received, length: {len(content)} chars")
    return content


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
            logger.warning(f"Dangerous code pattern detected: {pattern}")
            return True
    return False


def execute_code(code: str, context: str, llm_query_fn) -> str:
    """Execute code in a restricted environment"""
    logger.info(f"Executing code: {code[:200]}...")

    if parse_dangerous_code(code):
        logger.warning("Blocked dangerous code execution")
        return (
            "ERROR: Code contains dangerous operations. Only string operations allowed."
        )

    # Safe builtins
    safe_builtins = {
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "map": map,
        "filter": filter,
        "sorted": sorted,
        "reversed": reversed,
        "min": min,
        "max": max,
        "sum": sum,
        "abs": abs,
        "round": round,
        "pow": pow,
        "divmod": divmod,
        "ord": ord,
        "chr": chr,
        "hex": hex,
        "oct": oct,
        "bin": bin,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "hasattr": hasattr,
        "getattr": getattr,
        "setattr": setattr,
        "print": print,
        "repr": repr,
        "any": any,
        "all": all,
        "slice": slice,
    }

    local_vars = {"context": context, "re": __import__("re")}
    local_vars.update(safe_builtins)

    def llm_query(prompt: str, chunk: str = None) -> str:
        """Query sub-LLM"""
        if chunk:
            full_prompt = f"{prompt}\n\nContext:\n{chunk}"
        else:
            full_prompt = prompt
        logger.info(f"llm_query called, prompt length: {len(full_prompt)}")
        result = call_nano_gpt(full_prompt, SUB_MODEL, None)
        logger.info(f"llm_query result length: {len(result)}")
        return result

    local_vars["llm_query"] = llm_query

    output = io.StringIO()
    result_vars = {}

    def capture_var(name: str, value):
        result_vars[name] = value

    local_vars["FINAL_VAR"] = capture_var

    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            exec(code, {"__builtins__": safe_builtins}, local_vars)
    except Exception as e:
        logger.error(f"Code execution error: {type(e).__name__}: {str(e)}")
        return f"ERROR: {type(e).__name__}: {str(e)}"

    stdout_result = output.getvalue()

    if result_vars:
        # Return the final variable
        var_name, var_value = list(result_vars.items())[0]
        logger.info(f"FINAL_VAR set: {var_name}")
        return str(var_value)

    if not stdout_result:
        return "Code executed successfully (no output)"

    logger.info(f"Code output: {stdout_result[:200]}...")
    return stdout_result


class RLM:
    def __init__(
        self,
        max_iterations: int = 10,
        root_model: str = ROOT_MODEL,
        sub_model: str = SUB_MODEL,
        log_file: Optional[str] = None,
    ):
        self.max_iterations = max_iterations
        self.root_model = root_model
        self.sub_model = sub_model

        if log_file:
            handler = logging.FileHandler(log_file)
            handler.setFormatter(
                logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            )
            logger.addHandler(handler)

        logger.info(
            f"RLM initialized: root={root_model}, sub={sub_model}, max_iter={max_iterations}"
        )

    def ask(self, question: str, context: str) -> str:
        """Ask a question with the given context"""

        logger.info(f"Question: {question[:100]}...")
        logger.info(f"Context length: {len(context)} chars")

        conversation = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"""Query: {question}

Context length: {len(context)} characters

The context is stored in the 'context' variable. Use print() to examine it.
Use llm_query() to call sub-LLMs on chunks.
Use FINAL_VAR(variable_name) to return your final answer.

Start by examining the context!""",
            },
        ]

        for iteration in range(self.max_iterations):
            logger.info(f"=== Iteration {iteration + 1}/{self.max_iterations} ===")

            response = call_nano_gpt_messages(conversation, self.root_model)

            logger.info(f"LLM response (first 300 chars): {response[:300]}")
            conversation.append({"role": "assistant", "content": response})

            # Check for FINAL_VAR - can be FINAL_VAR("answer") or FINAL_VAR(variable_name)
            final_match = re.search(r'FINAL_VAR\(["\']([^"\']+)["\']\)', response)
            if final_match:
                answer = final_match.group(1)
                logger.info(f"FINAL_VAR with string: {answer}")
                return answer

            final_match = re.search(r"FINAL_VAR\s*\((\w+)\)", response)
            if final_match:
                var_name = final_match.group(1)
                code = f"print({var_name})"
                result = execute_code(code, context, None)
                if result.startswith("ERROR:"):
                    # Variable not defined, try to extract answer from response text
                    logger.warning(
                        f"Variable {var_name} not defined, using response text"
                    )
                    # Remove code blocks and extract answer
                    text = re.sub(r"```.*?```", "", response, flags=re.DOTALL)
                    text = text.strip()
                    if text:
                        return text
                logger.info(f"FINAL_VAR({var_name}) = {result[:200]}")
                return result

            # Extract code blocks - try multiple formats
            code_blocks = re.findall(r"```repl\n(.*?)```", response, re.DOTALL)
            if not code_blocks:
                code_blocks = re.findall(r"```python\n(.*?)```", response, re.DOTALL)

            # Also try to extract from tool call format: {tool => "repl", args => {... --code "..."}}
            if not code_blocks:
                tool_codes = re.findall(r'--code\s+"([^"]+)"', response)
                if tool_codes:
                    code_blocks = tool_codes

            if not code_blocks:
                # Try to get FINAL_ANSWER as fallback
                final_match = re.search(r"FINAL_ANSWER:\s*(.+)", response, re.DOTALL)
                if final_match:
                    return final_match.group(1).strip()

                conversation.append(
                    {
                        "role": "user",
                        "content": "Please write code in ```repl``` code blocks or use FINAL_VAR()",
                    }
                )
                continue

            logger.info(f"Executing {len(code_blocks)} code block(s)")

            for code in code_blocks:
                result = execute_code(code, context, None)
                logger.info(f"Code result: {result[:300]}...")
                conversation.append({"role": "user", "content": f"Output:\n{result}"})

        logger.warning("Max iterations reached")
        return "Max iterations reached without final answer"


def create_rlm(log_file: Optional[str] = None) -> RLM:
    """Factory function to create RLM instance"""
    return RLM(log_file=log_file)
