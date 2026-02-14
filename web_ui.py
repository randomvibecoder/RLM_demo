# RLM Web UI
# Install with: pip install fastapi uvicorn sse-starlette

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
import json
import asyncio
from queue import Queue
from pathlib import Path

from github_qa import create_rlm, clone_repo, read_files_recursive
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="RLM GitHub QA")

# Event queue for streaming
event_queue = Queue()


class StreamingRLM:
    """Wrapper around RLM that emits events for streaming"""

    def __init__(self, rlm, event_emitter):
        self.rlm = rlm
        self.event_emitter = event_emitter

    def emit(self, event_type, data):
        self.event_emitter.put({"type": event_type, "data": data})

    def completion(self, prompt, root_prompt):
        # We'll hook into the RLM's execution
        # For now, wrap the completion and emit events
        self.emit("start", {"prompt": root_prompt, "context_size": len(prompt)})

        # Call RLM completion - we'll add hooks
        result = self.rlm.completion(prompt=prompt, root_prompt=root_prompt)

        self.emit("complete", {"answer": str(result)})
        return result


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
        }
        .event { padding: 8px 12px; margin: 4px 0; border-radius: 4px; }
        .event-start { background: #1f6feb; color: white; }
        .event-iteration { background: #8957e5; color: white; }
        .event-python { background: #da3633; color: white; }
        .event-subllm { background: #f78166; color: white; }
        .event-complete { background: #238636; color: white; }
        .event-error { background: #da3633; color: white; }
        .event-info { background: #30363d; }
        .timestamp { color: #8b949e; font-size: 11px; }
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
    
    <button id="runBtn" onclick="runRLM()">Run RLM</button>
    
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
                    content = '🚀 <b>Starting RLM</b><br>Question: ' + data.prompt + '<br>Context: ' + (data.context_size / 1024 / 1024).toFixed(2) + 'MB';
                    break;
                case 'iteration':
                    content = '📝 <b>Iteration ' + data.iteration + '/' + data.total + '</b>';
                    break;
                case 'python':
                    content = '🐍 <b>Python Execution</b><br><code>' + data.code.substring(0, 100) + '...</code>';
                    break;
                case 'subllm':
                    content = '🔄 <b>Sub-LLM Call</b><br>Chunk size: ' + (data.chunk_size / 1024).toFixed(0) + 'KB<br>Depth: ' + data.depth;
                    break;
                case 'complete':
                    content = '✅ <b>Final Answer</b><br>' + data.answer.substring(0, 500) + '...';
                    break;
                case 'error':
                    content = '❌ <b>Error</b><br>' + data.message;
                    break;
                default:
                    content = JSON.stringify(data);
            }
            
            div.innerHTML = '<span class="timestamp">' + time + '</span> ' + content;
            events.appendChild(div);
            events.scrollTop = events.scrollHeight;
        }
        
        async function runRLM() {
            const repoUrl = document.getElementById('repoUrl').value;
            const question = document.getElementById('question').value;
            const btn = document.getElementById('runBtn');
            const eventsDiv = document.getElementById('events');
            
            btn.disabled = true;
            eventsDiv.innerHTML = '';
            
            if (eventSource) {
                eventSource.close();
            }
            
            eventSource = new EventSource('/ask?repo=' + encodeURIComponent(repoUrl) + '&question=' + encodeURIComponent(question));
            
            eventSource.onmessage = function(e) {
                const data = JSON.parse(e.data);
                addEvent(data.type, data.data);
            };
            
            eventSource.onerror = function(e) {
                console.log('Error:', e);
                btn.disabled = false;
                eventSource.close();
            };
            
            // When stream ends
            eventSource.addEventListener('done', function(e) {
                btn.disabled = false;
            });
        }
    </script>
</body>
</html>"""


@app.get("/ask")
async def ask(repo: str, question: str):
    """Stream RLM events via SSE"""

    async def event_generator():
        # Setup
        os.environ["OPENAI_API_KEY"] = os.getenv("NANO_GPT_API_KEY")
        os.environ["OPENAI_BASE_URL"] = os.getenv(
            "NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1"
        )

        # Create event queue
        event_queue = Queue()

        def emit(event_type, data):
            event_queue.put({"type": event_type, "data": data})

        # Emit start event
        emit("start", {"question": question, "repo": repo})

        try:
            # Clone repo
            emit("info", {"message": f"Cloning {repo}..."})
            repo_dir = clone_repo(repo)
            emit("info", {"message": "Reading files..."})
            context = read_files_recursive(repo_dir, max_size_mb=10)

            import shutil

            shutil.rmtree(repo_dir, ignore_errors=True)

            emit(
                "context_ready",
                {"size": len(context), "size_mb": len(context) / 1024 / 1024},
            )

            # Create RLM
            rlm = create_rlm(max_iterations=30, max_depth=3, verbose=False)

            emit("info", {"message": "Running RLM (this may take a while)..."})

            # Run RLM - we'll stream the verbose output
            import io
            import sys

            old_stdout = sys.stdout
            sys.stdout = captured = io.StringIO()

            result = rlm.completion(
                prompt=context,
                root_prompt=f"{question} - Cite your sources with character positions.",
            )

            sys.stdout = old_stdout

            # Parse the verbose output and emit events
            output = captured.getvalue()

            # Extract iteration info
            for line in output.split("\n"):
                if "Iteration" in line:
                    emit("iteration", {"line": line})
                elif "Python" in line or "Executing" in line:
                    emit("python", {"line": line})
                elif "sub" in line.lower() or "llm" in line.lower():
                    emit("subllm", {"line": line})

            # Extract final answer
            answer = str(result)
            emit("complete", {"answer": answer})

        except Exception as e:
            emit("error", {"message": str(e)})

        # Send events from queue
        while True:
            try:
                event = event_queue.get(timeout=1)
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] in ["complete", "error"]:
                    break
            except:
                break

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=3136)
