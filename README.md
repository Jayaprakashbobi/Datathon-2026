# SCRB Crime Intelligence Assistant

A prototype natural-language assistant over a small demo crime-case dataset,
built for Karnataka's State Crime Records Bureau (fictional data). A Flask
backend serves the case database and a grounded chat endpoint; a single-file
HTML/JS frontend provides the chat UI, voice input/output, a case ledger, and
a "Popular Cases" dropdown (History / Unsolved / Solved).

## Features

- Chat grounded in a local SQLite case database (retrieval by keyword +
  case-ID matching before every LLM call)
- Role-based detail level (Investigator / Supervisor see full identifiers;
  Analyst / Policymaker see masked "Subject-###" identifiers)
- English and Kannada (ಕನ್ನಡ) response language, plus matching voice
  input/output. Kannada speech output uses server-side gTTS (needs internet
  access from the machine running `app.py`), since most browsers/OSes don't
  ship a local Kannada voice; English speech uses the browser's built-in voice.
- Voice input (mic) and voice output (text-to-speech), with a Stop button to
  halt playback/listening at any time
- Case Ledger panel listing every case with a risk indicator
- Popular Cases dropdown grouped into History (recently viewed), Unsolved,
  and Solved
- Transcript export (opens a printable summary of the conversation)
- Works with either Google Gemini or Anthropic Claude as the LLM backend

## Project structure

```
.
├── app.py                                   # Flask backend + SQLite database
├── scrb-crime-intelligence-assistant.html   # Frontend (served at "/")
├── requirements.txt
└── scrb_cases.db                            # Created automatically on first run
```

## Requirements

- Python 3.9+
- A Gemini or Anthropic API key (chat won't work without one — see below)

## Setup

1. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Set an API key** (only one is required — Gemini is checked first, then
   Anthropic)

   macOS / Linux:
   ```bash
   export GEMINI_API_KEY="your-key-here"
   # or
   export ANTHROPIC_API_KEY="your-key-here"
   ```

   Windows PowerShell:
   ```powershell
   $env:GEMINI_API_KEY = "your-key-here"
   ```

   Windows cmd.exe:
   ```cmd
   set GEMINI_API_KEY=your-key-here
   ```

   > Environment variables only apply to the terminal session they're set
   > in. To persist them across sessions on Windows, use `setx
   > GEMINI_API_KEY "your-key-here"` and open a new terminal.

3. **Run the server**

   ```bash
   python app.py
   ```

   On first run this creates `scrb_cases.db` next to `app.py` and seeds it
   with 10 sample cases.

4. **Open the app**

   Visit `http://localhost:5000` in your browser.

If no API key is set, the app still runs and the case database/UI still
work — `/api/chat` will just return a "[SETUP REQUIRED]" message until a
key is configured.

## API endpoints

| Method | Path                     | Description                                   |
|--------|--------------------------|------------------------------------------------|
| GET    | `/`                      | Serves the frontend HTML                        |
| GET    | `/api/cases`             | Returns all cases as JSON                       |
| GET    | `/api/cases/<case_id>`   | Returns a single case by ID (e.g. `REC-1001`)   |
| GET    | `/api/hotspots`          | Returns case counts grouped by district         |
| POST   | `/api/chat`              | Sends a chat message, returns a grounded answer |
| POST   | `/api/tts`               | Converts text to speech (used for Kannada audio) |

`POST /api/chat` body:
```json
{
  "message": "Are there any cases connected to REC-1007?",
  "role": "Investigator",
  "lang": "English",
  "history": [{"role": "user", "text": "..."}, {"role": "assistant", "text": "..."}]
}
```

## Notes

- This is a hackathon/demo prototype. All case data, names, and figures are
  fictional and generated for demonstration purposes only.
- Debug mode is enabled in `app.py` (`app.run(debug=True)`), which auto-reloads
  on file changes — don't run it this way in production.
- The database resets to the 10 seed cases only if `scrb_cases.db` doesn't
  already exist; delete that file to reset the sample data.
