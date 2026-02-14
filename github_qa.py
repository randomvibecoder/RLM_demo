"""
GitHub Repo Q&A using RLM with source citations.
Uses the official rlm package from pip with nano-gpt backend.
"""

import os
import tempfile
import shutil
import subprocess
from pathlib import Path

# Patch rlm to handle nano-gpt
import rlm.clients.openai as openai_client

_original_init = openai_client.OpenAIClient.__init__


def _patched_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    self.last_prompt_tokens = 0
    self.last_completion_tokens = 0
    self.last_total_tokens = 0


_original_track = openai_client.OpenAIClient._track_cost


def _patched_track_cost(self, response, model):
    try:
        extra = getattr(response, "extra_data", {}) or {}
        pricing = extra.get("x_nanogpt_pricing", {}) if isinstance(extra, dict) else {}
        if pricing:
            self.last_prompt_tokens = pricing.get("inputTokens", 0)
            self.last_completion_tokens = pricing.get("outputTokens", 0)
            self.last_total_tokens = (
                self.last_prompt_tokens + self.last_completion_tokens
            )
            return
    except:
        pass
    try:
        _original_track(self, response, model)
    except:
        pass


openai_client.OpenAIClient.__init__ = _patched_init
openai_client.OpenAIClient._track_cost = _patched_track_cost

from rlm import RLM


# Custom system prompt with source citations
CUSTOM_PROMPT = """You are a Recursive Language Model (RLM). You have access to a Python REPL environment where the context is stored as a string variable called 'context'.

IMPORTANT: When you provide information in your FINAL_ANSWER, you MUST cite your sources by including the character position ranges from the context that support your answer. For example:
- "According to context[1500:2000], the driver is loaded via module_init()"
- "The code at context[100:300] shows that..."

The context is formatted with file markers:
=== File: path/to/file ===
file content here
=== File: another/file ===
more content

Use llm_query() to call sub-LLMs on chunks when needed.
Use print() to examine the context.
Use FINAL_ANSWER with source citations to return your final answer."""


def create_rlm(max_iterations: int = 3, verbose: bool = True) -> RLM:
    """Create RLM instance with nano-gpt backend"""
    return RLM(
        backend="openai",
        backend_kwargs={"model_name": "minimax/minimax-m2.5"},
        environment="local",
        max_iterations=max_iterations,
        custom_system_prompt=CUSTOM_PROMPT,
        verbose=verbose,
    )


def clone_repo(repo_url: str, dest_dir: str = None) -> str:
    """Clone a GitHub repository"""
    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix="rlm_repo_")

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    result = subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, dest_dir],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )

    if result.returncode != 0:
        raise Exception(f"Failed to clone: {result.stderr}")

    return dest_dir


def read_files_recursive(directory: str, max_size_mb: int = 50) -> str:
    """Read all files and concatenate with file markers"""
    max_bytes = max_size_mb * 1024 * 1024
    total_size = 0
    files_content = []

    extensions = {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".scala",
        ".sh",
        ".bash",
        ".yml",
        ".yaml",
        ".json",
        ".toml",
        ".md",
        ".txt",
        ".sql",
        ".html",
        ".css",
    }

    skip_dirs = {
        ".git",
        "node_modules",
        "__pycache__",
        "venv",
        ".venv",
        "build",
        "dist",
        "target",
    }

    for file_path in Path(directory).rglob("*"):
        if file_path.is_dir():
            if any(skip in file_path.parts for skip in skip_dirs):
                continue
            continue

        if file_path.suffix not in extensions:
            continue

        try:
            file_size = file_path.stat().st_size
            if file_size > 10 * 1024 * 1024:
                continue
            if total_size + file_size > max_bytes:
                break
        except:
            continue

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            rel_path = file_path.relative_to(directory)
            files_content.append(f"=== File: {rel_path} ===\n{content}\n")
            total_size += file_size
        except:
            continue

    return "\n\n".join(files_content)


def ask_about_repo(
    repo_url: str,
    question: str,
    rlm: RLM = None,
    max_context_size_mb: int = 10,
) -> str:
    """Ask a question about a GitHub repository using RLM"""

    # Setup environment
    from dotenv import load_dotenv

    load_dotenv()
    os.environ["OPENAI_API_KEY"] = os.getenv("NANO_GPT_API_KEY")
    os.environ["OPENAI_BASE_URL"] = os.getenv(
        "NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1"
    )

    if rlm is None:
        rlm = create_rlm()

    print(f"Cloning {repo_url}...")
    repo_dir = None
    try:
        repo_dir = clone_repo(repo_url)
        context = read_files_recursive(repo_dir, max_size_mb=max_context_size_mb)

        if not context:
            return "No readable files found"

        print(f"Context: {len(context)} chars ({len(context) / 1024 / 1024:.2f}MB)")
        print(f"Asking: {question}")

        result = rlm.completion(
            prompt=context,
            root_prompt=f"{question} - Cite your sources with character positions like context[100:200]",
        )

        # Extract answer
        if hasattr(result, "iterations") and result.iterations:
            last = result.iterations[-1]
            if hasattr(last, "final_answer"):
                return last.final_answer
            if hasattr(last, "response"):
                return last.response

        return str(result)

    finally:
        if repo_dir and os.path.exists(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    # Test with full Linux kernel repo (287MB+, feed 50MB)
    rlm = create_rlm(max_iterations=10)  # More iterations!
    answer = ask_about_repo(
        "https://github.com/torvalds/linux",
        "How are drivers loaded in this codebase?",
        rlm,
        max_context_size_mb=50,  # Feed 50MB of code!
    )
    print("\n" + "=" * 60)
    print("ANSWER:")
    print(answer)
    print("=" * 60)
