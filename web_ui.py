# RLM Web UI - Simple streaming version
import os
import json
import asyncio
import threading
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from github_qa import create_rlm, clone_repo, read_files_recursive
from dotenv import load_dotenv
import shutil

load_dotenv()

app = FastAPI(title="RLM GitHub QA")

# In-memory storage for job results
jobs = {}


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!DOCTYPE html>
<html>
<head>
    <title>RLM GitHub QA</title>
    <style>
        body { font-family: 'Monaco', monospace; background: #0d1117; color: #c9d1d9; padding: 20px; max-width: 900px; margin: 0 auto; }
        h1 { color: #58a6ff; }
        input, textarea { width: 100%; padding: 10px; background: #161b22; border: 1px solid #30363d; color: #c9d1d9; border-radius: 6px; margin-bottom: 10px; }
        textarea { height: 60px; }
        button { background: #238636; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-size: 14px; }
        button:hover { background: #2ea043; }
        #events { background: #161b22; padding: 15px; border-radius: 8px; min-height: 400px; max-height: 70vh; overflow-y: auto; margin-top: 20px; border: 1px solid #30363d; }
        .event { padding: 4px 8px; margin: 2px 0; border-radius: 3px; }
        .event-info { background: #30363d; }
        .event-iter { background: #8957e5; color: white; }
        .event-code { background: #da3633; color: white; }
        .event-done { background: #238636; color: white; }
        .event-error { background: #da3633; color: white; }
    </style>
</head>
<body>
    <h1>🔍 RLM GitHub QA</h1>
    <input id="repo" value="https://github.com/torvalds/linux" placeholder="GitHub URL">
    <textarea id="question">How are drivers loaded?</textarea>
    <button onclick="run()">Run RLM</button>
    <div id="events"></div>
    <script>
        let source = null;
        
        function log(msg, type='info') {
            const d = document.createElement('div');
            d.className = 'event event-' + type;
            d.textContent = msg;
            document.getElementById('events').appendChild(d);
            document.getElementById('events').scrollTop = 1e9;
        }
        
        function run() {
            const repo = document.getElementById('repo').value;
            const q = document.getElementById('question').value;
            document.getElementById('events').innerHTML = '';
            log('🚀 Starting...');
            
            if (source) source.close();
            source = new EventSource('/stream?repo=' + encodeURIComponent(repo) + '&q=' + encodeURIComponent(q));
            
            source.onmessage = e => {
                const d = JSON.parse(e.data);
                if (d.type === 'iter') log('📝 Iteration ' + d.n, 'iter');
                else if (d.type === 'code') log('🐍 ' + d.code.substring(0,80), 'code');
                else if (d.type === 'done') log('✅ Done: ' + d.answer.substring(0,200), 'done');
                else if (d.type === 'error') log('❌ ' + d.msg, 'error');
                else log(d.msg);
            };
            
            source.onerror = () => log('Connection closed');
        }
    </script>
</body>
</html>"""


def run_rlm(job_id, repo, question):
    """Run RLM in background thread"""
    os.environ["OPENAI_API_KEY"] = os.getenv("NANO_GPT_API_KEY")
    os.environ["OPENAI_BASE_URL"] = os.getenv(
        "NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1"
    )

    try:
        jobs[job_id] = {"status": "cloning", "events": []}

        repo_dir = clone_repo(repo)
        context = read_files_recursive(repo_dir, max_size_mb=10)
        shutil.rmtree(repo_dir, ignore_errors=True)

        jobs[job_id]["status"] = "running"
        jobs[job_id]["context_size"] = len(context)

        rlm = create_rlm(max_iterations=5, max_depth=3, verbose=True)

        # Run with custom handler to capture iterations
        import sys
        from io import StringIO

        old = sys.stdout
        sys.stdout = captured = StringIO()

        result = rlm.completion(
            prompt=context,
            root_prompt=question + " - Cite sources with character positions.",
        )

        sys.stdout = old
        output = captured.getvalue()

        # Parse iterations
        import re

        for match in re.finditer(r"Iteration\s+(\d+)", output):
            jobs[job_id]["events"].append({"type": "iter", "n": match.group(1)})

        # Get answer
        answer = str(result)
        jobs[job_id]["status"] = "done"
        jobs[job_id]["answer"] = answer

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


@app.get("/stream")
async def stream(repo: str, q: str):
    import uuid

    job_id = str(uuid.uuid4())

    async def events():
        # Start RLM in background
        thread = threading.Thread(target=run_rlm, args=(job_id, repo, q))
        thread.start()

        # Stream events
        seen_iters = set()

        while True:
            await asyncio.sleep(2)

            job = jobs.get(job_id)
            if not job:
                yield "data: " + json.dumps({"msg": "Starting..."}) + "\n\n"
                continue

            if job["status"] == "error":
                yield (
                    "data: "
                    + json.dumps({"type": "error", "msg": job["error"]})
                    + "\n\n"
                )
                break

            # Send new iterations
            for e in job.get("events", []):
                if e["n"] not in seen_iters:
                    seen_iters.add(e["n"])
                    yield "data: " + json.dumps(e) + "\n\n"

            if job["status"] == "done":
                # Send final answer
                answer = job.get("answer", "No answer")
                # Truncate for display
                if len(answer) > 500:
                    answer = answer[:500] + "..."
                yield "data: " + json.dumps({"type": "done", "answer": answer}) + "\n\n"
                break

        yield "data: " + json.dumps({"type": "done"}) + "\n\n"

    return EventSourceResponse(events())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=3136)
