# Windows setup

Tested on Windows 11 with Python 3.12 and PowerShell 5.1.

## 1. Prerequisites

```powershell
winget install --id Git.Git -e --source winget
winget install --id Python.Python.3.12 -e --source winget
```

Close and reopen the terminal afterwards. If `python --version` still says
"Python was not found", turn off the `python.exe` / `python3.exe` aliases under
**Settings → Apps → Advanced app settings → App execution aliases**.

## 2. Install

```powershell
cd C:\Users\<you>\Documents\Claude\agent-code
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

## 3. API key (never commit it)

1. Get a free key at <https://www.alphavantage.co/support/#api-key>.
2. `copy .env.example .env`, then open `.env` in Notepad and replace `replace-me`.
3. `.env` is listed in `.gitignore`. Check with `git check-ignore .env`; it should print `.env`.

The key is only read from the environment, is redacted from logs, and is never
written to reports.

## 4. Free-tier limits you will hit

| Limit | Effect | Mitigation |
|---|---|---|
| 25 requests/day | ~22 symbols + earnings calendar per day | `daily_request_budget: 24`; stalest symbols are fetched first |
| `outputsize=full` is premium | only ~100 recent bars per fetch | the cache merges each day's fetch, so history grows over time; seed longer history with `import-csv` |

Backtests and walk-forward evaluation need years of history. Until the cache
holds enough bars, `walkforward` will refuse to run and say why.

## 5. Daily use

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m agent_trading fetch            # update prices + earnings calendar
& $py -m agent_trading report           # fetch + write reports\daily_YYYY-MM-DD.md
& $py -m agent_trading report --no-fetch
& $py -m agent_trading screen
& $py -m agent_trading backtest
& $py -m agent_trading walkforward
& $py -m agent_trading journal open NVDA 0.05 180 172 --thesis "trend + momentum"
& $py -m agent_trading journal close 1 186 --reason "exit signal"
& $py -m agent_trading journal list
& $py -m agent_trading dashboard        # reports\dashboard.html
& $py -m agent_trading import-csv SPY C:\path\SPY.csv
& $py -m agent_trading import-robinhood C:\path\historicals.json
```

### Seeding long history from Robinhood

The free Alpha Vantage tier only returns ~100 bars. In a Claude Code session
with the Robinhood MCP connected, ask Claude to call `get_equity_historicals`
(interval `day`, up to 10 symbols per call) and save the JSON results, then run
`import-robinhood` on the saved files. Robinhood bars are split-adjusted;
gap-fill (interpolated) bars are skipped.

Paper trading and evaluation:

```powershell
& $py -m agent_trading paper run         # after each close: fills, stops, new paper orders
& $py -m agent_trading paper status      # positions, P&L, pending orders
& $py -m agent_trading evaluate          # train/validation report in reports\evaluation_YYYY-MM-DD.md
```

`journal open` rejects any paper trade that would risk more than 0.5% of equity,
push total open risk above 1.5%, exceed available cash, or exceed 25% of
equity in one position.

## 6. Schedule the daily report (optional)

Run after the US close, e.g. 5:30 PM Eastern, on weekdays:

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\scripts\daily_report.ps1`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 5:30PM
Register-ScheduledTask -TaskName "agent-trading daily report" -Action $action -Trigger $trigger
```

Adjust the time if your PC is not on Eastern time. Remove it with
`Unregister-ScheduledTask -TaskName "agent-trading daily report"`.

## 7. Where things go (all git-ignored)

| Path | Contents |
|---|---|
| `data/cache/` | cached daily bars + earnings calendar |
| `data/journal.db` | paper-trade journal (SQLite) |
| `reports/` | daily reports, backtest output, dashboard |
| `logs/` | rotating log files (secrets redacted) |
