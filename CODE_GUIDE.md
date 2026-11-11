# AIT Solutions — AI HR & Payroll Portal
## Code Guide (plain-English, file by file)

This document explains **every folder and file** in the project:
what it does, which tools it uses, what has been built, and where the
imports live.

---

## 1. What this project is

A role-based HR & Payroll web app built with **Streamlit**.

* **HR** signs in with a username/password and gets full access.
* **Employees** sign in with their Employee ID or registered work
  email and see only their own data (read-only, except their personal
  details which they can edit).

It manages employees (each with an optional profile photo), salaries,
payslips (PDF), PF/EPFO, leave, attendance, holidays, salary revisions,
full-and-final settlement, project assignments, an AI offer-letter
importer, an HR-only AI resume analyzer, and in-app
**notifications** (a bell for HR and employees).

The employee self-service and HR workflow also includes a shared
approval center for leave, reimbursement, and letter requests; request
comments and status-change history; notifications when HR decides or
requests information; downloadable employment, salary, and experience
letters; employee onboarding checklists; and monthly attendance
exception insights for missed punches, overtime, late arrivals, and
unrecorded working days.

---

## 2. Tools (libraries) used

Installed in the conda environment `hr_poc`. These are listed in the
`requirements` file.

| Tool | Version | Used for |
|---|---|---|
| **Python** | 3.12.14 (the configured `hr_poc` conda environment) | The language everything is written in; Python is not pinned in `requirements` |
| **Streamlit** | 1.65.0 | The whole web UI (pages, forms, tables, charts) |
| **sqlite3** | built-in | The database (no install needed) |
| **fpdf2** | 2.8.9 | Making **PDF** payslips and settlement statements |
| **PyMuPDF** (`fitz`) | 1.28.2 | Reading text out of an uploaded offer-letter or resume **PDF** |
| **openai** | 3.31.0 | The **AI** — offer-letter extraction, resume scoring, the assistant |
| **Pillow** | 12.3.0 | Cropping and resizing an uploaded profile photo |
| **pandas** | 3.0.6 | Showing tables in the database viewer and the resume analyzer |
| **VS Code + Pylance** | — | Editor / code intelligence (see `.vscode/`) |

Python's own libraries are also used: `datetime`, `calendar`, `json`,
`os`, `re`, `time`, `hashlib`, `hmac`, `secrets`, `pathlib`, `sys`.

### AI models and costs

The app calls the OpenAI API through the `openai` Python package. The
package is a client library; model use is a separate, metered API
service and is **not included** with a ChatGPT subscription. API pricing
depends on the selected model and the amount/type of data sent.

* **AI assistant:** defaults to `gpt-4.1`; override with
  `OPENAI_ASSISTANT_MODEL`.
* **Offer-letter extraction, bill reading, hiring content, payroll-audit
  summaries, and HR-letter polishing:** default to `gpt-4o`; most use
  `OPENAI_MODEL` as an override.
* **Resume analysis and Form 16 reading:** use the model choices exposed
  by the shared AI document workflows. Available choices in the code
  are `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`, and `gpt-4.1-mini`.
* The model names are model identifiers, not package versions. The
  actual model used for an individual request can differ when a user
  chooses another option or an environment override is configured.
* An `OPENAI_API_KEY` is required. The app reads it from Streamlit
  secrets or an environment variable. Uploaded documents and prompts
  used by AI features are sent to the configured OpenAI API.

Python, Streamlit, SQLite, and the listed Python packages do not charge
per employee simply for being installed; hosting, email delivery, and
OpenAI API usage may have separate charges. External links to
UMANG and EPFO open their websites and do not connect those services
to the portal's database.

---

## 3. Folder structure at a glance

```
AI_HR_Payroll_Portal/
├── app/
│   ├── main.py                 <- the entry point (assembles everything)
│   └── modules/                <- one file per feature
├── database/
│   ├── connection.py           <- all database setup + table creation
│   └── hr_payroll.db           <- the actual SQLite database file
├── data/
│   ├── hr_policy.md            <- HR policy notes the AI assistant quotes
│   └── posh_policy.md          <- the POSH policy shown on the policy page
├── .streamlit/
│   ├── config.toml             <- colours, fonts, theme
│   └── secrets.toml            <- OpenAI API key (NOT uploaded to git)
├── .vscode/                    <- editor settings
├── requirements                <- the tool/library list (pip)
├── .gitignore                  <- files that should not be uploaded
│
├── models/                     (placeholder - empty)
├── services/                   (placeholder - empty)
├── ai/  ml/                    (placeholder - empty)
├── config/  documents/         (placeholder - empty)
├── uploads/  tests/  utils/    (placeholder - empty)
```

> The empty folders were created for future plans (ML, file uploads and
> tests). No code lives in those folders yet. The `.py` files inside
> `models/` and `services/` are empty placeholders too.
>
> `data/hr_policy.md` is **not** a placeholder: it is the editable list
> of HR policy notes that the AI assistant quotes. See section 5.4.
>
> `data/posh_policy.md` is **not** a placeholder either: it is the POSH
> policy text shown on the "POSH policy" page. Edit the file to change
> the wording.

---

## 4. Where the imports live (how it hangs together)

There are three kinds of import, all written at the **top of each file**:

1. **Standard library** — e.g. `import datetime`, `import os`
2. **Third-party tools** — e.g. `import streamlit as st`, `import pandas as pd`
3. **Our own files** — e.g. `from database.connection import get_connection`
   and `from modules.salary import get_structure`

**The important trick** is in `app/main.py`:

```python
APP_DIR = Path(__file__).resolve().parent      # .../app
PROJECT_ROOT = APP_DIR.parent                  # the project root
for _path in (str(PROJECT_ROOT), str(APP_DIR)):
    sys.path.insert(0, _path)
```

This puts **both** the project root and the `app` folder on the import
path, so `from database...` and `from modules...` both work no matter
which folder Streamlit is started from.

---

## 5. File-by-file explanation

### 5.1 Root files

| File | What it is |
|---|---|
| `requirements` | The list of Python tools to install (`pip install -r requirements`). |
| `.gitignore` | Tells git to skip `secrets.toml`, `.env`, `__pycache__`, `.pyc`. |
| `.streamlit/config.toml` | **Base colours, fonts, radius and borders.** Warm off-white page, emerald accent, white cards, warm charcoal sidebar. `theme.py` supplies additional visual styling. |
| `.streamlit/secrets.toml` | Holds `OPENAI_API_KEY`. Created manually, **never committed** (gitignored). |
| `.vscode/settings.json` | Points VS Code at the `hr_poc` conda interpreter and adds `app/` to the analysis path. |
| `.vscode/extensions.json` | Recommends the Python + Pylance extensions. |

