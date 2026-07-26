import os
import re
import io
import json
import sqlite3
import requests
from flask import Flask, request, jsonify, send_from_directory, send_file
from gtts import gTTS

app = Flask(__name__, static_url_path='', static_folder='.')
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scrb_cases.db')

# ---------------------------------------------------------------------------
# 1. Database setup — SQLite, one row per case, structured fields stored as
#    JSON text for the nested bits (accused / linked / financial), which
#    keeps this readable while still being a real queryable database.
# ---------------------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS cases
                 (id TEXT PRIMARY KEY, district TEXT, station TEXT, date TEXT,
                  crimeType TEXT, status TEXT, summary TEXT, accused TEXT,
                  victims INTEGER, linked TEXT, financial TEXT)''')

    c.execute('SELECT count(*) FROM cases')
    if c.fetchone()[0] == 0:
        sample_cases = [
            ("REC-1001", "Bengaluru Urban", "Whitefield PS", "2026-02-14", "Cyber fraud", "Under investigation",
             "Phishing syndicate targeting salaried professionals via fake bank SMS links.",
             json.dumps([{"name": "Arjun Rao", "age": 34, "prior": 2, "risk": 78},
                         {"name": "Divya Shet", "age": 29, "prior": 0, "risk": 41}]),
             3, json.dumps(["REC-1006"]),
             json.dumps([{"amt": "₹4.2L", "from": "Mule a/c #A211", "to": "Shell entity X", "date": "2026-02-10"}])),
            ("REC-1002", "Mysuru", "Devaraja PS", "2026-01-22", "Chain snatching", "Chargesheeted",
             "Series of chain-snatching incidents targeting pedestrians near market areas.",
             json.dumps([{"name": "Manjunath K", "age": 41, "prior": 5, "risk": 88}]),
             4, json.dumps(["REC-1004"]), json.dumps([])),
            ("REC-1003", "Belagavi", "Tilakwadi PS", "2025-12-30", "Vehicle theft", "Under investigation",
             "Organised vehicle theft ring dismantling stolen two-wheelers for parts resale.",
             json.dumps([{"name": "Suresh Patil", "age": 37, "prior": 3, "risk": 70},
                         {"name": "Iqbal Sheikh", "age": 45, "prior": 6, "risk": 91}]),
             6, json.dumps(["REC-1009"]), json.dumps([])),
            ("REC-1004", "Mysuru", "Vijayanagar PS", "2026-02-02", "Chain snatching", "Under investigation",
             "Repeat modus operandi consistent with REC-1002; same accused identified via CCTV.",
             json.dumps([{"name": "Manjunath K", "age": 41, "prior": 5, "risk": 88}]),
             2, json.dumps(["REC-1002"]), json.dumps([])),
            ("REC-1005", "Mangaluru", "Bunder PS", "2026-03-01", "Narcotics possession", "Chargesheeted",
             "Small-quantity possession case near coastal transit hub.",
             json.dumps([{"name": "Ravi Shetty", "age": 26, "prior": 1, "risk": 55}]),
             0, json.dumps([]), json.dumps([])),
            ("REC-1006", "Bengaluru Urban", "Indiranagar PS", "2026-02-19", "Cyber fraud", "Under investigation",
             "Second cluster of the same phishing syndicate as REC-1001, different victim pool.",
             json.dumps([{"name": "Arjun Rao", "age": 34, "prior": 2, "risk": 78}]),
             5, json.dumps(["REC-1001"]),
             json.dumps([{"amt": "₹2.8L", "from": "Mule a/c #B117", "to": "Shell entity X", "date": "2026-02-18"}])),
            ("REC-1007", "Hubballi-Dharwad", "Vidyanagar PS", "2026-01-08", "Extortion", "Under investigation",
             "Extortion targeting small business owners, threats of repeat visits.",
             json.dumps([{"name": "Basavaraj N", "age": 50, "prior": 8, "risk": 93}]),
             5, json.dumps(["REC-1010"]),
             json.dumps([{"amt": "₹1.1L", "from": "Victim cash deposit", "to": "Assoc. a/c #C044", "date": "2026-01-06"}])),
            ("REC-1008", "Kalaburagi", "Station Bazaar PS", "2026-03-10", "Burglary", "Open — unidentified suspect",
             "Series of residential burglaries during daytime hours in a single locality.",
             json.dumps([]), 7, json.dumps([]), json.dumps([])),
            ("REC-1009", "Belagavi", "Camp PS", "2026-01-15", "Vehicle theft", "Under investigation",
             "Resale network for parts stripped from vehicles reported in REC-1003.",
             json.dumps([{"name": "Iqbal Sheikh", "age": 45, "prior": 6, "risk": 91}]),
             2, json.dumps(["REC-1003"]), json.dumps([])),
            ("REC-1010", "Hubballi-Dharwad", "Gokul Road PS", "2026-01-25", "Extortion", "Chargesheeted",
             "Same extortion network as REC-1007, second collection point identified.",
             json.dumps([{"name": "Basavaraj N", "age": 50, "prior": 8, "risk": 93},
                         {"name": "Ganesh Pujar", "age": 33, "prior": 2, "risk": 60}]),
             3, json.dumps(["REC-1007"]),
             json.dumps([{"amt": "₹0.6L", "from": "Victim cash deposit", "to": "Assoc. a/c #C044", "date": "2026-01-24"}])),
        ]
        c.executemany('INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?)', sample_cases)
        conn.commit()
    conn.close()


def row_to_case(row):
    return {
        "id": row["id"], "district": row["district"], "station": row["station"],
        "date": row["date"], "crimeType": row["crimeType"], "status": row["status"],
        "summary": row["summary"], "accused": json.loads(row["accused"]),
        "victims": row["victims"], "linked": json.loads(row["linked"]),
        "financial": json.loads(row["financial"]),
    }


def all_cases():
    conn = get_conn()
    rows = conn.execute('SELECT * FROM cases').fetchall()
    conn.close()
    return [row_to_case(r) for r in rows]


# ---------------------------------------------------------------------------
# 2. Retrieval — simple keyword-overlap scoring over the database, plus a
#    direct REC-#### id boost. This is what makes /api/chat "grounded"
#    instead of a bare LLM call.
# ---------------------------------------------------------------------------
def retrieve(query, limit=5):
    cases = all_cases()
    q_words = [w for w in re.split(r'\W+', query.lower()) if len(w) > 2]
    id_hits = {m.upper() for m in re.findall(r'REC-\d{4}', query, re.IGNORECASE)}

    scored = []
    for case in cases:
        haystack = ' '.join([
            case['id'], case['district'], case['station'], case['crimeType'],
            case['summary'], case['status'], *[a['name'] for a in case['accused']]
        ]).lower()
        score = sum(1 for w in q_words if w in haystack)
        if case['id'] in id_hits:
            score += 10
        scored.append((score, case))

    scored.sort(key=lambda x: -x[0])
    top = [c for s, c in scored if s > 0][:limit]
    if not top:
        top = [c for _, c in scored[:3]]
    return top


def mask_name(name, role):
    if role in ('Policymaker', 'Analyst'):
        h = sum(ord(ch) for ch in name)
        return f"Subject-{100 + (h * 37) % 900}"
    return name


def record_context(case, role):
    if case['accused']:
        accused_str = "; ".join(
            f"{mask_name(a['name'], role)} (age {a['age']}, prior offences: {a['prior']}, risk score: {a['risk']}/100)"
            for a in case['accused']
        )
    else:
        accused_str = "unidentified"

    if case['financial']:
        fin_str = "; ".join(
            f"{f['amt']} moved from {f['from']} to {f['to']} on {f['date']}" for f in case['financial']
        )
    else:
        fin_str = "none flagged"

    linked_str = ", ".join(case['linked']) if case['linked'] else "none"

    return (f"[{case['id']}] District: {case['district']}, Station: {case['station']}, "
            f"Date: {case['date']}, Crime type: {case['crimeType']}, Status: {case['status']}. "
            f"Summary: {case['summary']} Accused: {accused_str}. Victims: {case['victims']}. "
            f"Linked cases: {linked_str}. Financial flags: {fin_str}.")


def build_system_prompt(role, lang, context_records):
    context_block = "\n".join(record_context(c, role) for c in context_records)
    is_kannada = (lang == "Kannada")
    if is_kannada:
        lang_rule = (
            "Respond ENTIRELY in Kannada, using Kannada (ಕನ್ನಡ) script only. "
            "This applies no matter what language earlier turns in this conversation were in, "
            "and no matter what language the case records below are written in — translate any "
            "facts, names of fields, statuses, or figures you use into Kannada as you write. "
            "Do not mix in English sentences or English field labels. Only case IDs like "
            "[REC-1001] and rupee/number figures may stay in their original form."
        )
    else:
        lang_rule = "Respond in English."
    return f"""You are the SCRB Crime Intelligence Assistant, a natural-language analysis tool for
Karnataka's State Crime Records Bureau, used in a hackathon prototype demo with entirely fictional data.
Current user role: {role}. Investigators and Supervisors get full case detail including accused identifiers.
Analysts and Policymakers should receive aggregated, trend-level insight — identifiers may appear masked
as "Subject-###"; keep it that way, do not invent real names.
{lang_rule}
Only use the case records provided below as ground truth — do not invent case facts. When you reference
a case, cite it inline like [REC-1001]. If the records don't cover the question, say so plainly (in the
language specified above).
Keep answers brief and in the tone of a professional law-enforcement briefing — a few short sentences
or, at most, a short plain-text list. Where relevant, surface patterns (repeat offenders, linked cases,
financial links) rather than just listing every field.

Formatting rules — follow strictly:
- Plain prose only. Do NOT use Markdown formatting of any kind.
- Never use asterisks (*), hashes (#), underscores (_), or bullet/heading symbols.
- If you need a list, write it as short plain-text lines or a comma-separated sentence — no "*" or "-" bullets.
- No bold, no italics, no headers — just plain sentences.

CASE RECORDS:
{context_block}"""


# ---------------------------------------------------------------------------
# 3. LLM call — supports either Anthropic (Claude) or Google (Gemini),
#    whichever API key is present in the environment.
# ---------------------------------------------------------------------------
def call_anthropic(system_prompt, messages, api_key):
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-5",
            "max_tokens": 1000,
            "system": system_prompt,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        },
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "Unknown Anthropic API error."))
    return "".join(block.get("text", "") for block in data.get("content", [])).strip()


GEMINI_MODEL_FALLBACKS = ["gemini-3.6-flash", "gemini-flash-latest", "gemini-3.5-flash-lite"]

def call_gemini(system_prompt, messages, api_key):
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
                for m in messages]
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 1000},
    }

    last_error = None
    for model in GEMINI_MODEL_FALLBACKS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=30)
            data = resp.json()
            if "error" in data:
                last_error = data["error"].get("message", f"Unknown Gemini API error on {model}.")
                continue  # this model is unavailable/deprecated — try the next one
            if "candidates" not in data or not data["candidates"]:
                last_error = f"Empty response from Gemini ({model})."
                continue
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except requests.RequestException as e:
            last_error = str(e)
            continue

    raise RuntimeError(last_error or "All Gemini model fallbacks failed.")


def call_llm(system_prompt, messages):
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if gemini_key:
        return call_gemini(system_prompt, messages, gemini_key)
    if anthropic_key:
        return call_anthropic(system_prompt, messages, anthropic_key)

    raise RuntimeError(
        "[SETUP REQUIRED] No API key found. Set GEMINI_API_KEY as an environment variable "
        "before running app.py, then restart the server."
    )


# ---------------------------------------------------------------------------
# 4. Routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return send_from_directory('.', 'scrb-crime-intelligence-assistant.html')


@app.route('/api/cases', methods=['GET'])
def api_cases():
    return jsonify(all_cases())


@app.route('/api/cases/<case_id>', methods=['GET'])
def api_case_detail(case_id):
    conn = get_conn()
    row = conn.execute('SELECT * FROM cases WHERE id = ?', (case_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Case not found"}), 404
    return jsonify(row_to_case(row))


@app.route('/api/hotspots', methods=['GET'])
def api_hotspots():
    conn = get_conn()
    rows = conn.execute(
        'SELECT district, COUNT(*) as count FROM cases GROUP BY district ORDER BY count DESC'
    ).fetchall()
    conn.close()
    return jsonify([{"district": r["district"], "count": r["count"]} for r in rows])


@app.route('/api/tts', methods=['POST'])
def api_tts():
    # Server-side text-to-speech via gTTS. This exists mainly for Kannada:
    # most Windows/browser setups have no local Kannada voice installed, so
    # the browser's built-in speechSynthesis silently produces nothing.
    # gTTS just needs outbound internet access, not an installed voice.
    data = request.json or {}
    text = data.get("text", "").strip()
    lang = data.get("lang", "en")  # 'kn' for Kannada, 'en' for English

    if not text:
        return jsonify({"error": "text is required"}), 400

    try:
        tts = gTTS(text=text, lang=lang)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return send_file(buf, mimetype="audio/mpeg")
    except Exception as e:
        return jsonify({"error": f"TTS failed: {str(e)}"}), 500


@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json or {}
    message = data.get("message", "").strip()
    role = data.get("role", "Investigator")
    lang = data.get("lang", "English")
    history = data.get("history", [])  # [{role:'user'|'assistant', text: '...'}]

    if not message:
        return jsonify({"error": "message is required"}), 400

    context_records = retrieve(message)
    system_prompt = build_system_prompt(role, lang, context_records)

    messages = [{"role": h["role"], "content": h["text"]} for h in history]
    messages.append({"role": "user", "content": message})

    try:
        answer = call_llm(system_prompt, messages)
    except Exception as e:
        return jsonify({
            "answer": f"⚠️ {str(e)}",
            "citedIds": [],
        }), 200

    cited = sorted(set(re.findall(r'REC-\d{4}', answer)))
    if not cited:
        cited = [c["id"] for c in context_records]

    return jsonify({"answer": answer, "citedIds": cited})


if __name__ == '__main__':
    init_db()
    print(f"Database ready at {DB_PATH}")
    if os.environ.get("GEMINI_API_KEY"):
        print("Using Google Gemini for chat responses.")
    elif os.environ.get("ANTHROPIC_API_KEY"):
        print("Using Anthropic (Claude) for chat responses.")
    else:
        print("WARNING: no GEMINI_API_KEY set — /api/chat will return a setup message.")
    print("Server starting at http://localhost:5000")
    app.run(port=5000, debug=True)
