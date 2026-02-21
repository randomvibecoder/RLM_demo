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

    def event_callback(event_type, pct=None, msg=None, data=None):
        queue.put({"type": event_type, "pct": pct, "msg": msg, "data": data})

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

        # Send the full prompt to the UI
        from github_qa import CUSTOM_PROMPT

        full_prompt = f"System: {CUSTOM_PROMPT}\n\nUser: {question}"
        event_callback(
            "prompt", None, "Full prompt:", data={"prompt": full_prompt[:2000]}
        )

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

        # Get full result info
        try:
            result_dict = result.to_dict()
            answer = str(result)
            # Send iterations info
            if "iterations" in result_dict:
                event_callback(
                    "iterations",
                    None,
                    f"RLM iterations: {len(result_dict.get('iterations', []))}",
                    data={"iterations": result_dict.get("iterations", [])},
                )
        except:
            answer = str(result)

        jobs[job_id]["status"] = "done"
        queue.put({"type": "done", "answer": answer})

    except Exception as e:
        jobs[job_id]["status"] = "error"
        queue.put({"type": "error", "msg": str(e)})


HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>RLM GitHub QA</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0e14;
            --bg-secondary: #131920;
            --bg-tertiary: #1a2129;
            --accent: #00d9ff;
            --accent-dim: #00d9ff33;
            --text-primary: #e6edf3;
            --text-secondary: #8b949e;
            --border: #30363d;
            --success: #3fb950;
            --error: #f85149;
            --warning: #d29922;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            background-image: 
                radial-gradient(ellipse at top, #00d9ff08 0%, transparent 50%),
                radial-gradient(ellipse at bottom right, #3fb95005 0%, transparent 50%);
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
            padding: 40px 20px;
        }
        
        header {
            text-align: center;
            margin-bottom: 40px;
        }
        
        .logo {
            font-size: 48px;
            margin-bottom: 8px;
            animation: float 3s ease-in-out infinite;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-8px); }
        }
        
        h1 {
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(135deg, var(--text-primary) 0%, var(--accent) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
        }
        
        .subtitle {
            color: var(--text-secondary);
            font-size: 14px;
        }
        
        .card {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.2);
        }
        
        .input-group {
            margin-bottom: 16px;
        }
        
        .input-group label {
            display: block;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-secondary);
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        input, textarea {
            width: 100%;
            padding: 14px 16px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            border-radius: 10px;
            color: var(--text-primary);
            font-family: 'JetBrains Mono', monospace;
            font-size: 14px;
            transition: all 0.2s;
        }
        
        input:focus, textarea:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px var(--accent-dim);
        }
        
        textarea {
            min-height: 80px;
            resize: vertical;
        }
        
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            padding: 14px 32px;
            background: linear-gradient(135deg, var(--accent) 0%, #00a8cc 100%);
            color: var(--bg-primary);
            border: none;
            border-radius: 10px;
            font-family: 'Inter', sans-serif;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            width: 100%;
        }
        
        .btn:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px var(--accent-dim);
        }
        
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        #progress-container {
            display: none;
            margin-top: 20px;
        }
        
        .progress-bar {
            height: 8px;
            background: var(--bg-tertiary);
            border-radius: 4px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--accent), var(--success));
            width: 0%;
            transition: width 0.3s ease-out;
            border-radius: 4px;
        }
        
        .progress-text {
            font-size: 13px;
            color: var(--text-secondary);
            margin-top: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .spinner {
            width: 14px;
            height: 14px;
            border: 2px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        
        @keyframes spin { to { transform: rotate(360deg); } }
        
        #log {
            margin-top: 24px;
        }
        
        .log-entry {
            padding: 12px 16px;
            margin-bottom: 8px;
            border-radius: 8px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
            line-height: 1.5;
            animation: slideIn 0.3s ease-out;
        }
        
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(-8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .log-start { background: #1f6feb22; border-left: 3px solid #1f6feb; color: #58a6ff; }
        .log-info { background: var(--bg-tertiary); border-left: 3px solid var(--border); }
        .log-iter { background: #8957e522; border-left: 3px solid #8957e5; }
        .log-done { background: #23863622; border-left: 3px solid var(--success); }
        .log-error { background: #da363322; border-left: 3px solid var(--error); }
        .log-prompt { background: #00d9ff11; border-left: 3px solid var(--accent); }
        .log-iterations { background: #8957e522; border-left: 3px solid #8957e5; }
        
        .answer-box {
            background: linear-gradient(135deg, #23863611 0%, #00d9ff08 100%);
            border: 1px solid var(--success);
            border-radius: 12px;
            padding: 20px;
            margin-top: 12px;
            white-space: pre-wrap;
            line-height: 1.7;
            color: var(--text-primary);
            max-height: 400px;
            overflow-y: auto;
        }
        
        .prompt-box {
            background: var(--bg-tertiary);
            border: 1px solid var(--accent);
            border-radius: 8px;
            padding: 16px;
            margin-top: 8px;
            font-size: 12px;
            white-space: pre-wrap;
            max-height: 300px;
            overflow-y: auto;
            color: var(--text-secondary);
        }
        
        .iteration-box {
            background: #8957e511;
            border: 1px solid #8957e5;
            border-radius: 8px;
            padding: 16px;
            margin-top: 8px;
            max-height: 300px;
            overflow-y: auto;
        }
        
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            background: var(--accent-dim);
            border-radius: 20px;
            font-size: 12px;
            color: var(--accent);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">🧠</div>
            <h1>RLM GitHub QA</h1>
            <p class="subtitle">Ask questions about any GitHub repository using Recursive Language Models</p>
        </header>
        
        <div class="card">
            <div class="input-group">
                <label>Repository URL</label>
                <input id="repo" type="text" value="https://github.com/torvalds/linux" placeholder="https://github.com/owner/repo">
            </div>
            <div class="input-group">
                <label>Your Question</label>
                <textarea id="q" placeholder="How are drivers loaded in this codebase?">How are drivers loaded?</textarea>
            </div>
            <button id="runBtn" class="btn" onclick="run()">
                <span>✨</span> Ask Question
            </button>
            
            <div id="progress-container">
                <div class="progress-bar"><div id="progress-fill" class="progress-fill"></div></div>
                <div class="progress-text">
                    <div class="spinner"></div>
                    <span id="progress-text-content">Initializing...</span>
                </div>
            </div>
        </div>
        
        <div id="log"></div>
    </div>
    
    <script>
    function log(msg, type='info', data=null) {
        const d = document.getElementById('log');
        const entry = document.createElement('div');
        entry.className = 'log-entry log-' + type;
        
        if (type === 'done' && msg.length > 100) {
            entry.innerHTML = '<strong>✅ Answer:</strong><div class="answer-box">' + msg + '</div>';
        } else if (type === 'prompt' && data && data.prompt) {
            entry.innerHTML = '<strong>📋 Full Prompt to Kappa:</strong><div class="prompt-box">' + data.prompt + '</div>';
        } else if (type === 'iterations' && data && data.iterations) {
            let iterHtml = '<strong>🔄 RLM Iterations (' + data.iterations.length + '):</strong><div class="iteration-box">';
            data.iterations.forEach((iter, i) => {
                iterHtml += '<div style="margin-top:12px;padding-top:12px;border-top:1px solid #8957e555;">';
                iterHtml += '<strong>Iteration ' + (i+1) + ':</strong><br>';
                if (iter.response) iterHtml += '<pre style="white-space:pre-wrap;max-height:150px;overflow-y:auto;">' + iter.response.substring(0, 1000) + '</pre>';
                iterHtml += '</div>';
            });
            iterHtml += '</div>';
            entry.innerHTML = iterHtml;
        } else {
            entry.textContent = msg;
        }
        
        d.appendChild(entry);
        d.scrollTop = d.scrollHeight;
    }
    
    function setProgress(pct, text) {
        const container = document.getElementById('progress-container');
        const fill = document.getElementById('progress-fill');
        const txt = document.getElementById('progress-text-content');
        container.style.display = 'block';
        if (pct !== null) fill.style.width = pct + '%';
        if (text) txt.textContent = text;
    }
    
    function run() {
        document.getElementById('runBtn').disabled = true;
        document.getElementById('log').innerHTML = '';
        document.getElementById('progress-container').style.display = 'none';
        document.getElementById('progress-fill').style.width = '0%';
        log('🚀 Starting analysis...', 'start');
        setProgress(0, 'Initializing...');
        
        const url = '/stream?repo=' + encodeURIComponent(document.getElementById('repo').value) + 
              '&q=' + encodeURIComponent(document.getElementById('q').value);
        
        const es = new EventSource(url);
        
        es.onmessage = function(e) {
            try {
                const d = JSON.parse(e.data);
                if (d.type === 'start') log('🚀 ' + d.msg, 'start');
                else if (d.type === 'info') log('ℹ️ ' + (d.msg || ''), 'info');
                else if (d.type === 'progress') setProgress(d.pct, d.msg);
                else if (d.type === 'heartbeat') setProgress(null, d.msg);
                else if (d.type === 'prompt') log(d.msg, 'prompt', d.data);
                else if (d.type === 'iterations') log(d.msg, 'iterations', d.data);
                else if (d.type === 'iter') log('📝 Iteration ' + d.n, 'iter');
                else if (d.type === 'done') {
                    document.getElementById('progress-container').style.display = 'none';
                    log('✅ Analysis Complete!', 'done');
                    log(d.answer.substring(0, 5000), 'done');
                    document.getElementById('runBtn').disabled = false;
                    es.close();
                }
                else if (d.type === 'error') {
                    document.getElementById('progress-container').style.display = 'none';
                    log('❌ Error: ' + d.msg, 'error');
                    document.getElementById('runBtn').disabled = false;
                    es.close();
                }
            } catch(err) {
                log('Error: ' + e.data, 'error');
            }
        };
        
        es.onerror = function() {
            log('❌ Connection closed', 'error');
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
