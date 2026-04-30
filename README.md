# ETF AI Assistant

ETF AI Assistant is a Streamlit chatbot for information about the University of Belgrade School of Electrical Engineering (ETF). It answers from local markdown files in `.NewSkills` and is designed to stay focused on faculty-related questions.

## Data Sources

The assistant uses these local files:

- `.NewSkills/Studiranje.md` - study programs, modules, years, semesters, and courses.
- `.NewSkills/Workers.md` - ETF employees, positions, departments, contacts, and subjects.

## Features

- Streamlit chat interface.
- Recommended prompt buttons.
- Local retrieval over the markdown files before calling the AI model.
- Faculty-only guardrails.
- Provider selection through `.env`.
- Supports Gemini and Cursor API-key based configuration.

## Setup

Create and activate a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

## Environment Variables

Copy `.env.example` to `.env` if needed:

```powershell
Copy-Item .env.example .env
```

Use Gemini:

```env
AI_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash-lite
```

Use Cursor:

```env
AI_PROVIDER=cursor
CURSOR_API_KEY=your_cursor_api_key
CURSOR_MODEL=gpt-5.5-medium
```

Do not upload `.env` to GitHub. This project already has `.env` patterns in `.gitignore`.

## Run

Start the app:

```powershell
streamlit run app.py
```

Then open the local URL shown by Streamlit.

## Recommended Prompts

- `Ko je profesor Mladen Koprivica?`
- `Koji predmeti su na drugoj godini smer Telekomunikacije?`
- `Ko predaje Osnove Elektrotehnike 2?`

## Notes

- If the assistant does not find relevant context in `.NewSkills`, it should answer that the information is not available in the ETF data.
- Keep `.NewSkills` files updated when faculty data changes.