---

### 5.2 `app/main.py` — the entry point

**Does:** Assembles the whole app.

* Sets the page config (title, icon, wide layout).
* Fixes the import paths (section 4 above).
* Calls `initialize_database()` and `ensure_auth_setup()` once.
* Injects the global theme (`inject_theme()`).
* Shows the **login page** and stops if not signed in.
* Checks the latest due pay period and auto-releases it as a fallback;
  a daily Windows Scheduled Task performs the release even when the
  portal is closed.
* Picks the **page map for the role** (`PAGES` dict for HR vs employee).
* Draws the sidebar, then the **notification bell at the top right**,
  and runs the selected page.

**Imports:** `sys`, `pathlib.Path`, `streamlit as st`, plus
**one import line per module** (see the top of the file).

---

### 5.3 `database/connection.py`

**Does:** The single place that talks to the database.

* `get_connection()` — opens the SQLite file.
* `create_*_table()` — creates each table if it does not exist
  (employees, salary, payslips, users, leave requests, leave
  entitlements, attendance, holidays, holiday seed markers, revisions,
  settlements, candidates, notifications, assets, Form 16 documents,
  reimbursements, project assignments, and per-user appearance settings).
* `initialize_database()` — runs all of them, and applies small
  **migrations** (e.g. adding `employees.exit_date` to older databases).

**Imports:** `sqlite3`, `os` (both standard library).

---

### 5.4 `app/modules/` — one file per feature

Each file below is a **feature**. Every one is imported and routed by
`main.py`, and most end with a `show_..._page()` (HR) and/or a
`show_my_...()` (employee) function.

#### `theme.py` — the look & feel
Motion and polish that a config file cannot express: animations,
a single gradient hero banner, hover effects, custom scrollbars, and
per-user color palettes.
* **Functions:** `inject()` (adds the base stylesheet),
  `inject_user_theme()` (applies a saved palette with automatic text
  contrast), and `hero()` (the animated greeting banner).
* **Imports:** `streamlit`.
* **Palette choices:** Warm neutral, Ocean blue, Soft violet, Forest
  green, and Midnight. Choosing a preset applies coordinated page,
  surface, accent, sidebar, and dashboard colors; foreground colors are
  selected automatically for readable contrast. Settings are saved per
  account and available to both HR and employees.

#### `settings.py` — profile and appearance settings
Shows the sidebar settings section, profile information, and saved
theme choices. Stores each user's selected theme in the
`user_preferences` SQLite table. Theme presets apply across the
dashboard and sidebar with readable text contrast.

#### `auth.py` — sign-in, roles, passwords
Passwords are stored as salted **PBKDF2-SHA256** hashes, never as text.
* **Sign-in screen:** a full-bleed split — a violet story panel fills
  the left half of the viewport (brand, headline, six feature cards,
  trust strip) and a centred white card holds the login form on the
  right. `_LOGIN_CSS` is injected only while signed out, so it
  disappears the moment the user signs in; `_LOGIN_STORY` and
  `_LOGIN_HEADER` are the two HTML panels.
* **Functions:** `create_user`, `set_password`, `verify_current_password`,
  `reset_employee_password`, `authenticate_any`, `ensure_auth_setup`,
  `_provision_employee_accounts`, `show_login_page`, `sign_out`.
* **Imports:** `hashlib`, `hmac`, `secrets`, `streamlit`,
  `database.connection`.

#### `nav.py` — the sidebar
Builds the sidebar menu and the small account box (change password,
sign out). For an employee it also draws their profile photo (or their
initials) above their name.
* **Structure:** `HR_NAV` and `EMPLOYEE_NAV` are lists of
  `(group heading, [(label, page id, icon), ...])` blocks. HR sees
  **Workspace · AI Assist · Payroll · Time Off & Workplace ·
  Admin**;
  an employee sees **Profile · Payroll · Time off
  & Workplace**.
  Each block is a **collapsible section** (a `st.expander`): click its
  heading and it opens to show the modules inside, which keeps a long
  menu reading as a few short ones. The block that holds the page you are
  already on opens itself, so the menu never hides where you are.
  The Payroll section also links to UMANG and the
  official EPFO Passbook portal; employees sign in directly on those
  external websites. Employee-only **Quick Links** opens a shortcut page
  in the main content area, and **Health Benefits** links separately to
  the Pazcare sign-in page.
* **AI Assist block.** HR's offer letter, resume analyzer, hiring pack,
  letter generator, and payroll audit tools sit together in
  `AI_BLOCK = "AI Assist"`. Employees use the floating assistant
  launcher; there is no duplicate assistant entry in their sidebar.
* **Function:** `render_sidebar(user)`.
* **Imports:** `streamlit`, `modules.auth`, `modules.session`,
  `modules.avatar`, `modules.settings`.

#### `quick_links.py` — employee shortcut page
Displays employee destinations as shortcut cards in the main content
area, sorted alphabetically by label. The sidebar's **Quick Links**
button opens this page; selecting a card navigates to the chosen
employee section.
* **Function:** `show_quick_links()`.
* **Imports:** `streamlit`.

#### `notifications.py` — the bell
The in-app **notifications** system: a short message for the person who
should hear about something that happened.
* HR has one shared inbox (`recipient = "hr"`); each employee has their
  own inbox (`recipient = employee_id`). `recipient_for(user)` picks it.
* `notify` / `notify_hr` / `notify_employee` write a message into the
  **`notifications`** table.
* `get_notifications`, `unread_count`, `mark_read`, `mark_all_read` and
  `clear_all` read and update the inbox.
* `render_notifications(user)` draws the button — **"Notifications ·
  N new"** — and a popover listing the recent messages, each with an
  icon, an age ("5 min ago") and its own "Mark all read" / "Clear"
  buttons. `main.py` places it at the **top right of the page** on every
  signed-in screen.
* Who sends what: `leave.py` (new request → HR, decision → employee,
  cancellation → HR), `payslip.py` (new payslip → employee),
  `revisions.py` (salary change → employee), `assets.py` (asset
  assigned or taken back → employee) and `reimbursements.py` (new claim
  → HR, approved/rejected/paid → employee). Those modules only ever call
  the helpers — they never touch the table directly.
* **Imports:** `datetime`, `streamlit`, `database.connection`.

#### `home.py` — the splash screen
Brief branded start-up screen with an animated progress bar, then it
hands over to the dashboard.
* **Functions:** `show_home()`, `_advance_from_landing()`.
* **Imports:** `time`, `streamlit`, `modules.theme.hero`.

