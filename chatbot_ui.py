"""
Evidence Chatbot - Climate Resilience Fund
===========================================
A local RAG chatbot that answers questions about field notes
with verifiable citations. No API key or internet needed.

HOW TO RUN:   python chatbot_ui.py
THEN OPEN:    http://127.0.0.1:5000  in your browser
TO STOP:      Press Ctrl+C in the terminal

REQUIRES:     pip install flask
"""

# -- Imports -------------------------------------------------------
import os, csv, re, webbrowser, threading
from collections import defaultdict
from flask import Flask, request, jsonify

DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)

# -- 1. Load data --------------------------------------------------

# Read all 90 field note text files into a dictionary
NOTES = {}
for f in sorted(os.listdir(os.path.join(DIR, "field_notes"))):
    if f.endswith(".txt"):
        with open(os.path.join(DIR, "field_notes", f), encoding="utf-8") as fh:
            NOTES[f] = fh.read()

# Read the index CSV (tells us which district/risk each note belongs to)
with open(os.path.join(DIR, "field_notes_index.csv"), encoding="utf-8") as fh:
    INDEX = list(csv.DictReader(fh))

# Calculate top-10 funded districts from project history
_funding = defaultdict(float)
with open(os.path.join(DIR, "project_history.csv"), encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        dc = row["district_code"].strip().upper()
        if not dc.startswith("D-"):
            dc = "D-" + dc.lstrip("D").lstrip("-").zfill(3)
        try:
            _funding[dc] += float(row["cost_usd"])
        except ValueError:
            pass
TOP10 = sorted(_funding.items(), key=lambda x: -x[1])[:10]

print(f"Loaded {len(NOTES)} field notes. Ready!")

# -- 2. Search: score & rank notes against a question -------------

STOP = {
    "the","a","an","is","are","was","were","in","on","at","to","for",
    "of","and","or","that","this","what","which","how","why","who",
    "with","from","by","it","its","be","has","have","had","do","does",
    "did","not","no","but","if","can","will","about","there","their",
    "they","them","so","as","up","out","also","more","very","any",
    "all","some","into","listed","key","observation","includes",
    "estimated","schedule","impact","field","note",
}

def search(question, top_k=5):
    """
    Score every note against the question and return top matches.

    Scoring:
      +100  if the user names a specific file (e.g. field_note_028.txt)
      +50   if the user mentions a district code the note belongs to
      +1    for each keyword found in the note text
      +3    if a keyword matches the note's risk category
    """
    words = [w for w in re.findall(r"[a-z0-9_]+", question.lower())
             if w not in STOP and len(w) > 1]
    dists = set(f"D-{int(m):03d}" for m in re.findall(r"[Dd]-?0*(\d{1,3})", question))
    files = set(re.findall(r"field_note_\d+\.txt", question.lower()))
    idx_map = {r["file"]: r for r in INDEX}

    scored = []
    for fname, txt in NOTES.items():
        score, low = 0, txt.lower()
        row = idx_map.get(fname, {})
        if fname.lower() in files:
            score += 100
        for d in dists:
            if row.get("district_code") == d:
                score += 50
            if row.get("district_id") == d.replace("-", ""):
                score += 50
        for w in words:
            if w in low:
                score += 1
            if w in row.get("primary_risk", "").lower():
                score += 3
        if score > 0:
            scored.append((fname, txt, score))
    scored.sort(key=lambda x: -x[2])
    return scored[:top_k]

# -- 3. Answer: build a cited HTML response ------------------------

def answer(question):
    """Search notes, parse each hit, and build HTML cards with citations."""
    hits = search(question)
    if not hits:
        return "No relevant field notes found.", []

    html_parts = []

    for fname, txt, _ in hits:
        # Parse the note with simple regex
        get = lambda pat: (re.search(pat, txt).group(1).strip()
                           if re.search(pat, txt) else "")
        district  = get(r"District:\s*(.+)")
        date      = get(r"Field Note \| (\d{4}-\d{2}-\d{2})")
        partner   = get(r"Partner:\s*(.+)")
        severity  = get(r"Severity rating \(1.5\):\s*(\d)")
        context   = get(r"Context note:\s*(.+)")

        def bullets(header):
            m = re.search(header + r":\n((?:- .+\n?)+)", txt)
            if not m:
                return []
            return [l.strip().lstrip("- ").strip()
                    for l in m.group(1).strip().split("\n") if l.strip()]

        observations = bullets("Key observations")
        mitigations  = bullets("Mitigation actions proposed")

        # Build card
        card = (f'<div class="card">'
                f'<div class="card-head">{fname} &mdash; {district} ({date})</div>')

        if partner:
            card += f'<p><b>Partner:</b> {partner}</p>'
            card += f'<div class="cite">[{fname}: "Partner: {partner}"]</div>'

        if severity:
            card += f'<p><b>Severity:</b> {severity}/5</p>'
            card += f'<div class="cite">[{fname}: "Severity rating (1-5): {severity}"]</div>'

        if context:
            card += f'<p><b>Context:</b> {context}</p>'
            card += f'<div class="cite">[{fname}: "{context}"]</div>'

        for obs in observations:
            label = "Budget" if obs.lower().startswith("budget note") else "Observation"
            card += f'<p><b>{label}:</b> {obs}</p>'
            card += f'<div class="cite">[{fname}: "{obs}"]</div>'

        for mit in mitigations:
            card += f'<p><b>Mitigation:</b> {mit}</p>'
            card += f'<div class="cite">[{fname}: "{mit}"]</div>'

        card += '</div>'
        html_parts.append(card)

    return "".join(html_parts), [f for f, _, _ in hits]

# -- 4. HTML page (self-contained, no templates needed) ------------

PAGE = r"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Evidence Chatbot</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Segoe UI,sans-serif;background:#f5f5f5;height:100vh;display:flex;flex-direction:column}
header{background:#1a3a5c;color:#fff;padding:14px 24px}
header h1{font-size:18px;font-weight:600}
header p{font-size:12px;opacity:.75;margin-top:2px}

.wrap{display:flex;flex:1;overflow:hidden}

/* sidebar */
.side{width:280px;background:#fff;border-right:1px solid #ddd;padding:16px;overflow-y:auto}
.side h3{font-size:12px;text-transform:uppercase;color:#888;margin:12px 0 8px}
.side button{display:block;width:100%;text-align:left;padding:9px 10px;margin-bottom:4px;
  background:#f8f9fa;border:1px solid #eee;border-radius:6px;font-size:13px;cursor:pointer}
.side button:hover{background:#e3f0fd;border-color:#90caf9}
.dist{display:flex;justify-content:space-between}
.dist b{color:#1a3a5c}
.dist span{color:#999;font-size:12px}

/* chat area */
.chat{flex:1;display:flex;flex-direction:column;overflow:hidden}
#msgs{flex:1;overflow-y:auto;padding:20px 24px}

.bubble{max-width:88%;margin-bottom:16px;animation:pop .25s ease}
@keyframes pop{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.bubble.user{margin-left:auto;background:#1a3a5c;color:#fff;padding:10px 16px;border-radius:16px 16px 4px 16px;font-size:14px}
.bubble.bot{background:#fff;padding:16px;border-radius:4px 16px 16px 16px;border:1px solid #e0e0e0}

.card{background:#f8fafe;border-left:3px solid #1a3a5c;border-radius:0 6px 6px 0;padding:10px 12px;margin-bottom:12px}
.card-head{font-weight:700;color:#1a3a5c;margin-bottom:6px;font-size:14px}
.card p{font-size:13px;margin:4px 0;color:#333}
.cite{font-size:11px;color:#1a3a5c;background:#e3edf7;padding:2px 7px;border-radius:4px;
  display:inline-block;margin-bottom:6px;font-family:Consolas,monospace;word-break:break-word}

.sources{margin-top:8px;font-size:11px;color:#999}
.sources span{background:#f0f0f0;padding:1px 7px;border-radius:8px;margin-right:3px;font-family:monospace}

.welcome{text-align:center;color:#aaa;margin-top:60px}
.welcome h2{font-size:20px;color:#666;margin:10px 0 6px}

/* input bar */
.bar{display:flex;gap:8px;padding:12px 24px;background:#fff;border-top:1px solid #ddd}
.bar input{flex:1;padding:10px 16px;border:2px solid #ddd;border-radius:20px;font-size:14px;outline:none}
.bar input:focus{border-color:#1a3a5c}
.bar button{padding:10px 24px;background:#1a3a5c;color:#fff;border:none;border-radius:20px;
  font-size:14px;font-weight:600;cursor:pointer}
.bar button:hover{background:#254d75}
</style></head><body>

<header>
  <h1>Climate Resilience Fund &mdash; Evidence Chatbot</h1>
  <p>Every answer cites the source file + quoted snippet so you can verify claims.</p>
</header>

<div class="wrap">
  <div class="side">
    <h3>Top Funded Districts</h3>
    DISTRICT_BUTTONS
    <h3>Example Questions</h3>
    <button onclick="ask(this.textContent)">Why is District D010 operationally risky?</button>
    <button onclick="ask(this.textContent)">What risks are documented for D097?</button>
    <button onclick="ask(this.textContent)">What contractor issues affect D096?</button>
    <button onclick="ask(this.textContent)">Which partner is in field_note_009.txt?</button>
    <button onclick="ask(this.textContent)">What budget pressure exists for D088?</button>
  </div>

  <div class="chat">
    <div id="msgs">
      <div class="welcome" id="welcome">
        <h2>Ask a question about field notes</h2>
        <p>Click a district or example, or type your own question below.</p>
      </div>
    </div>
    <div class="bar">
      <input id="q" placeholder="Type a question..." onkeydown="if(event.key==='Enter')send()">
      <button onclick="send()">Ask</button>
    </div>
  </div>
</div>

<script>
const msgs=document.getElementById('msgs'), inp=document.getElementById('q');

function ask(t){ inp.value=t; send(); }

function add(html,cls){
  let w=document.getElementById('welcome'); if(w) w.remove();
  let d=document.createElement('div'); d.className='bubble '+cls; d.innerHTML=html;
  msgs.appendChild(d); msgs.scrollTop=msgs.scrollHeight;
}

async function send(){
  let q=inp.value.trim(); if(!q) return;
  add(q,'user'); inp.value='';
  add('<i style="color:#999">Searching...</i>','bot');
  try{
    let r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})});
    let d=await r.json(); msgs.removeChild(msgs.lastChild);
    let h=d.answer;
    if(d.files_used&&d.files_used.length){
      h+='<div class="sources">Sources: ';
      d.files_used.forEach(f=>{h+='<span>'+f+'</span>';}); h+='</div>';
    }
    add(h,'bot');
  }catch(e){ msgs.removeChild(msgs.lastChild); add('Something went wrong.','bot'); }
  inp.focus();
}
</script></body></html>"""

# -- 5. Flask routes -----------------------------------------------

@app.route("/")
def home():
    btns = ""
    for dc, amt in TOP10:
        btns += (f'<button onclick="ask(\'What risks are documented for {dc}?\')">'
                 f'<div class="dist"><b>{dc}</b><span>USD {amt:,.0f}</span></div></button>\n')
    return PAGE.replace("DISTRICT_BUTTONS", btns)

@app.route("/ask", methods=["POST"])
def ask_route():
    q = request.get_json().get("question", "").strip()
    if not q:
        return jsonify(answer="Please type a question.", files_used=[])
    ans, files = answer(q)
    return jsonify(answer=ans, files_used=files)

# -- 6. Start ------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Chatbot running at: http://127.0.0.1:{port}")
    print(f"  Press Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=port, debug=False)
