# Scalable Flask Web UI for RLM with proper async job queue
import os
import time
import uuid
import threading
from queue import Queue, Empty
from flask import Flask, request, Response
import json

from github_qa import create_rlm, clone_repo, read_files_recursive
from dotenv import load_dotenv
import shutil

load_dotenv()

app = Flask(__name__)

jobs = {}
jobs_lock = threading.Lock()
thread_pool = []  # Track running threads


def run_rlm_job(job_id, repo, question):
    """Run RLM - runs in thread, pushes events to queue"""
    queue = jobs[job_id]["queue"]

    def event_callback(event_type, pct=None, msg=None):
        queue.put({"type": event_type, "pct": pct, "msg": msg})

    try:
        os.environ["OPENAI_API_KEY"] = os.getenv("NANO_GPT_API_KEY") or ""
        os.environ["OPENAI_BASE_URL"] = (
            os.getenv("NANO_GPT_BASE_URL", "https://nano-gpt.com/api/v1")
            or "https://nano-gpt.com/api/v1"
        )

        # Clone with progress
        event_callback("info", 0, "Starting clone...")

        def progress_callback(stage, pct, msg):
            event_callback("progress", pct, msg)

        repo_dir = clone_repo(repo, progress_callback=progress_callback)

        # Read files with progress
        event_callback("progress", 0, "Counting files...")
        context = read_files_recursive(
            repo_dir, max_size_mb=10, progress_callback=progress_callback
        )
        shutil.rmtree(repo_dir, ignore_errors=True)

        event_callback(
            "progress", 100, f"Context loaded: {len(context) / 1024 / 1024:.1f} MB"
        )

        rlm = create_rlm(max_iterations=3, max_depth=1, verbose=False)

        # Start heartbeat for RLM
        phrases = [
            "🤔 Thinking",
            "💭 Still working",
            "🔄 Processing",
            "⏳ Almost there",
        ]

        def heartbeat():
            for i in range(100):
                time.sleep(3)
                if jobs.get(job_id, {}).get("status") == "done":
                    break
                phrase = phrases[i % len(phrases)]
                event_callback("heartbeat", None, f"{phrase}... ({i * 3}s)")

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()

        event_callback("info", None, "Running RLM...")

        result = rlm.completion(prompt=context, root_prompt=question)

        jobs[job_id]["status"] = "done"
        queue.put({"type": "done", "answer": str(result)})

    except Exception as e:
        jobs[job_id]["status"] = "error"
        queue.put({"type": "error", "msg": str(e)})


HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>RLM GitHub QA</title>
    <style>
        body { font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 20px; max-width: 900px; margin: 0 auto; }
        h1 { color: #58a6ff; }
        input, textarea { width: 100%; padding: 10px; background: #161b22; border: 1px solid #30363d; color: white; margin-bottom: 10px; }
        textarea { height: 50px; }
        button { background: #238636; color: white; border: none; padding: 10px 20px; cursor: pointer; }
        button:disabled { background: #333; }
        #log { background: #161b22; padding: 15px; margin-top: 20px; min-height: 400px; max-height: 70vh; overflow-y: auto; white-space: pre-wrap; border-radius: 8px; }
        .msg { padding: 4px 8px; margin: 2px 0; border-radius: 4px; }
        .start { background: #1f6feb; color: white; }
        .info { background: #30363d; }
        .iter { background: #8957e5; color: white; }
        .done { background: #238636; color: white; }
        .err { background: #da3633; color: white; }
        .heartbeat { background: #1f6feb; color: white; }
        
        #progress-container { display: none; margin-top: 10px; }
        .progress-bar { height: 6px; background: #30363d; border-radius: 3px; overflow: hidden; }
        .progress-fill { height: 100%; background: linear-gradient(90deg, #238636, #2ea043); width: 0%; transition: width 0.3s; }
        .progress-text { font-size: 12px; color: #8b949e; margin-top: 4px; }
        
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #fff; border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; margin-right: 6px; vertical-align: middle; }
    </style>
</head>
<body>
    <h1>RLM GitHub QA</h1>
    <input id="repo" value="https://github.com/torvalds/linux">
    <textarea id="q">How are drivers loaded?</textarea>
    <button id="runBtn" onclick="run()">Run RLM</button>
    <div id="progress-container">
        <div class="progress-bar"><div id="progress-fill" class="progress-fill"></div></div>
        <div id="progress-text" class="progress-text"></div>
    </div>
    <div id="log"></div>
    <script>
    let heartbeatTimeout = null;
    
    function log(msg, type='info') {
        const d = document.getElementById('log');
        d.innerHTML += '<div class="msg ' + type + '">' + msg + '</div>';
        d.scrollTop = d.scrollHeight;
    }
    
    function setProgress(pct, text) {
        const container = document.getElementById('progress-container');
        const fill = document.getElementById('progress-fill');
        const txt = document.getElementById('progress-text');
        container.style.display = 'block';
        if (pct !== null) fill.style.width = pct + '%';
        if (text) txt.textContent = text;
    }
    
    function run() {
        document.getElementById('runBtn').disabled = true;
        document.getElementById('log').innerHTML = '';
        document.getElementById('progress-container').style.display = 'none';
        document.getElementById('progress-fill').style.width = '0%';
        log('🚀 Starting...', 'start');
        setProgress(0, 'Initializing...');
        
        const url = '/stream?repo=' + encodeURIComponent(document.getElementById('repo').value) + 
              '&q=' + encodeURIComponent(document.getElementById('q').value);
        
        const es = new EventSource(url);
        
        es.onmessage = function(e) {
            try {
                const d = JSON.parse(e.data);
                if (d.type === 'start') log('🚀 ' + d.msg, 'start');
                else if (d.type === 'info') log('ℹ️ ' + (d.msg || ''), 'info');
                else if (d.type === 'progress') {
                    setProgress(d.pct, d.msg);
                }
                else if (d.type === 'heartbeat') {
                    setProgress(null, d.msg);
                }
                else if (d.type === 'iter') log('📝 Iteration ' + d.n, 'iter');
                else if (d.type === 'done') {
                    document.getElementById('progress-container').style.display = 'none';
                    log('✅ Done!', 'done');
                    log(d.answer.substring(0, 3000), 'done');
                    document.getElementById('runBtn').disabled = false;
                    es.close();
                }
                else if (d.type === 'error') {
                    document.getElementById('progress-container').style.display = 'none';
                    log('❌ ' + d.msg, 'err');
                    document.getElementById('runBtn').disabled = false;
                    es.close();
                }
            } catch(err) {
                log('Error: ' + e.data);
            }
        };
        
        es.onerror = function() {
            log('Connection closed', 'err');
            document.getElementById('runBtn').disabled = false;
        };
    }
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return HTML


@app.route("/stream")
def stream():
    repo = request.args.get("repo") or ""
    q = request.args.get("q") or ""
    job_id = str(uuid.uuid4())  # Unique job ID

    # Create job with queue
    job_queue = Queue()
    with jobs_lock:
        jobs[job_id] = {"queue": job_queue, "status": "running"}
        thread = threading.Thread(target=run_rlm_job, args=(job_id, repo, q))
        thread.start()

    def generate():
        # Send initial message
        yield f"data: {json.dumps({'type': 'start', 'msg': f'Starting job {job_id[:8]}...'})}\n\n"

        seen_events = set()
        while True:
            try:
                # Non-blocking get with timeout
                event = job_queue.get(timeout=30)

                # Deduplicate
                event_key = f"{event.get('type')}_{event.get('msg', '')[:50]}"
                if event_key in seen_events:
                    continue
                seen_events.add(event_key)

                yield f"data: {json.dumps(event)}\n\n"

                if event.get("type") in ("done", "error"):
                    break

            except Empty:
                # Keepalive - check if job still exists
                with jobs_lock:
                    if job_id not in jobs:
                        break
                yield f"data: {json.dumps({'type': 'info', 'msg': '...'})}\n\n"

        # Cleanup job
        with jobs_lock:
            jobs.pop(job_id, None)

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3136, threaded=True)