#### `application.py` — HR dashboard
The HR home page: a personalised welcome hero, key numbers (employees,
payslips, total/average CTC) and cards linking to each module.
* **Functions:** `_dashboard_stats()`, `show_application()`.
* The card list is the `MODULES` table at the top of the file: add a row
  `(title, description, ":material/icon:", page_id, css_key)`. The
  shared accent and hover styling are applied automatically by
  `theme.py`; `css_key` only has to be unique.
* **Imports:** `streamlit`, `database.connection`, `modules.theme.hero`.

#### `employee.py` — employee records (HR)
Create, view, edit and delete employee master records, reset an
employee's password, and assign the projects they are working on.
* **Functions:** `render_employee_card`, `delete_employee`,
  `update_employee`, `render_employee_record`, `show_employee`.
* **Imports:** `datetime`, `streamlit`, `database.connection`,
  `modules.salary.scale_salary_structure`,
  `modules.auth.reset_employee_password`,
  `modules.projects.render_hr_projects`.
* **Note:** the employee record card ends with a **Projects** section
  (assign a project, list current assignments, remove one). Project
  rows follow the employee when HR changes their Employee ID.

#### `projects.py` — project assignments
Records which projects each employee is working on. HR assigns a
project (name, role, status, start date, optional notes) and removes
old ones; employees see the same list read-only on **My overview** and
get a notification when a project is assigned.
* **Functions:** `get_projects`, `add_project`,
  `delete_project`, `render_my_projects`, `render_hr_projects`, plus
  helpers `_pretty_date`, `_detail_line`, `_status_badge`.
* **Imports:** `datetime`, `streamlit`, `database.connection`
  (`get_connection`, `create_project_table`),
  `modules.notifications.notify_employee`.
* **Data:** one row per assignment in `employee_projects`
  (`employee_id`, `project_name`, `role`, `status`, `start_date`,
  `notes`, `created_at`). Active projects sort first; the FK cascades
  on employee delete.

#### `salary.py` — salary structure
Turns an **Annual CTC** into a statutory-compliant monthly breakdown,
saves it, shows it, and **rescales** it when the CTC changes.
* **Functions:** `auto_salary_components`, `get_structure`,
  `save_structure`, `structure_summary`, `scale_salary_structure`,
  `render_structure_details`, `render_create_salary`,
  `render_view_salaries`, `show_salary`, `show_salary_page`,
  `show_my_salary`.
* **Imports:** `streamlit`, `database.connection`,
  `modules.session.require_employee`.

#### `payslip.py` — payslips (the biggest file)
Builds monthly salary and PF with calendar-day proration, paid and
working-day counts, the scheduled month-end pay date, LOP handling,
saving, an **HTML preview** and a **PDF** download, plus the HR and
employee pages. A daily scheduled task and the app fallback catch up all
missing periods whose pay dates have arrived, from each employee's
joining month; employee views show saved payslips.
* **Functions (main):** `build_monthly_breakdown`, `save_payslip`,
  `auto_generate_current_month_payslips`, `build_payslip_html`,
  `build_payslip_pdf`, `render_payslip_preview`, `show_payslip_page`,
  `show_my_payslips`, `latest_payslip`.
* **Imports:** `calendar`, `datetime`, `html`, `os`, `streamlit`,
  `database.connection`, `modules.salary.get_structure`,
  `modules.session` (`require_employee`, `employee_details`),
  `modules.notifications`, `modules.workdays.working_days_between`.
  PDF library
  is imported inside the PDF function: `from fpdf import FPDF`.
* **Loss of pay** (`lop_days_for_month`) counts the **working days**
  of approved Loss of Pay leave that fall inside the pay month, so a
  Friday-to-Monday LOP deducts two days of pay, not four — the same
  count the leave page shows the employee.
* **`latest_payslip(employee_id)`** returns the newest released payslip as a
  small summary dict (`period`, `net_pay`, `gross`, `deductions`,
  `generated`) plus its period and breakdown for preview and PDF
  download, or `None` when no payslip has been saved.

#### `epfo.py` — PF / EPFO statement
Shows the provident-fund statement using saved, released payslips only.
Unreleased months are omitted; the balance is the **running total of
contributions** (Employee EPF + Employer EPF + Total row), capped at the
latest due period and the employee's exit or final-settlement month.
Visible to **both** HR and employees.
* **Functions:** `epfo_components`, `epfo_statement`, `epfo_table_rows`,
  `render_epfo_section`, `_render_pf`, `show_epfo_page`, `show_my_epfo`.
* **Imports:** `datetime`, `streamlit`, `modules.payslip`,
  `modules.settlement.last_accrual_period`.

#### `tax.py` — income tax: Form 16 and monthly TDS
Two jobs: a month-by-month **TDS estimate** from each employee's salary
structure, and **Form 16** filing. HR gets the full page; an employee
sees their own record read-only as **My tax**.

* **TDS estimate.** `estimate_tax` walks the new-regime slabs in
  `TAX_SLABS`, takes off the ₹ 75,000 standard deduction, applies the
  section 87A rebate (no tax up to ₹ 12 lakh of taxable income) with
  marginal relief just above it, then adds 4% cess. `slab_tax` does the
  band-by-band arithmetic. Every figure comes back in a dict so the screen
  can show its working, and every screen carries the same "estimate only"
  caption. `monthly_tds_rows` spreads the year's tax over the financial
  year's months (April–March), starting at the joining month and stopping
  at the statement month; `tds_so_far` totals it.
* **Reading a Form 16.** HR uploads several PDFs at once; each is read
  with `modules.offer_letter.extract_text` and sent to the model
  (`ai_read_form16`, `temperature=0`, JSON output) for the employee
  **name**, PAN, employer, year and totals. `normalise_form16` makes the
  reply safe to render.
* **Matching happens in Python, not in the model.** `name_score` compares
  names as word sets (titles dropped, word order ignored) and
  `match_employee` chooses the employee, also reading the employee id out
  of the **file name** when it is there. A strong printed name wins;
  otherwise the file name decides. If the two **disagree** the match is
  flagged as a `conflict` and the screen warns HR — this is exactly the
  case that could file a form against the wrong person, so it is never
  settled silently.
* **Nothing is issued by itself.** The read results are held in
  `st.session_state["tax_review"]` and drawn as a review list where HR
  fixes the employee or the year, then presses **Issue**.
* **Storage.** One row per form in the **`form16_documents`** table (see
  `create_form16_table`), with the PDF itself kept as a BLOB like the
  employee photo. `(employee_id, tax_year)` is unique, so a re-issued form
  replaces the old one rather than piling up. Issuing also sends the
  employee a **Tax** notification pointing at the tax page.
