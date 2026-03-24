"""Real-time dashboard for Solana arbitrage bot."""
from __future__ import annotations

import json
import os
import time
from functools import wraps

from flask import Flask, Response, render_template_string, request
import httpx

app = Flask(__name__)
DASH_USER = os.getenv("DASHBOARD_USER", "admin")
DASH_PASS = os.getenv("DASHBOARD_PASS", "admin")
BOT_HEALTH_URL = "http://localhost:8080/health"


def check_auth(username: str, password: str) -> bool:
    return username == DASH_USER and password == DASH_PASS


def auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Unauthorized", 401,
                {"WWW-Authenticate": 'Basic realm="Login"'},
            )
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
@auth_required
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/stats")
@auth_required
def api_stats():
    try:
        resp = httpx.get(BOT_HEALTH_URL, timeout=5)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}, 502


@app.route("/api/ai-provider", methods=["GET", "POST"])
@auth_required
def ai_provider():
    """Get or set the nightly report AI provider."""
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import detector.nightly_report as nr

        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            provider = data.get("provider", "ollama")
            if provider not in ("ollama", "anthropic"):
                return {"error": "Invalid provider"}, 400
            nr.ai_provider = provider
            return {"ok": True, "ai_provider": provider}
        return {"ai_provider": nr.ai_provider}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/api/stream")
@auth_required
def stream():
    def generate():
        while True:
            try:
                resp = httpx.get(BOT_HEALTH_URL, timeout=5)
                data = resp.text
            except Exception:
                data = json.dumps({"error": "bot unreachable"})
            yield f"data: {data}\n\n"
            time.sleep(2)
    return Response(generate(), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# Inline HTML template
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Solana Arb Bot &mdash; Dashboard</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  :root{
    --bg:#0a0c10;--card:#12151c;--border:#1e2330;
    --green:#14f195;--red:#f44;--yellow:#ffd60a;
    --text:#c9d1d9;--muted:#6b7280;
    --font:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  }
  body{background:var(--bg);color:var(--text);font-family:var(--font);
       min-height:100vh;padding:2rem}

  /* header */
  .header{display:flex;align-items:center;gap:1rem;margin-bottom:2rem;flex-wrap:wrap}
  .header h1{font-size:1.4rem;letter-spacing:.02em}
  .badge{font-size:.75rem;padding:.25rem .6rem;border-radius:999px;font-weight:600;text-transform:uppercase}
  .badge-running{background:rgba(20,241,149,.15);color:var(--green);border:1px solid var(--green)}
  .badge-paused{background:rgba(255,214,10,.15);color:var(--yellow);border:1px solid var(--yellow)}
  .badge-error{background:rgba(255,68,68,.15);color:var(--red);border:1px solid var(--red)}

  /* grid */
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:2rem}
  .card{background:var(--card);border:1px solid var(--border);border-radius:.75rem;padding:1.25rem}
  .card .label{font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:.4rem}
  .card .value{font-size:1.6rem;font-weight:700;color:var(--green)}
  .card .value.negative{color:var(--red)}
  .card .sub{font-size:.7rem;color:var(--muted);margin-top:.25rem}

  /* detail section */
  .detail{background:var(--card);border:1px solid var(--border);border-radius:.75rem;padding:1.25rem}
  .detail h3{font-size:.85rem;color:var(--muted);margin-bottom:.75rem;text-transform:uppercase;letter-spacing:.04em}
  .detail-row{display:flex;justify-content:space-between;padding:.35rem 0;border-bottom:1px solid var(--border);font-size:.85rem}
  .detail-row:last-child{border:none}
  .detail-row .k{color:var(--muted)}

  /* footer */
  .footer{margin-top:2rem;text-align:center;font-size:.7rem;color:var(--muted)}

  /* connection indicator */
  .conn{display:inline-block;width:8px;height:8px;border-radius:50%;margin-left:.5rem;vertical-align:middle}
  .conn-ok{background:var(--green)}
  .conn-lost{background:var(--red)}
</style>
</head>
<body>

