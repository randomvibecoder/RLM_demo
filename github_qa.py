import os
import tempfile
import shutil
import subprocess
import logging
import datetime
from typing import List, Optional
from pathlib import Path

from rlm.core import RLM

logger = logging.getLogger(__name__)


def clone_repo(repo_url: str, dest_dir: Optional[str] = None) -> str:
    """Clone a GitHub repository to a directory"""
    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix="rlm_repo_")

    logger.info(f"Cloning {repo_url} to {dest_dir}...")
    print(f"Cloning {repo_url} to {dest_dir}...")

    result = subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, dest_dir],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        logger.error(f"Failed to clone repo: {result.stderr}")
        raise Exception(f"Failed to clone repo: {result.stderr}")

    logger.info(f"Successfully cloned repo")
    return dest_dir


def read_files_recursive(directory: str, max_size_mb: int = 50) -> str:
    """Read all files in directory and concatenate into one string"""
    max_bytes = max_size_mb * 1024 * 1024
    total_size = 0
    files_content = []

    # Extensions to include
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

    # Directories to skip
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

    path = Path(directory)
    file_count = 0

    for file_path in path.rglob("*"):
        # Skip directories
        if file_path.is_dir():
            if any(skip in file_path.parts for skip in skip_dirs):
                continue
            continue

        # Check extension
        if file_path.suffix not in extensions:
            continue

        # Skip large files
        try:
            file_size = file_path.stat().st_size
            if file_size > 10 * 1024 * 1024:  # Skip files > 10MB
                continue
            if total_size + file_size > max_bytes:
                logger.warning(
                    f"Reached max size limit ({max_size_mb}MB), stopping file collection"
                )
                break
        except:
            continue

        # Read file
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            rel_path = file_path.relative_to(directory)
            files_content.append(f"=== File: {rel_path} ===\n{content}\n")
            total_size += file_size
            file_count += 1
        except:
            continue

    logger.info(
        f"Read {file_count} files, total size: {total_size / 1024 / 1024:.2f} MB"
    )
    print(f"Read {file_count} files, total size: {total_size / 1024 / 1024:.2f} MB")
    return "\n\n".join(files_content)


def ask_about_repo(
    repo_url: str,
    question: str,
    rlm: Optional[RLM] = None,
    max_context_size_mb: int = 10,
) -> str:
    """Clone a repo and ask a question about it using RLM"""

    # Create log file for this run
    log_file = f"logs/rlm_run_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    os.makedirs("logs", exist_ok=True)

    if rlm is None:
        rlm = RLM(log_file=log_file)

    logger.info(f"Starting RLM query for repo: {repo_url}")
    logger.info(f"Question: {question}")
    logger.info(f"Max context size: {max_context_size_mb}MB")

    # Clone repo
    repo_dir = None
    try:
        repo_dir = clone_repo(repo_url)

        # Read all files
        context = read_files_recursive(repo_dir, max_size_mb=max_context_size_mb)

        if not context:
            logger.warning("No readable files found in repository")
            return "No readable files found in repository"

        logger.info(
            f"Context prepared, length: {len(context)} chars ({len(context) / 1024 / 1024:.2f}MB)"
        )

        # Ask question via RLM
        print(f"Asking RLM: {question}")
        answer = rlm.ask(question, context)

        logger.info(f"Final answer: {answer}")
        return answer

    finally:
        # Cleanup
        if repo_dir and os.path.exists(repo_dir):
            logger.info(f"Cleaning up repo directory: {repo_dir}")
            shutil.rmtree(repo_dir, ignore_errors=True)


if __name__ == "__main__":
    # Test with Linux kernel repo
    log_file = f"logs/rlm_test_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    rlm = RLM(log_file=log_file, max_iterations=5)
    answer = ask_about_repo(
        "https://github.com/torvalds/linux",
        "How are drivers loaded in this codebase?",
        rlm,
        max_context_size_mb=5,  # Start with small context for testing
    )
    print("\nAnswer:", answer)
    print(f"\nFull logs saved to: {log_file}")