* **Functions:** `estimate_tax`, `slab_tax`, `gross_annual`,
  `monthly_tds_rows`, `tds_months`, `tds_so_far`, `financial_year_start`,
  `fy_label`, `parse_tax_year`, `name_score`, `match_employee`,
  `ai_read_form16`, `normalise_form16`, `save_form16`,
  `get_form16_index`, `get_form16_data`, `delete_form16`,
  `show_tax_page`, `show_my_tax`.
* **Imports:** `datetime`, `json`, `re`, `pandas`, `streamlit`,
  `database.connection`, `modules.offer_letter` (reuses `extract_text`,
  `ai_available`, `MODELS`, `DEFAULT_MODEL`), `modules.config`,
  `modules.notifications`, `modules.session`; `from openai import OpenAI`
  inside the AI function.
* **Known limit.** Surcharge (income above ₹ 50 lakh) is not modelled, and
  the estimate ignores an employee's investments, rent and other income.
  It is a guide, not a payroll calculation.

#### `workdays.py` — the working-day calculator
One job: decide what counts as a working day, so leave, attendance
and payslips never disagree about what a date range costs.
* **Rules:** Saturday and Sunday are off, a date in the `holidays`
  table is off, everything else counts. `working_days_between(from,
  to, portion)` returns whole days — or 0.5 for a single half day.
  `is_working_day` answers for one date, `holiday_date_set` gives the
  holiday dates to skip, `span_description` explains a range in words
  (including any weekend/holiday days skipped), and `skipped_days`
  lists what was skipped. Constants: `DAY_PORTIONS`, `HALF_DAY`.
* **Imports:** only `database.connection` — deliberately nothing from
  the rest of `modules`. `holidays` imports `payslip` (for `MONTHS`),
  so `payslip` must not import `holidays` back; this neutral module
  reads the holiday table straight from the database and can be used
  from anywhere without risking a circular import.

#### `leave.py` — leave management
A corporate leave desk: leave types (Casual / Sick / Earned / Loss of
Pay), yearly entitlements, balances, and applying / approving /
cancelling requests.
* **The working-days rule.** Leave is counted in **working days**,
  never calendar days — Friday to Monday costs two days, and a
  weekend or public holiday inside the range is free. The maths
  lives in `modules.workdays` so leave, attendance and the payslip
  all agree on what a request costs.
* **Policy is checked before a request is saved**
  (`validate_request`): the balance has to cover the request, the
  range cannot clash with leave already pending or approved, and a
  wholly-past range, an all-weekend/holiday range, a half day spanning
  more than one date, or a half day of Loss of Pay is refused with a
  plain-English reason. Violations raise `ValueError`, which the UI
  shows inline and the AI bot converts into a reply.
* **Functions:** `get_entitlements`, `set_entitlement`, `get_balance`,
  `balance_for`, `validate_request`, `apply_leave`, `get_requests`,
  `decide_request(status, decided_by, note=None)`, `cancel_request`,
  `colleagues_off`, `ensure_all_entitlements`, `list_employees`,
  `show_leave_page`, `show_my_leave`, helpers (`_my_request_card`,
  `_history_panel`, `_approval_context`, `format_range`).
* **Imports:** `datetime`, `streamlit`, `database.connection`,
  `modules.notifications`, `modules.payslip.MONTHS`,
  `modules.theme.hero`, `modules.workdays`.
* **HR page.** The approval queue comes first, and every pending card
  shows what approving *costs* before HR commits: the balance impact
  (available → after, or "no balance is spent" for Loss of Pay) and
  who else is already off in the same range. Approve/Reject buttons
  can carry a decision note, which the employee sees in their
  notification. Tabs cover leave **coverage** by month (who is off
  when) and **balances** by employee.
* **Employee page.** Three tabs: **Book leave**, **Leave history**
  and **Leave policy**. Booking previews the working-day count, the
  balance after, and the weekends/holidays being skipped; success
  messages flash after the rerun. History opens with four summary
  cards (days taken, approved, pending, not approved), a status
  filter, then the requests newest first with a Withdraw button while
  still pending. A half day is offered for paid leave only.

#### `attendance.py` — attendance
A corporate timesheet, not a school roll call: nobody ticks a box
that says "I am present". Working days skip weekends and holidays.
* **How it works now:** the employee **clocks in and clocks out**;
  hours served, punctuality and the day's status all follow from the
  punches. A radio picks the work mode (Office / Work From Home) once
  clocked in, and the mode survives clock-out. Weekends, holidays and
  days covered by **approved leave** refuse a clock-in (the page
  shows the leave branch instead of the buttons), and past days are
  locked to employees.
* **Shift maths:** 09:30–18:30 with a 15-minute grace; the one-hour
  lunch is deducted only when the span is over 6 hours; 4h or more
  counts as a full day, under 4h becomes a Half Day.
* **HR page.** Three tabs. **Daily timesheet**: head-counts
  (Present / WFH / Half day / On leave / Absent / Late today), a
  "Who is in" table for the chosen date, and a "Correct a day" panel
  where HR can fix anyone's status or punches. **Monthly summary**:
  working days, hours served, late arrivals, team attendance %, a
  per-person report and a day-by-day drill-down. **Insights** highlights
  late patterns, missed punches, overtime, recorded absences, and
  unrecorded past working days (excluding approved leave, holidays,
  dates before joining, and dates after exit).
* **Functions:** `clock_in`, `clock_out`, `set_mode`,
  `mark_attendance` (any day, used by HR), `mark_self` (today only,
  legacy kept for older callers), `get_attendance`,
  `get_attendance_for_date`, `is_working_day`, `hours_worked`,
  `punctuality`, `daily_register`, `register_summary`,
  `month_summary`, `monthly_report`, `show_attendance_page`,
  `show_my_attendance`, `_working_days`.
* **Imports:** `datetime`, `streamlit`, `database.connection`,
  `modules.payslip.MONTHS`, `modules.leave` (`list_employees`,
  `get_requests`), `modules.holidays` (`working_days`,
  `holiday_dates`), `modules.theme.hero`.
* **Note:** attendance "Absent" is only a record — pay is unaffected.
  Loss of pay comes from **approved Loss of Pay leave**
  (`payslip.lop_days_for_month`, counted in working days), not from
  the attendance sheet.

#### `holidays.py` — holiday calendar
HR maintains public/company holidays; employees get a read-only list.
Holidays feed the attendance module so they are never counted as
working days. Only **upcoming** holidays in the current year are shown;
past dates stay in the database for attendance but disappear from both
pages.
* **Defaults:** `seed_default_holidays()` adds fixed national holidays
  every year plus curated 2026 festival dates. A `holiday_seed` marker
  makes this one-time per year, so a default the HR team removes does
  not come back on the next rerun.
