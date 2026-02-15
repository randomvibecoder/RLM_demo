# RLM Implementation Journal

## Entry 1: Feb 15, 2026 - Initial Setup

### What Happened:
1. Cloned Linux kernel repository (sparse checkout for kernel/sched)
2. Set up .env file with nano GPT API keys
3. Researched RLM (Recursive Language Models) from the paper arxiv.org/abs/2512.24601

### Technical Notes:
- RLM is a technique where the root LM writes Python code to inspect context instead of processing the entire context directly
- Root LM can recursively call sub-LMs on chunks of the context
- This allows handling contexts far larger than the model's context window

## Entry 2: Feb 15, 2026 - First RLM Implementation

### What Happened:
1. Created rlm_minimax.py - full RLM implementation with:
   - NanoGPTClient for API calls to minimax/minimax-m2.5
   - REPLEnvironment to execute Python code
   - RLM class with root/sub LM architecture

2. Fixed model name from "minimax2.5" to "minimax/minimax-m2.5" (found via API)

### Issues Encountered:
- Model name was incorrect - had to query /models endpoint
- The minimax model kept trying to use tool calling format (~~~function) instead of writing Python code
- The _extract_code function couldn't parse the model's response format

## Entry 3: Feb 15, 2026 - Debugging Model Responses

### What Happened:
- The minimax model kept outputting tool-like invocations instead of actual Python code
- Model format: <filepath>~~~python\ncode\n~~~</invoke>
- Tried multiple regex patterns to extract code but model kept changing formats
- Created simplified version (rlm_simple.py) as fallback

### Current Status:
- Full RLM implementation exists but model doesn't cooperate with code execution paradigm
- Simplified version sends relevant code directly to model

## Entry 4: Feb 15, 2026 - GitHub Setup

### What Happened:
1. Checked gh auth status - authenticated as randomvibecoder
2. Created private repo: https://github.com/randomvibecoder/RLM_demo

### Files to Commit:
- rlm_minimax.py (full RLM)
- rlm_simple.py (simplified version)
- .env (API keys - DON'T PUSH)
- linux/ (kernel source)

## Entry 5: Feb 15, 2026 - Running Tests

### What Happened:
- Attempted to run rlm_simple.py to get answer
- Command timed out/aborted
- Need to try again with better error handling

### Next Steps:
- Fix the simplified RLM to get answer
- Commit working code to GitHub

## Entry 6: Feb 15, 2026 - SUCCESS! RLM Answer Received

### What Happened:
1. Ran rlm_simple.py successfully
2. Got detailed answer about calc_delta_fair() arithmetic trick
3. Pushed to private repo https://github.com/randomvibecoder/RLM_demo

### The Answer:
The CFS scheduler uses **reciprocal multiplication** to avoid division:
- Instead of: `delta_exec * weight / lw->weight`
- Uses: `(delta_exec * weight * inv_weight) >> WMULT_SHIFT`
- Where `WMULT_SHIFT = 32` and `WMULT_CONST = 2^32 - 1`
- `inv_weight = WMULT_CONST / weight` is pre-computed once

This is implemented in `__calc_delta()` which is called from `calc_delta_fair()`.

### Full RLM Status:
- The full RLM (rlm_minimax.py) has the architecture but minimax model doesn't follow the code execution paradigm
- The model keeps outputting tool-like invocations instead of actual Python code
- Simplified version works by sending relevant code directly to the model

## Entry 7: Feb 15, 2026 - Files Committed

### What Happened:
1. Cleaned up gitignore to exclude linux/, .env, images, pycache
2. Committed to rlm-demo remote (private repo)
3. Files committed: .gitignore, journal.md, rlm_minimax.py, rlm_simple.py, requirements.txt, .env.example, README.md, github_qa.py, web_ui.py

## Entry 8: Feb 15, 2026 - Full RLM with Chunking Works!

### What Happened:
1. Created rlm_full.py - chunk-based RLM that doesn't require model to write Python code
2. Instead, it splits context into chunks and uses root/sub LM pattern
3. Successfully got answer about calc_delta_fair arithmetic trick

### The Chunk-Based Approach:
- Splits context into ~500 line chunks
- Root model identifies which chunks are relevant
- Sub model analyzes each relevant chunk
- Root model synthesizes final answer

### Files Added:
- rlm_full.py - Full RLM with chunk-based sub-calls
