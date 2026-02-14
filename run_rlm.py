#!/usr/bin/env python3
"""Run RLM with nano-gpt - includes source citation feature"""

import os
from dotenv import load_dotenv

load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("NANO_GPT_API_KEY")
os.environ["OPENAI_BASE_URL"] = os.getenv(
    "NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1"
)

# Patch the RLM client to handle missing usage
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

# Custom system prompt that asks for source citations
custom_prompt = """You are a Recursive Language Model (RLM). You have access to a Python REPL environment where the context is stored as a string variable called 'context'.

IMPORTANT: When you provide information in your FINAL_ANSWER, you MUST cite your sources by including the character position ranges from the context that support your answer. For example:
- "According to context[1500:2000], the driver is loaded via module_init()"
- "The code at context[100:300] shows that..."

The context is formatted as:
=== File: path/to/file ===
file content here
=== File: another/file ===
more content

Use llm_query() to call sub-LLMs on chunks when needed.
Use print() to examine the context.
Use FINAL_ANSWER with source citations to return your final answer."""

rlm = RLM(
    backend="openai",
    backend_kwargs={"model_name": "minimax/minimax-m2.5"},
    environment="local",
    max_iterations=3,
    verbose=True,
    custom_system_prompt=custom_prompt,
)

context = """=== File: kernel/driver.c ===
static int driver_init(void) {
    return driver_register(&my_driver);
}
module_init(driver_init);

=== File: kernel/driver.h ===
struct driver {
    int (*probe)(struct device *dev);
    void (*remove)(struct device *dev);
};
"""

result = rlm.completion(
    prompt=context,
    root_prompt="How are drivers loaded in this codebase? Cite your sources with character positions.",
)

print("=" * 60)
print("FINAL ANSWER:")
# Check available attributes
if hasattr(result, "final_answer"):
    print(result.final_answer)
elif hasattr(result, "iterations") and result.iterations:
    last_iter = result.iterations[-1]
    if hasattr(last_iter, "final_answer"):
        print(last_iter.final_answer)
    else:
        print("Last iteration:", last_iter)
else:
    print(result)
print("=" * 60)