* **Functions:** `list_holidays`, `add_holiday`, `update_holiday`,
  `delete_holiday`, `seed_default_holidays`, `working_days`,
  `upcoming_holidays`, `show_holidays_page`, `show_my_holidays`.
* **Imports:** `calendar`, `datetime`, `html`, `streamlit`,
  `database.connection`, `modules.payslip.MONTHS`, `modules.theme.hero`.
* **Look:** a gradient hero, three headline metrics (upcoming / this
  month / next holiday) and a **month-grouped grid of date-chip
  cards**. Each card shows a coloured day/month chip, the weekday and
  an Upcoming/Today badge; HR cards also carry Edit and Remove buttons.
* **Editing:** HR opens the inline editor, changes the date or name and
  saves. A date that already holds another holiday is refused with a
  clear message. The add form only accepts dates from today to 31
  December, so new entries cannot vanish into the past.
* **Note:** the year picker is gone by design - the calendar is always
  the current year. Employees never see Add, Edit or Remove controls.

#### `assets.py` — company assets issued to employees

The register of company property (laptops, phones, ID cards and so on).
HR adds an item, assigns it to an employee, and can take it back,
retire it or remove it. Employees see a read-only list of what is
currently with them.

* **Data:** the `assets` table. One row per item: `asset_tag`,
  `category`, `name`, `serial_number`, `condition`, `status`
  (Available / Assigned / Returned / Retired), `employee_id`,
  `assigned_date`, `returned_date`, `notes`.
* **Functions:** `add_asset`, `update_asset`, `assign_asset`,
  `return_asset`, `retire_asset`, `restore_asset`, `delete_asset`,
  `list_assets`, `get_asset`, `employee_assets`, `assignable_assets`,
  `asset_summary`, `show_assets_page` (HR), `show_my_assets`
  (employee).
* **Rules:** a new tag is auto-numbered (`AIT-0001`) when the Asset tag
  box is left blank. "Available" and "Returned" both mean *in stock* and
  can be assigned; "Assigned" means it is with someone. Assigning or
  returning sends the employee a bell notification (category "Asset").
* **Imports:** `datetime`, `streamlit`, `database.connection`,
  `modules.leave.list_employees`, `modules.notifications.notify_employee`,
  `modules.session.require_employee`, `modules.theme.hero`.
* **Look:** a gradient hero, four headline metrics (total / assigned /
  in stock / retired), one compact **Add · Assign · Edit** expander, then
  a filterable three-column grid of icon-chip cards. Each card shows the
  category icon, name, tag, serial, condition, status badge and who holds
  it, with Return/Retire and Remove buttons for HR.

#### `policies.py` — company policies (read-only)

Shows the POSH policy. Nothing here is stored in the database: the page
reads a text file and renders it, so the wording can change without
touching code.

* **Data:** `data/posh_policy.md`. Comment blocks (`<!-- ... -->`) in that
  file are stripped before display, so editor notes stay hidden. The
  file's first heading is dropped too, because the page banner already
  shows the title.
* **Functions:** `load_policy`, `show_policies_page` (HR),
  `show_my_policies` (employee).
* **Look:** a gradient hero, four quick facts taken from the Act
  (applies to / raise within / inquiry time / confidential), a contact
  callout, then the full policy in a hover-lift card. HR also sees a hint
  pointing at the file to edit.
* **Imports:** `os`, `re`, `streamlit`, `modules.theme.hero`.
* **Note:** if the file is missing or empty the page still opens and says
  so, rather than crashing.

#### `reimbursements.py` — employee bills & reimbursements

An employee pays for something out of their own pocket (a cab, lunch,
internet), snaps the bill and submits a claim. HR looks at the claim
against the receipt, approves or rejects it, then marks the approved one
as paid. The uploaded file is kept with the claim so the proof can never
be lost.

* **Data:** the `reimbursements` table. One row per claim: `employee_id`,
  `category` (Travel / Food / Accommodation / Internet / Phone / Medical /
  Training / Office supplies / Client entertainment / Other), `amount`,
  `expense_date`, `description`, `status`
  (**Pending → Approved → Paid**, or **Rejected**), plus the bill itself
  (`file_name`, `mime`, `size_bytes`, `data`) and the decision trail
  (`submitted_at`, `decided_at`, `decided_by`, `decision_note`,
  `employee_reply`, `paid_on`). Statuses include **Pending**, **Needs
  information**, **Approved**, **Rejected**, **Paid**, and **Cancelled**.
* **Functions:** `submit_reimbursement`, `approve_reimbursement`,
  `reject_reimbursement`, `reopen_reimbursement`, `undo_approval`,
  `mark_paid`, `withdraw_reimbursement`, `delete_reimbursement`,
  `list_reimbursements`, `get_reimbursement`, `get_reimbursement_file`,
  `reimbursement_summary`, `show_reimbursements_page` (HR),
  `show_my_reimbursements` (employee).
* **Rules:** only a PDF / PNG / JPG up to 8 MB is accepted, and the amount
  must be more than zero. An employee can **withdraw** only their own
  *pending* claim; withdrawn claims remain in history as Cancelled. HR
  can request more information and receive the employee's reply. HR can
  act on any claim and remove any claim. Every
  step notifies the right person (submit → HR, decide/paid → employee,
  category "Reimbursement").
* **Money never mixes with salary.** A reimbursement is settled on its
  own, so approving one never silently changes a payslip.
* **Imports:** `datetime`, `streamlit`, `database.connection`,
  `modules.leave.list_employees`, `modules.notifications` (`notify_hr`,
  `notify_employee`), `modules.session.require_employee`,
  `modules.theme.hero`.
* **Look:** a gradient hero, four headline metrics (total / pending /
  awaiting payment / reimbursed), an **Upload a bill** expander for the
  employee (category, amount, expense date, file, what it was for), and a
  filterable three-column grid of icon-chip cards. HR's cards carry the
  decision form (a note plus Approve / Reject / Mark paid / Undo / Reopen)
  and a Remove button; everyone gets a Download bill button.

#### `approvals.py` — HR approval center
Combines pending leave, reimbursement, and employee letter requests.
HR can approve, reject, or request more information, with comments;
employees are notified in-app and can reply to information requests.
The history tab shows current request states plus the chronological
status-change timeline.

#### `employee_services.py` — letters and onboarding
Employees request employment-verification, salary-certificate, and
experience letters. HR issues or declines requests; issued letters are
generated as PDFs from the employee record and downloadable by the
employee. The onboarding checklist tracks profile completion, required
documents, employee setup tasks, and HR verification. Profile/document
tasks are checked against the saved employee profile and uploaded
documents before the employee can submit them.

#### `request_tracking.py` — request status history
Stores status changes, actor, comments, and timestamps for leave,
reimbursement, and letter requests. The Approval Center uses this
timeline to preserve the request's review trail.

