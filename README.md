# ETF AI Ukis

ETF AI Ukis is a Streamlit assistant for questions about Elektrotehnicki fakultet Univerziteta u Beogradu. The app uses locally generated knowledge files about study programs and employees, then sends the selected context to the UKIS AI chat API.

## Files

- `app_ukisAI.py` - Streamlit chat app for asking ETF-related questions.
- `ETF_scrape_Studiranje.py` - scraper that collects ETF study program and course information.
- `ETF_scrape_Workers.py` - scraper that collects ETF employee information and related subjects.
- `.NewSkills/Studiranje.md` - generated knowledge file used by the app.
- `.NewSkills/Workers.md` - generated knowledge file used by the app.

## Requirements

- Python 3.10 or newer
- Internet access for scraping ETF pages and calling `https://api.ukisai.academy`

Install Python dependencies from `requirements.txt`.

## Setup

Create a virtual environment:

```bash
python -m venv venv
```

Activate it on Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Generate Knowledge Files

Run the scrapers before starting the app:

```bash
python ETF_scrape_Studiranje.py
python ETF_scrape_Workers.py
```

The scripts create the `.NewSkills` folder and write:

- `.NewSkills/Studiranje.json`
- `.NewSkills/Studiranje.md`
- `.NewSkills/Workers.json`
- `.NewSkills/Workers.md`

## Run The App

Start the Streamlit application:

```bash
streamlit run app_ukisAI.py
```

Then open the local Streamlit URL shown in the terminal.

## Notes

- The app answers only from the generated ETF context files.
- If the `.NewSkills` markdown files are missing, run the scrapers again.
- The scrapers depend on the current HTML structure of `www.etf.bg.ac.rs`, so they may need updates if the website changes.
