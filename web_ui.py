# RLM Web UI
# Install with: pip install fastapi uvicorn sse-starlette

import os
import json
import asyncio
import threading
from queue import Queue, Empty
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from github_qa import create_rlm, clone_repo, read_files_recursive
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="RLM GitHub QA")

# Event queue for streaming
event_queue = Queue()


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!DOCTYPE html>
<html>
<head>
    <title>RLM GitHub QA</title>
    <style>
        * { box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px; 
            margin: 0 auto; 
            padding: 20px;
            background: #0d1117;
            color: #c9d1d9;
        }
        h1 { color: #58a6ff; }
        .input-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; color: #8b949e; }
        input, textarea { 
            width: 100%; 
            padding: 10px; 
            border-radius: 6px;
            border: 1px solid #30363d;
            background: #161b22;
            color: #c9d1d9;
            font-size: 14px;
        }
        textarea { height: 80px; resize: vertical; }
        button {
            background: #238636;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
        }
        button:hover { background: #2ea043; }
        button:disabled { background: #30363d; cursor: not-allowed; }
        #events {
            margin-top: 20px;
            background: #161b22;
            border-radius: 8px;
            padding: 15px;
            min-height: 300px;
            max-height: 500px;
            overflow-y: auto;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 13px;
            line-height: 1.6;
            white-space: pre-wrap;
        }
        .event { padding: 8px 12px; margin: 4px 0; border-radius: 4px; }
        .event-start { background: #1f6feb; color: white; }
        .event-iteration { background: #8957e5; color: white; }
        .event-python { background: #da3633; color: white; }
        .event-subllm { background: #f78166; color: white; }
        .event-complete { background: #238636; color: white; }
        .event-error { background: #da3633; color: white; }
        .event-info { background: #30363d; }
        .event-stream { background: #21262d; border-left: 3px solid #58a6ff; }
        .timestamp { color: #8b949e; font-size: 11px; }
        .spinner {
            display: inline-block;
            width: 12px;
            height: 12px;
            border: 2px solid #8b949e;
            border-top-color: transparent;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-right: 8px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <h1>🔍 RLM GitHub QA</h1>
    <p>Ask questions about any GitHub repository using Recursive Language Models</p>
    
    <div class="input-group">
        <label>GitHub Repository URL</label>
        <input type="text" id="repoUrl" placeholder="https://github.com/torvalds/linux" value="https://github.com/torvalds/linux">
    </div>
    
    <div class="input-group">
        <label>Question</label>
        <textarea id="question" placeholder="How are drivers loaded in this codebase?">How are drivers loaded in this codebase?</textarea>
    </div>
    
    <button id="runBtn" onclick="runRLM()">
        <span class="spinner" id="spinner" style="display:none"></span>Run RLM
    </button>
    
    <h3>Live Events</h3>
    <div id="events"></div>
    
    <script>
        let eventSource = null;
        
        function addEvent(type, data) {
            const events = document.getElementById('events');
            const div = document.createElement('div');
            div.className = 'event event-' + type;
            
            let content = '';
            const time = new Date().toLocaleTimeString();
            
            switch(type) {
                case 'start':
                    content = '🚀 <b>Starting RLM</b><br>Question: ' + data.question + '<br>Repo: ' + data.repo;
                    break;
                case 'info':
                    content = 'ℹ️ ' + data.message;
                    break;
                case 'iteration':
                    content = '📝 ' + data.line;
                    break;
                case 'stream':
                    content = '<span class="timestamp">' + time + '</span> ' + escapeHtml(data.line);
                    break;
                case 'complete':
                    content = '✅ <b>Final Answer</b><br>' + escapeHtml(data.answer.substring(0, 1000));
                    if (data.answer.length > 1000) content += '...';
                    break;
                case 'error':
                    content = '❌ <b>Error</b><br>' + escapeHtml(data.message);
                    break;
                default:
                    content = escapeHtml(JSON.stringify(data));
            }
            
            div.innerHTML = content;
            events.appendChild(div);
            events.scrollTop = events.scrollHeight;
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        async function runRLM() {
            const repoUrl = document.getElementById('repoUrl').value;
            const question = document.getElementById('question').value;
            const btn = document.getElementById('runBtn');
            const spinner = document.getElementById('spinner');
            const eventsDiv = document.getElementById('events');
            
            btn.disabled = true;
            spinner.style.display = 'inline-block';
            eventsDiv.innerHTML = '';
            
            if (eventSource) {
                eventSource.close();
            }
            
            const url = '/ask?repo=' + encodeURIComponent(repoUrl) + '&question=' + encodeURIComponent(question);
            eventSource = new EventSource(url);
            
            eventSource.onmessage = function(e) {
                const data = JSON.parse(e.data);
                addEvent(data.type, data.data);
            };
            
            eventSource.onerror = function(e) {
                console.log('Error:', e);
                btn.disabled = false;
                spinner.style.display = 'none';
                eventSource.close();
            };
            
            eventSource.addEventListener('done', function(e) {
                btn.disabled = false;
                spinner.style.display = 'none';
            });
        }
    </script>
</body>
</html>"""


@app.get("/ask")
async def ask(repo: str, question: str):
    """Stream RLM events via SSE"""

    async def event_generator():
        os.environ["OPENAI_API_KEY"] = os.getenv("NANO_GPT_API_KEY")
        os.environ["OPENAI_BASE_URL"] = os.getenv(
            "NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1"
        )

        # Send start event
        yield json.dumps(
            {"type": "start", "data": {"question": question, "repo": repo}}
        )

        try:
            # Clone repo
            yield json.dumps(
                {"type": "info", "data": {"message": f"Cloning {repo}..."}}
            )

            repo_dir = clone_repo(repo)
            yield json.dumps({"type": "info", "data": {"message": "Reading files..."}})

            context = read_files_recursive(repo_dir, max_size_mb=10)

            import shutil

            shutil.rmtree(repo_dir, ignore_errors=True)

            size_mb = len(context) / 1024 / 1024
            yield json.dumps(
                {
                    "type": "info",
                    "data": {"message": f"Context ready: {size_mb:.2f} MB"},
                }
            )

            # Create RLM with verbose=True to capture output
            rlm = create_rlm(max_iterations=5, max_depth=3, verbose=True)

            yield json.dumps(
                {"type": "info", "data": {"message": "Running RLM (5 iterations)..."}}
            )

            # Run RLM - verbose=True prints to stdout
            import io
            import sys

            # Capture stdout in a thread-safe way
            output_buffer = []

            # We'll run RLM in a separate thread and stream output
            def run_rlm():
                old_stdout = sys.stdout
                sys.stdout = captured = io.StringIO()
                try:
                    result = rlm.completion(
                        prompt=context,
                        root_prompt=f"{question} - Cite your sources with character positions.",
                    )
                    output = captured.getvalue()
                    output_buffer.append(("complete", str(result)))
                except Exception as e:
                    output_buffer.append(("error", str(e)))
                finally:
                    sys.stdout = old_stdout

            # Run in thread so we can stream
            thread = threading.Thread(target=run_rlm)
            thread.start()

            # Stream output as it comes
            last_pos = 0
            while thread.is_alive():
                # Check for new output (this is a hacky way - verbose output goes to stdout)
                await asyncio.sleep(2)
                yield json.dumps(
                    {
                        "type": "info",
                        "data": {"message": "Running... (this takes a few minutes)"},
                    }
                )

            thread.join()

            # Send final result
            if output_buffer:
                etype, data = output_buffer[0]
                if etype == "complete":
                    yield json.dumps({"type": "complete", "data": {"answer": data}})
                else:
                    yield json.dumps({"type": "error", "data": {"message": data}})

        except Exception as e:
            yield json.dumps({"type": "error", "data": {"message": str(e)}})

        yield json.dumps({"type": "done"})

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=3136)