#### `revisions.py` — salary revisions
Records a salary-revision history and applies a new CTC (which rescales
the structure).
* **Functions:** `record_revision`, `get_revisions`, `apply_revision`,
  `render_revision_history`, `show_revisions_page`.
* **Imports:** `datetime`, `streamlit`, `database.connection`,
  `modules.salary`, `modules.notifications`.

#### `settlement.py` — full & final settlement
Computes a full-and-final settlement, saves it, produces a **PDF**, and
sets the employee's exit date (which stops further payroll/PF accrual).
* **Functions:** `compute_settlement`, `save_settlement`,
  `get_settlements`, `build_settlement_pdf`, `set_exit_date`,
  `last_accrual_period`, `show_settlement_page`.
* **Imports:** `datetime`, `streamlit`, `database.connection`,
  `modules.payslip`, `modules.leave.get_balance`,
  `modules.salary.GRATUITY_PCT_OF_BASIC`; `from fpdf import FPDF` inside
  the PDF function.

#### `offer_letter.py` — AI offer-letter importer
Upload an offer letter (**PDF or text**) and AI extracts the fields to
create a new employee. Falls back to manual entry when no API key is
set.
* **Functions:** `ai_extract_fields`, `extract_text`, `normalise_fields`,
  `create_employee_from_offer`, `suggest_employee_id`,
  `show_offer_letter_page`.
* **Imports:** `datetime`, `json`, `os`, `re`, `streamlit`,
  `database.connection`, `modules.salary`, `modules.employee`,
  `modules.auth`, `modules.config`; `import fitz as pymupdf` (PDF text)
  and `from openai import OpenAI` are imported inside the functions.

#### `resume_analyzer.py` — AI resume analyzer (HR only)

HR gives the **required skills** for a role and uploads resumes; AI
scores each candidate out of 100 and says how well they fit, then HR
marks the good ones **Shortlisted**. It appears only in the HR sidebar
and the page itself refuses to render for an employee login, so the
lock-out does not rely on the menu alone.

* **Scoring.** `ai_score_resume` sends the resume plus the requirements
  (built by `_requirements_text`) to the model with `temperature=0` and
  JSON output, asking for a `score`, the `matched_skills`, the
  `missing_skills` and a short verdict. `normalise_resume` cleans the
  reply and `verdict_for` turns the score into a band — **85+ Perfect
  fit, 70+ Strong match, 50+ Possible fit, else Not a fit**.
* **Storage.** Every candidate is one row in the **`candidates`** table
  (see `create_candidate_table`). Skill lists are stored as
  comma-separated text. `get_candidates` filters by job, verdict,
  decision and a name/skill search, always best match first;
  `save_decisions` records the Shortlist/Reject/On-hold choice.
* **UI.** `show_resume_analyzer_page` holds an "Screen new resumes"
  expander (a `st.file_uploader` with `accept_multiple_files=True`) and
  a ranked `st.data_editor` whose Decision column is a dropdown.
* **Functions:** `ai_score_resume`, `normalise_resume`, `verdict_for`,
  `save_candidate`, `get_candidates`, `save_decisions`,
  `delete_candidate`, `clear_candidates`, `show_resume_analyzer_page`.
* **Imports:** `datetime`, `json`, `pandas`, `streamlit`,
  `database.connection`, `modules.offer_letter` (reuses `extract_text`,
  `ai_available`, `MODELS`, `DEFAULT_MODEL`), `modules.config`;
  `from openai import OpenAI` inside the AI function.

#### `assistant.py` — the AI HR assistant (bot on every page)

