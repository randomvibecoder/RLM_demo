#!/usr/bin/env python3
"""
Full RLM implementation with chunk-based sub-calls
Works by giving the model chunks of context to analyze
"""

import os
import sys
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

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
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

        for attempt in range(3):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=120,
                )
                if response.status_code != 200:
                    print(f"Error: {response.status_code} - {response.text[:200]}")
                    time.sleep(5)
                    continue
                return response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                time.sleep(5)
        return ""


class RLMChunk:
    """A chunk of the context that can be analyzed"""

    def __init__(self, content: str, start_line: int, end_line: int):
        self.content = content
        self.start_line = start_line
        self.end_line = end_line

    def __str__(self):
        return f"=== Lines {self.start_line}-{self_end_line} ===\n{self.content}"


class FullRLM:
    """
    Full RLM with recursive sub-calls.
    Instead of asking model to write Python code (which doesn't work well with minimax),
    we chunk the context and let root model recursively call sub-model on chunks.
    """

    def __init__(
        self,
        root_model: str = "minimax/minimax-m2.5",
        sub_model: str = "minimax/minimax-m2.5",
    ):
        self.root_client = NanoGPTClient(model=root_model)
        self.sub_client = NanoGPTClient(model=sub_model)
        self.chunk_size = 500  # lines per chunk

    def chunk_context(self, context: str, chunk_size: int = 500) -> List[RLMChunk]:
        """Split context into chunks"""
        lines = context.split("\n")
        chunks = []
        for i in range(0, len(lines), chunk_size):
            chunk = RLMChunk(
                content="\n".join(lines[i : i + chunk_size]),
                start_line=i,
                end_line=min(i + chunk_size, len(lines)),
            )
            chunks.append(chunk)
        return chunks

    def run(self, context: str, question: str) -> str:
        """Run RLM with chunk-based recursion"""

        # First, ask root model to identify which chunks are relevant
        chunks = self.chunk_context(context)

        print(f"Context split into {len(chunks)} chunks")

        # Root model analyzes question and decides which chunks to examine
        root_prompt = f"""You are analyzing Linux kernel code to answer: {question}

The file has {len(chunks)} chunks (each ~{self.chunk_size} lines).
First, tell me which chunk numbers (0-{len(chunks) - 1}) are most likely to contain the answer.
Just list the chunk numbers, nothing else."""

        messages = [
            {
                "role": "system",
                "content": "You are a code analysis expert. Identify relevant code sections.",
            },
            {"role": "user", "content": root_prompt},
        ]

        print("\n=== Root Model: Identifying relevant chunks ===")
        response = self.root_client.chat(messages)
        print(f"Response: {response[:500]}")

        # Parse chunk numbers from response
        relevant_chunks = []
        for i in range(len(chunks)):
            if (
                f"chunk {i}" in response.lower()
                or f"lines {i * self.chunk_size}" in response.lower()
            ):
                relevant_chunks.append(i)

        # If no specific chunks found, check a few
        if not relevant_chunks:
            # Check chunks around calc_delta_fair line (around line 290)
            relevant_chunks = [0, 1]  # Check first few chunks as fallback

        print(f"Relevant chunks: {relevant_chunks}")

        # Now recursively call sub-model on each relevant chunk
        sub_answers = []
        for chunk_idx in relevant_chunks[:3]:  # Limit to 3 chunks
            chunk = chunks[chunk_idx]
            sub_prompt = f"""Analyze this code chunk (lines {chunk.start_line}-{chunk.end_line}) from kernel/sched/fair.c

Question: {question}

Code:
{chunk.content}

Provide a detailed answer based ONLY on this chunk:"""

            messages = [
                {
                    "role": "system",
                    "content": "You are a kernel expert. Analyze the code and provide detailed answer.",
                },
                {"role": "user", "content": sub_prompt},
            ]

            print(f"\n=== Sub Model: Analyzing chunk {chunk_idx} ===")
            answer = self.sub_client.chat(messages)
            sub_answers.append(f"Chunk {chunk_idx}:\n{answer}")

        # Root model synthesizes final answer
        synthesis_prompt = f"""Question: {question}

Answers from code analysis:
{chr(10).join(sub_answers)}

Synthesize these into a final answer:"""

        messages = [
            {
                "role": "system",
                "content": "Synthesize the analysis into a clear answer.",
            },
            {"role": "user", "content": synthesis_prompt},
        ]

        print("\n=== Root Model: Synthesizing final answer ===")
        final_answer = self.root_client.chat(messages)

        return final_answer


def main():
    # Load fair.c
    fair_c_path = Path("linux/kernel/sched/fair.c")
    if not fair_c_path.exists():
        print("Error: fair.c not found!")
        sys.exit(1)

    with open(fair_c_path) as f:
        context = f.read()

    question = """In calc_delta_fair(), what arithmetic trick avoids division in the hot path?"""

    rlm = FullRLM()
    answer = rlm.run(context, question)

    print("\n" + "=" * 60)
    print("FINAL ANSWER:")
    print("=" * 60)
    print(answer)


if __name__ == "__main__":
    main()
