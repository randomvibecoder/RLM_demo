# RLM Web UI - Simple working version
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
        button:disabled { background: #30363d; }
        #events { background: #161b22; padding: 15px; border-radius: 8px; min-height: 400px; max-height: 70vh; overflow-y: auto; margin-top: 20px; border: 1px solid #30363d; white-space: pre-wrap; }
        .event { padding: 4px 8px; margin: 2px 0; border-radius: 3px; }
        .event-info { background: #30363d; }
        .event-iter { background: #8957e5; color: white; }
        .event-done { background: #238636; color: white; }
        .event-error { background: #da3633; color: white; }
    </style>
</head>
<body>
    <h1>🔍 RLM GitHub QA</h1>
    <input id="repo" value="https://github.com/torvalds/linux" placeholder="GitHub URL">
    <textarea id="question">How are drivers loaded?</textarea>
    <button id="runBtn" onclick="run()">Run RLM</button>
    <div id="events"></div>
    <script>
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
            document.getElementById('runBtn').disabled = true;
            log('🚀 Starting...');
            
            const source = new EventSource('/run?repo=' + encodeURIComponent(repo) + '&q=' + encodeURIComponent(q));
            
            source.onmessage = e => {
                try {
                    if (!e.data) return;
                    const d = JSON.parse(e.data);
                    if (d.type === 'iter') log('📝 Iteration ' + d.n, 'iter');
                    else if (d.type === 'done') {
                        log('✅ Done!', 'done');
                        document.getElementById('runBtn').disabled = false;
                        // Show answer
                        const ans = document.createElement('div');
                        ans.className = 'event event-done';
                        ans.style.whiteSpace = 'pre-wrap';
                        ans.textContent = d.answer.substring(0, 3000);
                        document.getElementById('events').appendChild(ans);
                    }
                    else if (d.type === 'error') {
                        log('❌ ' + d.msg, 'error');
                        document.getElementById('runBtn').disabled = false;
                    }
                    else log(d.msg || '...');
                } catch(err) {}
            };
            
            source.onerror = () => {
                log('Connection closed');
                document.getElementById('runBtn').disabled = false;
            };
        }
    </script>
</body>
</html>"""


@app.get("/run")
async def run(repo: str, q: str):
    """Run RLM and stream events"""

    async def events():
        # Send start
        yield "data: " + json.dumps({"msg": "Starting..."}) + "\n\n"

        try:
            # Setup env
            os.environ["OPENAI_API_KEY"] = os.getenv("NANO_GPT_API_KEY")
            os.environ["OPENAI_BASE_URL"] = os.getenv(
                "NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1"
            )

            # Clone
            yield "data: " + json.dumps({"msg": "Cloning " + repo}) + "\n\n"
            repo_dir = clone_repo(repo)

            yield "data: " + json.dumps({"msg": "Reading files..."}) + "\n\n"
            context = read_files_recursive(repo_dir, max_size_mb=10)
            shutil.rmtree(repo_dir, ignore_errors=True)

            yield (
                "data: "
                + json.dumps({"msg": f"Context: {len(context) / 1024 / 1024:.1f}MB"})
                + "\n\n"
            )

            # Create RLM
            rlm = create_rlm(max_iterations=5, max_depth=3, verbose=True)

            yield (
                "data: " + json.dumps({"msg": "Running RLM (5 iterations)..."}) + "\n\n"
            )

            # Run RLM - this is blocking, we can't stream iterations easily
            # So we'll just run it and return the result
            result = rlm.completion(
                prompt=context,
                root_prompt=q + " - Cite sources with character positions.",
            )

            answer = str(result)
            yield "data: " + json.dumps({"type": "done", "answer": answer}) + "\n\n"

        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "msg": str(e)}) + "\n\n"

        yield "data: " + json.dumps({"type": "done"}) + "\n\n"

    return EventSourceResponse(events())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=3136)