A popup chat bot, available on **every signed-in page** for both HR
and employees. A **rounded emerald tile** floats in the bottom-right
corner and opens the popup — a **small** window (a compact 430px chat
column, not a big modal). The drawing is deliberately plain: an emerald
rounded square carrying a little **robot face** — two white eyes and a small
smile — with a green presence dot. It
is small (a 78px dock in the bottom-right corner), has no glow behind it
and carries no caption text,
so it stays tidy; its motion is a gentle float with a soft status pulse. The
chat **greets you by name** with a time-of-day hello ("Good afternoon,
Tharun! 👋 How can I help you today?"). You can ask things like *"what
is my leave balance?"*, *"when is the next holiday?"* or, as HR, *"show
me Pavan's PF balance"* — and you can ask it to **do** things: *"apply
casual leave next monday"* books the leave there and then.

The launcher is deliberately **not** the button. The button is invisible
(it paints nothing) and only exists to catch the click; `BOT_FIGURE` is
the drawing that sits on top of it.

Five traps worth remembering here, all of which cost real debugging:

1. `st.html` wraps its content in a box that is only as tall as that
   content, so a percentage height inside it resolves to **zero**. The
   drawing is therefore positioned with `position: absolute; inset: 0`
   to fill the dock. Asking for `height: 100%` instead makes the whole
   launcher collapse to nothing.
2. Sizing the button with `height: 100%` once made only a thin strip
   clickable, because Streamlit inserts its own boxes around a button and
   the percentage resolved against one of those instead of the dock. The
   button is pinned with `position: absolute; inset: 0` instead, which
   fills the dock no matter what Streamlit wraps around it.
3. `st.html` sanitises its markup, and that sanitiser **strips SVG**. An
   inline `<svg>` glyph renders as nothing, leaving an empty tile. The
   robot face is therefore drawn from plain elements in `BOT_FIGURE` plus
   CSS - two round eyes (`border-radius: 50%`) and a smile made from a
   bottom border with a rounded bottom edge - never from SVG.
4. That same sanitiser drops an injected block **completely** when it so
   much as *mentions* SVG tag names, even inside a CSS comment. Measured in
   a headless browser: a plain `<style>` passes through `st.html`, while
   the identical stylesheet with the text `<svg>` written in a comment
   disappears - which left the launcher unstyled, sitting in the page flow
   instead of floating. The bot stylesheet is therefore injected with
   `st.markdown(..., unsafe_allow_html=True)`, which does not sanitise.
5. `position: fixed` only means "fixed to the window" while **no ancestor
   has a transform** - a transformed ancestor becomes the containing block
   instead. The theme used to fade each page in with `ait-fade-up`, whose
   final keyframe is a transform, so with `fill-mode: both` Streamlit's
   `stMainBlockContainer` kept a transform forever and the launcher was
   pinned to the bottom of the *page* (hundreds of pixels below the fold)
   rather than the window. The page transition now animates **opacity
   only**. If a floating element ever drifts again, inspect its ancestors'
   `transform` values first.

The important part is how it gets its answers:

* **It never guesses.** Every fact comes from a **tool** — a small
  Python function that reads SQLite. The model picks which tool to call;
  it is not allowed to invent numbers.
* **Permissions are enforced in Python, not in the prompt.** `_resolve_target`
  pins an employee to their own record no matter what the model asks
  for, so a cleverly worded question ("show me Pavan's salary") is
  **refused**, not answered.
* **Each account gets its own conversation.** A browser session outlives
  a sign-out, so `render_assistant` remembers the signed-in identity in
  `ait_bot_owner` and wipes `ait_bot_chat` / `ait_bot_history` whenever
  it changes. Nobody can see the previous person's chat - which contains
  their salary, leave and provident-fund figures.
* **It can answer policy questions.** `_load_policy()` reads
  `data/hr_policy.md` (plain English, editable by anyone, HTML comments
  ignored) and adds it to the instructions the bot receives. If a policy
  question is *not* covered there, the bot is told to say it does not
  have that detail and to point the user at HR — it will **not** invent a
  notice period or a working-hours rule.
* **It can take actions, not just answer.** `apply_leave` books leave
  straight away (no "are you sure?" step — that is what the owner asked
  for), `cancel_leave` cancels a pending request and HR can `decide_leave`
  to approve or reject one. Writes obey the same Python-enforced pinning as
  reads, so an employee can only ever book or cancel their **own** leave.
  A missing leave type becomes Casual Leave, and the reply says which type
  was used so it can be changed.
* **Dates are worked out in Python.** `_resolve_date` turns "next monday",
  "tomorrow", "in 3 days" or a plain `YYYY-MM-DD` into a real date, and
  the system prompt carries a seven-day calendar. That keeps a leave
  request off the wrong week, which model arithmetic alone would not.
* **Voice input:** a microphone beside the chat box uses browser speech
  recognition where supported (typically Chrome or Edge). Clicking the
  microphone records a question; after recognition, it is submitted
  automatically and the assistant responds in the chat.
  Recognition requests Indian English (`en-IN`), and the microphone is
  a visible button immediately beside the chat input.
  Voice can ask questions or make supported requests; it uses the same
  employee-scoped tools and permissions as typed chat. Voice-submitted
  requests follow the assistant's existing request handling. Browser speech
  recognition may use an online browser
  service and is not guaranteed to be offline or available in every browser.
  The resulting chat request still uses the configured OpenAI API and may
  incur its normal usage cost.
* **The log follows the newest message.** `_inject_autoscroll()` sends a
  tiny script with the transcript so it stays pinned to the bottom. The
  script is harmless if it never runs: the log simply stops following.
* **Two questions in a row work.** The whole conversation is kept in
  `st.session_state["ait_bot_history"]` in OpenAI's message format, and
  the API messages are rebuilt from it on every round, so a previous
  tool call always keeps its matching tool results. A tool's request and
  its results are stored in **one** `history.extend()` call, so a rerun
  that fires mid-answer (Streamlit's run-on-save, a stray click) cannot
  split them. `_sanitise()` is a belt-and-braces repair: before every
  request it drops any tool request that lost its results, which is what
  the API otherwise rejects with *"An assistant message with 'tool_calls'
  must be followed by tool messages…"*.
* **The helper button floats; the chat is a popup.** A fixed-position
  `Ask AIT` pill sits in the bottom-right corner of every page and opens
  a centred `st.dialog` popup (`width="large"`). Streamlit draws the
  backdrop, the close button, ESC and click-outside handling, and calls
  `_close_bot` on dismissal to lower the open flag. The popup is a
  **small** dialog (`width="small"`, capped to 430px) with a short
  transcript, and it opens with a friendly greeting from `_hello`. The
  launcher and popup are rendered from `main.py` *after* the page body
  and styled by `BOT_STYLESHEET` at the bottom of this file (it belongs
  to the widget, not to the global theme). `BOT_FIGURE` is the launcher
  drawing - a rounded emerald tile with a robot face (two eyes and a smile)
  and a presence dot:
  it sits in an `ait_bot_dock` container on top of an invisible button,
  and `BOT_STYLESHEET` gives it its look and its motion (a gentle float
  plus a soft status pulse).
* **Model:** `gpt-4.1` by default; override with the `OPENAI_ASSISTANT_MODEL`
  environment variable. `_create` retries without `temperature` if a
  model (e.g. the `gpt-5.x` family) rejects it.
* **Tools (read):** `who_am_i`, `get_employee`, `get_salary_structure`,
  `get_payslip`, `get_leave_balance`, `get_attendance_summary`,
  `get_pf_summary`, `get_holidays`, `list_leave_requests`, plus HR-only
  `find_employee` and `payroll_summary`.
* **Tools (write):** `apply_leave`, `cancel_leave` (own request), and
  HR-only `decide_leave` (approve/reject).
* **Functions:** `render_assistant`, `available`, `_render_panel`,
  `_hello`, `_ask`, `_run_tool`, `_resolve_target`, `_resolve_date`,
  `_resolve_leave_type`, `_calendar_note`, `_create`, `_recent`,
  `_sanitise`, `_close_bot`, `_as_dict`, `_load_policy`,
  `_inject_autoscroll`, and one `_tool_...` function per tool.
* **Imports:** `datetime`, `importlib.util`, `json`, `os`, `re`,
  `streamlit`, `database.connection`, `modules.attendance`,
  `modules.config`, `modules.epfo`, `modules.holidays`, `modules.leave`,
  `modules.payslip`, `modules.salary`, `modules.session`; `from openai
  import OpenAI` inside the function.
* **To add a policy fact:** edit `data/hr_policy.md`. No code change and
  no restart.

#### `config.py` — secrets helper
Reads a secret from, in order: the project `secrets.toml`, the user's
`~/.streamlit/secrets.toml`, then an environment variable.
* **Functions:** `get_secret`, `has_secret`, `secrets_location`,
  `_load_toml`.
* **Imports:** `os`, `pathlib.Path`.

#### Leave request email delivery
To email the TL/team address entered with a leave request, configure
SMTP settings in `.streamlit/secrets.toml` (or as environment variables):

```toml
SMTP_HOST = "smtp.example.com"
SMTP_PORT = "587"
SMTP_USERNAME = "portal@example.com"
SMTP_PASSWORD = "mail-provider-app-password"
SMTP_FROM_EMAIL = "portal@example.com"
SMTP_USE_SSL = "false"
```

Port 587 uses STARTTLS by default. Set `SMTP_USE_SSL` to `"true"` for
an SSL connection such as port 465. The notification includes the
employee name and ID, leave type, dates, working days, day portion,
reason, and request ID. If delivery fails, the leave request remains
saved and the employee sees an explicit warning.

#### `session.py` — "who is signed in"
Small helpers so an employee page only ever sees that employee's row.
* **Functions:** `signed_in_employee_id`, `employee_details`,
  `require_employee`.
* **Imports:** `streamlit`, `database.connection`.

#### `profile.py` — employee self-service
Employees view and edit their own personal details, and add, change or
remove their **profile photo** — the upload/remove controls sit **right
under the picture**. The upload control is a **plain button**: the
uploader lives in a `profile_photo_upload` container and `theme.py`
strips Streamlit's dashed "drag and drop" box (and its size note) so
only the Upload button shows.
* **Framing:** once an image is chosen the screen adds **Zoom**,
  **Move left / right**, **Move up / down** and **Straighten** controls
  plus a live **round preview**, so the employee frames the shot before
  saving (the values are passed to `avatar.process_upload`).
* **Functions:** `show_my_profile`, `_render_profile_view`,
  `_render_profile_editor`, `_render_photo_editor`, `_save_profile`,
  `_update_profile`.
* **Imports:** `datetime`, `json`, `streamlit`, `database.connection`,
  `modules.session.signed_in_employee_id`, `modules.avatar`.

#### `avatar.py` — profile photos
Keeps each employee's **profile picture** as a small square JPEG in the
`employees.photo` column (a BLOB), so the picture travels with a backup
and leaves no stray files behind.
* `process_upload` flips the image the right way up (EXIF), then crops
  square and resizes it to 400px. It also takes the **framing** the
  employee chose on "My details" —
  `zoom` (1.0 fits the shorter side), `offset_x` / `offset_y`
  (slide the picture left–right and up–down) and `rotation`
  (whole quarter turns). Called with no framing it is a plain
  centre crop, exactly as before.
* `save_avatar` / `clear_avatar` / `get_avatar` read and write the BLOB.
* `render_avatar` draws a circle: the photo when there is one, otherwise
  coloured **initials** from `initials()`. Used by the sidebar and the
  "My details" screen. `render_preview` / `preview_html` do the same for
  raw bytes, so the photo editor can show a live **round preview**.
* **Imports:** `base64`, `io`, `streamlit`, `database.connection`;
  `from PIL import Image, ImageOps` inside `process_upload`.

#### `my_overview.py` — employee home
The employee's dashboard. It opens with a personalised welcome
hero, then an **identity card** (photo, name, role, employment-type
and how long they have been with the company), two rows of figures —
pay on top (Annual CTC, Net monthly, PF balance) and everyday
things underneath (Leave balance, Attendance this month, Next
holiday) — then a **Projects** card listing what HR has assigned,
a **leave block**
("Leave this year" usage bars next
to "Recent leave"), a **Latest payslip** card with **View payslip** and
**Download PDF** actions, and a closing note about
where to edit personal details. Employee shortcuts are available from
the **Quick Links** page; Pazcare **Sign In** remains a separate link under
**Health Benefits** in the sidebar. Settings appears at the bottom of
the sidebar.
* **Function:** `show_portal_home()`, plus helpers `_profile_card`,
  `_key_figures`, `_at_a_glance`, `_leave_breakdown`, `_recent_leave`,
  `_latest_payslip`, `_tenure`, `_plural`, and `_working_days_to_date`.
* **Imports:** `datetime`, `streamlit`, `modules.attendance.get_attendance`,
  `modules.avatar.render_avatar`, `modules.epfo.epfo_statement`,
  `modules.holidays` (`holiday_dates`, `upcoming_holidays`),
  `modules.leave` (`STATUS_COLORS`, `format_range`, `get_balance`,
  `get_requests`), `modules.payslip` (`get_employees_with_salary`,
  `latest_payslip`), `modules.projects.render_my_projects`,
  `modules.salary`,
  `modules.session.require_employee`, `modules.theme.hero`.
* **Note:** attendance compares present / work-from-home days (half days
  count as 0.5) against this month's working days **so far**, so the
  figure stays fair mid-month. Shortcut cards on the Quick Links page
  set `st.session_state.current_page` to the destination id defined in
  `main.py`, then rerun the app.

#### `accounts.py` — HR user accounts
HR view for the portal's user accounts.
* **Function:** `show_accounts_page()`.
* **Imports:** `streamlit`, `modules.auth`.

#### `database_viewer.py` — table browser (HR)
Read-only viewer of any database table, using pandas to render it.
* **Functions:** `_list_tables`, `_read_table`, `_schema`,
  `show_database_page`.
* **Imports:** `os`, `pandas as pd`, `streamlit`, `database.connection`.

---

## 6. How to run it

From the project root, in the `hr_poc` environment:

```powershell
python -m streamlit run app\main.py
```

Then open http://localhost:8501 in a browser.

* **HR login:** username `hr`
* **Employee login:** Employee ID + password

To add the OpenAI key, create `.streamlit/secrets.toml` with:

```toml
OPENAI_API_KEY = "sk-..."
```

---

## 7. Quick "what was built" summary

| Area | Status |
|---|---|
| Employee records (create/edit/delete) | Done |
| Salary from Annual CTC + auto statutory split | Done |
| Payslips (monthly, LOP, PDF download) | Done |
| PF / EPFO statement (both roles) | Done |
| Income tax — Form 16 (AI reads the name) + monthly TDS estimate | Done |
| Leave (types, balances, approvals) | Done |
| Attendance (employee self-marking + HR daily register, holiday-aware) | Done |
| Holiday calendar (current-year only) | Done |
| Company assets (register, assign/return, employee view) | Done |
| POSH policy (read-only page, editable text file) | Done |
| Reimbursements (employee uploads a bill → HR approves, pays) | Done |
| Salary revisions (history + rescale) | Done |
| Full & final settlement (+ PDF) | Done |
| Employee profile photo (self-service, with zoom/pan adjust, sidebar avatar) | Done |
| Notifications (sidebar bell, HR + employee inboxes) | Done |
| AI offer-letter importer | Done |
| AI resume analyzer (HR only — match scores + shortlist) | Done |
| AI HR assistant (popup bot on every page, answers + applies leave) | Done |
| AI features grouped in their own **AI Assist** sidebar block (assistant / offer letter / resume) | Done |
| Sidebar split into **collapsible** blocks (HR: Workspace / AI Assist / Payroll / Time Off & Workplace / Admin) | Done |
| Official UMANG and EPFO Passbook links in Payroll sidebar section | Done |
| Zoho Accounts sign-in link for Zoho Payroll in Payroll sidebar section | Done |
| Assistant launcher floats bottom-right of the window (78px, robot face with eyes, verified in a real browser) | Done |
| Theming (warm neutral and emerald palette, charcoal sidebar, animations) | Done |
| ML / uploads / tests | Not started (empty folders) |