<div class="header">
  <h1>Solana Arb Bot</h1>
  <span id="status-badge" class="badge badge-running">loading...</span>
  <span id="conn" class="conn conn-lost" title="SSE connection"></span>
</div>

<div class="grid">
  <div class="card">
    <div class="label">Balance</div>
    <div class="value" id="balance">--</div>
    <div class="sub">SOL</div>
  </div>
  <div class="card">
    <div class="label">Total Trades</div>
    <div class="value" id="trades">--</div>
  </div>
  <div class="card">
    <div class="label">Total Profit</div>
    <div class="value" id="profit">--</div>
    <div class="sub">SOL</div>
  </div>
  <div class="card">
    <div class="label">Uptime</div>
    <div class="value" id="uptime">--</div>
  </div>
  <div class="card">
    <div class="label">Errors</div>
    <div class="value" id="errors">--</div>
  </div>
</div>

<div class="detail">
  <h3>Details</h3>
  <div class="detail-row"><span class="k">Mode</span><span id="d-mode">--</span></div>
  <div class="detail-row"><span class="k">Opportunities seen</span><span id="d-opps">--</span></div>
  <div class="detail-row"><span class="k">Last scan</span><span id="d-scan">--</span></div>
  <div class="detail-row">
    <span class="k">AI Provider (nightly report)</span>
    <span>
      <select id="ai-select" style="background:var(--bg);color:var(--green);border:1px solid var(--border);padding:.25rem .5rem;border-radius:4px;font-family:var(--font);font-size:.8rem;cursor:pointer">
        <option value="ollama">Ollama (local)</option>
        <option value="anthropic">Anthropic (Claude)</option>
      </select>
    </span>
  </div>
</div>

<div class="footer">Auto-refreshing every 2 s via SSE</div>

<script>
function fmtUptime(sec){
  if(sec==null)return"--";
  const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=sec%60;
  return(h?h+"h ":"")+(m?m+"m ":"")+(s+"s");
}
function fmtProfit(v){
  if(v==null)return"--";
  const sign=v>=0?"+":"";
  return sign+v.toFixed(6);
}

const $=id=>document.getElementById(id);
const conn=$("conn");

function update(d){
  if(d.error){
    $("status-badge").className="badge badge-error";
    $("status-badge").textContent="unreachable";
    return;
  }
  // status badge
  const running=d.status==="running";
  $("status-badge").className="badge "+(running?"badge-running":"badge-paused");
  $("status-badge").textContent=d.status;

  // cards
  $("balance").textContent=(d.balance_sol!=null?d.balance_sol.toFixed(4):"--");
  $("trades").textContent=d.trades_total??"--";

  const profitEl=$("profit");
  profitEl.textContent=fmtProfit(d.profit_total);
  profitEl.className="value"+(d.profit_total<0?" negative":"");

  $("uptime").textContent=fmtUptime(d.uptime_sec);
  $("errors").textContent=d.errors_total??"--";

  // details
  $("d-mode").textContent=d.dry_run?"Dry Run":"Live";
  $("d-opps").textContent=d.opportunities_seen??"--";
  $("d-scan").textContent=d.last_scan_sec_ago!=null?(d.last_scan_sec_ago+"s ago"):"--";
}

// AI provider select
const aiSel=$("ai-select");
fetch("/api/ai-provider").then(r=>r.json()).then(d=>{if(d.ai_provider)aiSel.value=d.ai_provider}).catch(()=>{});
aiSel.onchange=()=>{
  fetch("/api/ai-provider",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider:aiSel.value})})
    .then(r=>r.json()).then(d=>{if(d.ok)aiSel.style.borderColor="var(--green)";setTimeout(()=>aiSel.style.borderColor="var(--border)",1500)})
    .catch(()=>{aiSel.style.borderColor="var(--red)"});
};

// SSE setup with basic-auth credentials baked into the URL
const es=new EventSource("/api/stream");
es.onopen=()=>{conn.className="conn conn-ok"};
es.onerror=()=>{conn.className="conn conn-lost"};
es.onmessage=e=>{
  conn.className="conn conn-ok";
  try{update(JSON.parse(e.data))}catch(_){}
};
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
