# Keeping AI HR Payroll Details.md up to date

AI HR Payroll Details.md lives in the project root. It is generated
from the live codebase so it never drifts from what is actually running.

## How it updates automatically

- **In the app:** pp/main.py calls scripts.update_ai_hr_payroll_details.refresh_if_changed() 
  on every Streamlit rerun. The function fingerprints all .py files under pp/, database/ and scripts/,
  plus equirements, .streamlit/config.toml and data/*.md. If nothing changed it does nothing; if
  anything changed it regenerates the document. The next click after an edit is enough.
- **After adding a new feature:** add a TIMELINE entry and a MODULES entry in
  scripts/update_ai_hr_payroll_details.py. If the feature uses OpenAI, add an AI_FEATURES entry too.
  Routes, sidebar blocks, database tables, modules, models and package lists update themselves.

## Manual update (Windows PowerShell)

`powershell
Set-Location "C:\Users\Sai Tharun\OneDrive\Desktop\AI_HR_Payroll_Portal"
="utf-8"
& "C:\Users\Sai Tharun\anaconda3\envs\hr_poc\python.exe" scripts\update_ai_hr_payroll_details.py
`

## Manual update (CMD)

`cmd
cd "C:\Users\Sai Tharun\OneDrive\Desktop\AI_HR_Payroll_Portal"
set PYTHONIOENCODING=utf-8
"C:\Users\Sai Tharun\anaconda3\envs\hr_poc\python.exe" scripts\update_ai_hr_payroll_details.py
`

## What it extracts

- pp/modules/*.py - purpose, who uses it, line and function counts, whether it calls OpenAI
- pp/main.py - the real HR and employee PAGES tables (the routes)
- pp/modules/nav.py - the collapsible sidebar blocks and icons
- database/connection.py - every CREATE TABLE IF NOT EXISTS
- equirements - pinned packages

## Notes

- The helper only uses the Python standard library.
- If you want it to regenerate right now regardless of the fingerprint, run the script above.
- The state file scripts/.details_state.json is written by the script; it's small and can be deleted to force a refresh.
