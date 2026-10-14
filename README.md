# Premier League Transfer Value Predictor

Pulls recent Premier League stats from [football-data.org](https://www.football-data.org) with
`requests`, trains a linear regression on goals, assists, minutes, appearances, age, position and
physical form, and serves a Premier League–styled web app. In the app you can look up any player,
or type in your own, and compare what the model thinks they're worth with their market value.

The app shows:

- **Player card**: photo, club crest, position, age, nationality, form badge and injury news
- **Valuation**: model value vs market value, a comparison chart and an undervalued/overpriced verdict
- **Stats strip**: per-season goals, assists, minutes and appearances, plus G+A per 90
- **Value drivers**: how much each feature pushes this player above or below an average player
- **Season by season**: goals and assists as bars, with minutes as a line
- **Scouting lab**: plug in any player with sliders for stats, position and form (fit / weak / injured) and get a live valuation
- **Model vs market**: a scatter of every player against the model = market line. Click a dot to open that player.
- **The table**: biggest bargains, most overpriced and most valuable players
- **Model card**: cross-validated accuracy, learned effect sizes and caveats

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # then paste your free football-data.org key into .env
python -m predictor all         # fetch the last 3 completed seasons, build the dataset, train
python app.py                   # open http://127.0.0.1:5000
```

Before any data is fetched, the app shows a setup screen with these steps.

### Commands

| Command | What it does |
| --- | --- |
| `python -m predictor fetch` | Downloads stats into `data/raw/`: football-data.org scorer tables per season, plus FPL data |
| `python -m predictor train` | Builds `data/players.json` and trains `models/model.json` |
| `python -m predictor all` | Both |

Useful flags: `--seasons 2022 2023 2024` (season start years), `--season-count 4`,
`--include-current` (adds the season in progress), `--limit 150` (players per season),
`--no-fpl`, `--folds 10`.

The app re-reads `players.json` and `model.json` whenever they change, so you can retrain without
restarting the server.

## Where the data comes from

| What | Source |
| --- | --- |
| Goals, assists, appearances, date of birth, position, club, crest | football-data.org v4 `competitions/PL/scorers` (free tier, 10 requests/min, handled automatically) |
| Minutes played, injury/availability status, player photos | Fantasy Premier League public API (`bootstrap-static`, `element-summary`), no key needed |
| Market value (the regression target) | `data/market_values.csv`, which you maintain |

**Why the second source:** football-data.org's free tier has no minutes, injury status or photos.
FPL provides all three, so players are matched across the two sources by name and club. If FPL is
unreachable or you pass `--no-fpl`, the pipeline still runs:

- minutes are estimated from appearances, and the model then leaves minutes out (an estimate would
  just duplicate appearances)
- form is inferred from availability: a player who featured in under half of the matchdays in
  their latest season is "weak", and under a quarter is "injured"

**Market values:** no free API offers transfer valuations, so `data/market_values.csv` ships with
about 120 hand-compiled, **approximate** figures (€m, 2025/26 season). They are a starting point and
not authoritative. Update them from your preferred source and rerun `python -m predictor train`. The
CSV also takes optional overrides:

- `form`: `fit`, `weak` or `injured` (beats FPL and the availability guess)
- `photo_url`: any image URL

Rows that don't match a player in the fetched seasons are listed after training.

Players without a market value still appear in the app with a model valuation. You can also type an
actual fee into the lab to compare against.

## How the model works

- **Target:** `log(market value)`. Each feature then acts as a percentage ("+1 goal per season ≈ +x%"),
  which suits transfer prices. Predictions also stay positive, whereas a plain linear fit in euros
  predicts negative prices for squad players.
- **Features:**
  - per-season averages of goals, assists, minutes and appearances over the fetched seasons (with
    `--include-current`, the season in progress counts in proportion to the matchdays played)
  - age, plus age² centred on 26, so value can peak mid-career and then decline
  - position (one-hot, midfielder as the baseline)
  - form (one-hot, fit as the baseline)
- **Fit:** scikit-learn `LinearRegression`. Accuracy is reported with 5-fold cross-validation, so the
  headline numbers come from players the model didn't train on.
- **Explanations:** the "value drivers" bars split each prediction into one multiplicative effect per
  feature, measured against the average player in the training data.
- **Storage:** the trained model is plain JSON (intercept and coefficients), so the web app needs no
  scikit-learn at runtime.

### Limitations worth knowing

- The scorers endpoint only lists players who scored, so attackers dominate and goalkeepers barely
  appear. When a position or form category has no training examples, the app says it has no learned
  effect.
- With roughly 100 players and 11 parameters, effect sizes are noisy. Read the cross-validated error
  before quoting a number.
- Market value depends on much this model can't see: contract length, wages, club leverage and
  reputation. Treat a large gap between model and market as a prompt to look closer, not as proof
  that a player is mispriced.

## Project layout

```
predictor/
  football_data.py   football-data.org client (auth header, rate-limit retries)
  fpl.py             FPL client + availability -> form mapping
  names.py           accent/word-order tolerant name matching across sources
  fetch.py           downloads and caches raw responses in data/raw/
  dataset.py         raw responses + market_values.csv -> one row per player
  model.py           training, cross-validation, prediction and explanations
  __main__.py        CLI
app.py               Flask app + JSON API (/api/state, /api/players/<id>, /api/predict)
templates/, static/  front end (Chart.js is vendored, so charts work offline)
data/market_values.csv
tests/               pytest suite using fixtures shaped like the real API responses
```

Run the tests with `pytest`.

*An independent fan project, not affiliated with or endorsed by the Premier League. Chart.js is
MIT-licensed (`static/vendor/CHARTJS_LICENSE.md`).*
