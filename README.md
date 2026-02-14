# RLM_Github

Recursive Language Model (RLM) implementation for analyzing GitHub repositories.

Based on the paper "Recursive Language Models" (https://arxiv.org/abs/2512.24601)

## What is an RLM?

RLMs allow LLMs to process arbitrarily long contexts (10M+ tokens) by:
1. Loading the entire context as a variable in a Python REPL
2. The LLM writes code to examine/decompose the context
3. Can recursively call sub-LMs on chunks of the context

## Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy .env.example to .env and add your API key
cp .env.example .env
```

## Usage

```python
from rlm.core import RLM
from github_qa import ask_about_repo

# Simple RLM usage
rlm = RLM()
answer = rlm.ask("What is the main function?", "def main(): pass")

# Ask about a GitHub repo
answer = ask_about_repo(
    "https://github.com/torvalds/linux",
    "How are drivers loaded in this codebase?"
)
```

## API

This project uses nano-gpt.com API for both root and sub-LLM calls:
- Root model: `minimax/minimax-m2.5`
- Sub-model: `meta-llama/llama-4-maverick`
