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


def create_rlm(
    max_iterations: int = 3, max_depth: int = 3, verbose: bool = True
) -> RLM:
    """Create RLM instance with nano-gpt backend"""
    return RLM(
        backend="openai",
        backend_kwargs={"model_name": "minimax/minimax-m2.5-official"},
        environment="local",
        max_iterations=max_iterations,
        max_depth=max_depth,  # Enable recursion!
        # Sub-LM config - use same model
        other_backends=["openai"],
        other_backend_kwargs=[{"model_name": "minimax/minimax-m2.5-official"}],
        custom_system_prompt=CUSTOM_PROMPT,
        verbose=verbose,
    )


def clone_repo(repo_url: str, dest_dir: str = None, progress_callback=None) -> str:
    """Clone a GitHub repository with progress reporting"""
    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix="rlm_repo_")

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    process = subprocess.Popen(
        ["git", "clone", "--progress", "--depth", "1", repo_url, dest_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    import re

    last_pct = 0

    for line in process.stdout:
        if progress_callback:
            # Parse git progress - various formats:
            # "Counting objects:  12% (11803/98356)"
            # "Compressing objects:   5% (4370/87388)"
            # "Receiving objects:  12% (35000/290000), 25.00 MiB | 2.50 MiB/s"
            # "Resolving deltas:  45% (1000/2200)"

            if "Counting objects:" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    last_pct = int(match.group(1))
                    progress_callback(
                        "clone", last_pct, f"Counting objects: {last_pct}%"
                    )
            elif "Compressing objects:" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    last_pct = int(match.group(1))
                    progress_callback(
                        "clone", last_pct, f"Compressing objects: {last_pct}%"
                    )
            elif "Receiving objects:" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    last_pct = int(match.group(1))
                    progress_callback(
                        "clone", last_pct, f"Receiving objects: {last_pct}%"
                    )
            elif "Resolving deltas:" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    last_pct = int(match.group(1))
                    progress_callback(
                        "clone", last_pct, f"Resolving deltas: {last_pct}%"
                    )

    process.wait()

    if process.returncode != 0:
        raise Exception(f"Failed to clone")

    return dest_dir


def read_files_recursive(
    directory: str, max_size_mb: int = 50, progress_callback=None
) -> str:
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

    # First pass: count files (fast)
    all_files = []
    for file_path in Path(directory).rglob("*"):
        if file_path.is_dir():
            if any(skip in file_path.parts for skip in skip_dirs):
                continue
            continue
        if file_path.suffix not in extensions:
            continue
        try:
            if file_path.stat().st_size > 10 * 1024 * 1024:
                continue
        except:
            continue
        all_files.append(file_path)

    total_files = len(all_files)
    processed = 0

    for file_path in all_files:
        try:
            file_size = file_path.stat().st_size
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
            processed += 1

            if progress_callback and total_files > 0:
                pct = int((processed / total_files) * 100)
                progress_callback(
                    "read", pct, f"Reading files: {processed}/{total_files}"
                )
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
    rlm = create_rlm(
        max_iterations=30, max_depth=3
    )  # 30 iterations, 3 levels of recursion!
    answer = ask_about_repo(
        "https://github.com/torvalds/linux",
        "What programming languages are used in this codebase?",
        rlm,
        max_context_size_mb=10,  # Smaller context for faster test
    )
    print("\n" + "=" * 60)
    print("ANSWER:")
    print(answer)
    print("=" * 60)
