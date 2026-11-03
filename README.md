# SQL Query Doctor

Full documentation: [DOCUMENTATION.md](DOCUMENTATION.md).

Upload a SQL Server execution plan (.sqlplan or .xml). The app draws the plan as an interactive graph, flags common problems with a rule engine, and (optionally) explains them in plain English using the Gemini API free tier.

## Run on Windows
```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 and click **Try a sample plan**.

## Turn on AI explanations (optional, free tier)
Create a key in Google AI Studio and put it in a `.env` file next to `ai.py`:
```
GEMINI_API_KEY=your_key_here
```
The app reads `.env` on startup (`.env` is gitignored). Optionally add `GEMINI_MODEL` to override the default model. The free tier allows only a handful of requests per model per day, so when one model's quota runs out the app falls back to another flash model automatically. Never commit your key.

## Get your own plans
In SSMS, run a query with Include Actual Execution Plan, right-click the plan, and choose Save Execution Plan As.

## Layout
- `plan_parser.py` ShowPlan XML to an operator tree with cost shares
- `rules.py` rule engine (scans, key lookups, warnings, bad estimates, missing indexes)
- `ai.py` optional Gemini explanation with caching
- `app.py` Flask API and static UI (`static/index.html`)

## Not included yet
Benchmark mode, automated tests, and deployment config from the documentation.
