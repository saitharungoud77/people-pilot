#!/usr/bin/env python3
"""Regenerate "AI HR Payroll Details.md" from the codebase.

Run it by hand:

    python scripts/update_ai_hr_payroll_details.py

Or let the app do it: app/main.py calls refresh_if_changed() on every
rerun, so the document updates itself the next time you open or click
anything in the portal after changing code.

The generator only uses the Python standard library. It reads the real
files (routes, sidebar, tables, packages, AI models) and combines that
with the short hand-written descriptions further down this file, so the
document can never drift far from what is actually running.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

DOC = ROOT / "AI HR Payroll Details.md"

STATE = Path(__file__).resolve().parent / ".details_state.json"


# ============================================================
# CURATED KNOWLEDGE
# ============================================================
# Everything below is written by hand. When a new feature lands, add
# a module row, an AI feature row and a build-history line here - the
# rest of the document is generated.


TIMELINE = [
    ("1", "Base portal",
     "Streamlit app with HR and employee roles, SQLite database, "
     "employee records, salary split from annual CTC and monthly "
     "payslips with PDF download."),
    ("2", "One file per feature",
     "The code was split into app/modules (one file per feature), "
     "with main.py only assembling the app. CODE_GUIDE.md explains "
     "every file in plain English."),
    ("3", "Cleaner HR dashboard",
     "Charts were removed from the HR dashboard; it now shows a "
     "welcome header, key numbers and module cards."),
    ("4", "Payroll depth",
     "Salary revisions that rescale every component, full and final "
     "settlement, LOP handling and the PF/EPFO statement redesign."),
    ("5", "AI offer-letter importer",
     "Upload an offer letter; OpenAI reads it and drafts the employee "
     "record, salary structure and optional login."),
    ("6", "Single sign-in",
     "One form for everyone. Employee ID or username is used to work "
     "out whether the person is HR or an employee."),
    ("7", "AIT Assist",
     "A floating AI assistant on every page with database-backed tools: "
     "it books leave, checks balances, finds records and answers policy "
     "questions. Conversations are isolated per signed-in person."),
    ("8", "AI resume analyzer",
     "HR sets the required skills, uploads resumes, and gets a match "
     "score, a verdict and a shortlist decision. HR only."),
    ("9", "Profile photos",
     "Employees upload, adjust (zoom, position, rotate), preview and "
     "remove their own profile photo."),
    ("10", "Tax and Form 16",
     "Form 16 and monthly TDS workspace, old vs new regime comparison, "
     "and AI name matching when several Form 16 files are uploaded at "
     "once so each one reaches the right employee."),
    ("11", "Workplace modules",
     "Holiday calendar (current year), leave history, employee "
     "overview, company assets and the read-only POSH policy."),
    ("12", "Calm violet design",
     "One accent colour, light sidebar, soft cards, subtle motion and "
     "collapsible sidebar blocks grouped around how people work."),
    ("13", "Reimbursements",
     "Employees upload bills, HR approves them, marks them paid and "
     "keeps the receipt attached to the claim."),
    ("14", "Corporate attendance",
     "Clock in and out with Office or Work From Home, late and half-day "
     "rules, a daily HR register, and past days locked to employees."),
    ("15", "Corporate leave",
     "Leave counted in working days (Mon-Fri minus holidays), policy "
     "checks before a request is created, half-days, approval notes and "
     "team coverage."),
    ("16", "Full-screen sign-in",
     "A full-viewport split sign-in page: the story panel on the left, "
     "the sign-in card on the right, and copy that leads with the two "
     "things the product is built around - AI and time saved."),
    ("17", "Second AI wave",
     "AI payroll audit, AI bill reader, AI letter generator and the AI "
     "hiring pack. They are grouped in the AIT Assist sidebar block, "
     "next to the assistant, offer letter and resume analyzer."),
    ("18", "Shift timings by client / project",
     "HR creates one shift per client or project, assigns employees to it, "
     "and attendance, late marks, half-days and the break deduction follow "
     "each person's own shift."),
    ("19", "One-click payroll",
     "HR generates a whole month of payslips in one click, edits any "
     "component before saving, and payroll closes automatically after a "
     "saved final settlement so no payslip is created afterwards."),
    ("20", "This document",
     "AI HR Payroll Details.md plus the generator that keeps it in "
     "step with the code, wired into app/main.py."),
    ("21", "Month-end payroll release",
     "Payslips use calendar-day proration for new joiners, show paid and "
     "working days and the scheduled pay date, and release after month end "
     "(the preceding Friday for weekends). The app and a daily Windows "
     "task catch up every missing due period from each employee's joining "
     "month, even while the portal is closed. PF uses saved released "
     "payslips only."),
]


STACK = [
    ("Application shell", "Streamlit", "streamlit==1.65.0",
     "Free, open source",
     "One Python codebase for UI, forms, charts and session state. The "
     "whole team already works in Python, so there is no separate "
     "front-end build, API layer or JavaScript toolchain to maintain for "
     "an internal HR tool.",
     "React or Next.js (free, far more code), Django or Flask with Jinja "
     "templates (free, more wiring), Microsoft Power Apps (paid per "
     "user), Retool (paid per user)."),
    ("Database", "SQLite", "built into Python",
     "Free",
     "Zero setup, one file, easy to back up by copying database/"
     "hr_payroll.db. A small company has tens of employees, not "
     "millions of rows, so a client-server database adds cost and "
     "operational work with no benefit.",
     "PostgreSQL or MySQL (free, needs a server), Supabase or Neon "
     "(free tier, paid plans), Amazon RDS (paid), Firebase (free tier, "
     "paid plans)."),
    ("AI provider", "OpenAI API", "openai==3.31.0",
     "Paid per token (usage based)",
     "One SDK and one key cover all seven AI features: structured JSON "
     "for forms, vision for bill photos, and tool calling for the "
     "assistant. JSON mode returns parseable objects, which is what "
     "makes the offer letter, resume, letter and audit features "
     "reliable.",
     "Anthropic Claude (paid per token, excellent writing), Google "
     "Gemini (free tier plus paid), Azure OpenAI (paid, enterprise data "
     "residency), OpenRouter (paid, one key for many models), local "
     "Ollama or Llama (free, private, needs a capable machine)."),
    ("PDF reading", "PyMuPDF", "PyMuPDF==1.28.2",
     "Free for open source; AGPL licence - commercial licence needed "
     "if you distribute closed-source software",
     "Fast, accurate text extraction with no Java or system packages. "
     "It reads offer letters, resumes and text-based bills.",
     "pdfplumber (free, slower), PyPDF2 or pypdf (free, weaker layout "
     "handling), pdfminer.six (free), Tesseract OCR (free, needed for "
     "scanned PDFs), Azure Document Intelligence or Google Document AI "
     "(paid, best OCR)."),
    ("PDF writing", "fpdf2", "fpdf2==2.8.9",
     "Free, open source",
     "Small, pure Python and good enough for clean A4 payslips, "
     "settlement statements and letters. It ships the rupee glyph when "
     "Arial is available.",
     "ReportLab (free core, paid add-ons), WeasyPrint (free, HTML to "
     "PDF), Puppeteer with headless Chrome (free, heavier), DocuSign or "
     "Adobe Sign (paid, for e-signature rather than generation)."),
    ("Image handling", "Pillow", "Pillow==12.3.0",
     "Free, open source",
     "Profile photo crop, rotate and compress, and bill photos are "
     "shrunk before they are sent to the vision model to keep requests "
     "small.",
     "ImageMagick (free, needs system install), OpenCV (free, much "
     "heavier), browser-side canvas (free, but needs JavaScript)."),
    ("Tables in the admin view", "pandas", "pandas==3.0.6",
     "Free, open source",
     "st.dataframe expects a DataFrame for sorting and column widths; "
     "pandas is already the standard choice and comes with Streamlit.",
     "Plain lists of dicts (free, fewer features), Polars (free, "
     "faster for big data), AG Grid (free community edition, paid "
     "enterprise)."),
    ("Authentication", "Custom PBKDF2-SHA256",
     "Python standard library",
     "Free",
     "One internal login, no third-party dependency, no per-user fee. "
     "Passwords are salted and hashed with 200k PBKDF2 rounds, never "
     "stored in plain text.",
     "Auth0 or Okta (paid per user, free dev tier), Clerk (free tier, "
     "paid growth), Firebase Auth (free tier), Microsoft Entra ID "
     "(paid per user), Google Workspace SSO (paid per user)."),
    ("Secrets", "secrets.toml + environment variables",
     "Python standard library",
     "Free",
     "Keys stay out of the repository. The app looks in the project "
     ".streamlit/secrets.toml, then the user's home .streamlit/"
     "secrets.toml, then environment variables.",
     "HashiCorp Vault (free OSS, paid enterprise), AWS Secrets Manager "
     "(paid), Azure Key Vault (paid), Doppler (free tier, paid plans)."),
    ("Public URL", "Cloudflare quick tunnel", "cloudflared.exe",
     "Free",
     "Gives a working HTTPS address in seconds with no account, which "
     "is enough while the app is being reviewed. The address changes "
     "whenever the tunnel restarts and only works while this PC and the "
     "app are running.",
     "Cloudflare named tunnel with your own domain (free tunnel, domain "
     "cost), Render or Railway (free tier, paid plans), Fly.io (paid "
     "usage), Streamlit Community Cloud (free for public apps), AWS or "
     "Azure (paid)."),
    ("Testing", "Streamlit AppTest + headless Chrome over CDP",
     "streamlit built-in, websockets==17.2, Google Chrome",
     "Free",
     "AppTest runs the real pages without a browser and catches logic "
     "and render errors. Headless Chrome checks the CSS, layout and "
     "sign-in flow the way a person sees them. Both are test-only and "
     "not needed to run the app.",
     "Playwright (free, extra install), Selenium (free, extra install), "
     "Cypress (free OSS, paid cloud), BrowserStack (paid)."),
]


AI_FEATURES = [
    {
        "name": "AI offer-letter importer",
        "module": "offer_letter.py",
        "who": "HR",
        "what": (
            "HR uploads a PDF or pastes an offer letter. The model "
            "extracts the candidate's name, designation, department, "
            "joining date, CTC and personal details as JSON. HR reviews "
            "an editable preview; saving creates the employee record, "
            "the statutory salary structure and optionally a login."
        ),
        "why": (
            "Offer letters are semi-structured documents that change "
            "layout every time. Rules and regex break on the next "
            "template; a model with JSON mode handles the variation and "
            "returns exactly the keys the form needs."
        ),
        "guard": (
            "Temperature 0 and a fixed seed for repeatable output. "
            "Missing values are normalised to empty strings or zero, "
            "dates are converted to ISO, and nothing is saved until HR "
            "confirms the preview."
        )
    },
    {
        "name": "AIT Assist (the assistant on every page)",
        "module": "assistant.py",
        "who": "HR and employees",
        "what": (
            "A popup in the corner of every signed-in page. It answers "
            "policy questions from data/hr_policy.md and acts through "
            "fourteen database tools: who am I, employee lookup, salary "
            "structure, payslip, leave balance, attendance summary, PF "
            "summary, holidays, find employee, payroll summary, apply "
            "leave, list leave, cancel leave and approve or reject "
            "leave. Actions run immediately, without a confirmation "
            "step, as requested."
        ),
        "why": (
            "Tool calling is the difference between a chatbot that says "
            "'you can apply for leave' and one that actually files it. "
            "The model never writes SQL; Python resolves the signed-in "
            "person, checks permissions and calls the same functions "
            "the pages use."
        ),
        "guard": (
            "Every tool receives the signed-in user and resolves the "
            "target employee in Python. Employees can only touch their "
            "own records; HR tools are refused for employees. Answers "
            "come from tools and the policy file, not from the model's "
            "memory. Conversations are isolated by an owner id."
        )
    },
    {
        "name": "AI resume analyzer",
        "module": "resume_analyzer.py",
        "who": "HR",
        "what": (
            "HR enters a job title, the required skills and optional "
            "criteria, uploads PDF or text resumes, and the model scores "
            "each one out of 100 with matched skills, missing skills, "
            "strengths, gaps, a summary and a verdict. HR then marks "
            "candidates as shortlisted or rejected."
        ),
        "why": (
            "Reading fifty resumes against one skill list is slow and "
            "inconsistent. A model gives every resume the same rubric "
            "and returns structured fields the table can sort."
        ),
        "guard": (
            "The model is told to score only against the supplied "
            "requirements. The score is clamped to 0-100 and the verdict "
            "is derived from fixed bands, not invented. HR-only access "
            "is enforced twice: in the page and in the router."
        )
    },
    {
        "name": "AI Form 16 matching (tax)",
        "module": "tax.py",
        "who": "HR",
        "what": (
            "When HR uploads several Form 16 PDFs at once, the model "
            "reads the name and employee id on each document and "
            "matches it to the right employee, so every form is issued "
            "to the correct person instead of being filed by hand."
        ),
        "why": (
            "Form 16 files arrive from payroll software with different "
            "file names and layouts. Matching by text is far safer than "
            "matching by file name."
        ),
        "guard": (
            "A match is only accepted when a name or id is found in the "
            "document text; unmatched files are listed for HR to assign "
            "manually. The PDF itself is stored as a BLOB against the "
            "employee and financial year."
        )
    },
    {
        "name": "AI bill reader",
        "module": "bill_reader.py",
        "who": "Employees (inside reimbursements)",
        "what": (
            "The employee uploads a bill photo or a text-based PDF and "
            "clicks Read bill with AI. The model extracts the vendor, "
            "bill number, date, total, GST and category, and the claim "
            "form is prefilled for review."
        ),
        "why": (
            "A photo of a receipt has no machine-readable fields. A "
            "vision model reads the same image a person would, without "
            "an OCR pipeline or per-document templates."
        ),
        "guard": (
            "Photos are resized and recompressed before sending. Scanned "
            "PDFs with no text layer are refused with a clear message "
            "instead of sending a blank page. The category is snapped to "
            "the app's own list, GST cannot exceed the total, and a bill "
            "with no readable total is rejected for manual entry. The "
            "employee always reviews the values before submitting."
        )
    },
    {
        "name": "AI payroll audit",
        "module": "payroll_audit.py",
        "who": "HR",
        "what": (
            "Before payroll is locked, the audit compares every employee "
            "against their salary structure, payslip, attendance, "
            "approved Loss of Pay and PF rules. It flags missing "
            "payslips, stale payslips, LOP spikes, missing attendance, "
            "PF mismatches, impossible net pay, broken salary splits, "
            "missing salary structures and possible duplicate bills. "
            "The model then writes a short brief in plain English."
        ),
        "why": (
            "The checks themselves must be deterministic, so they are "
            "plain Python. The model is used only for the summary - "
            "turning a table of findings into a priority list a busy HR "
            "manager can act on."
        ),
        "guard": (
            "The model never decides whether something is wrong and "
            "never changes a number; it only reads the findings. The "
            "audit table and CSV work even without an API key. A month "
            "with no attendance rows skips the missing-attendance check "
            "so the report is not noise."
        )
    },
    {
        "name": "AI letter generator",
        "module": "letter_generator.py",
        "who": "HR",
        "what": (
            "Produces experience, relieving, salary certificate, "
            "employment verification and warning letters. Facts come "
            "from the database; the model can rewrite the wording. The "
            "letter is previewed and downloaded as a PDF."
        ),
        "why": (
            "HR writes the same letters repeatedly. Fixing the facts in "
            "Python removes the risk of a wrong salary in a bank letter, "
            "while the model removes the repetitive drafting."
        ),
        "guard": (
            "Every number in the AI text is compared with the facts and "
            "the standard draft. If the model introduces or changes a "
            "number, or drops the employee's name, the standard wording "
            "is used instead and HR sees why. Salary in words is "
            "generated in Indian lakh and crore format."
        )
    },
    {
        "name": "AI hiring pack",
        "module": "hiring_pack.py",
        "who": "HR",
        "what": (
            "Builds a role pack from a job title, department, seniority "
            "and optional notes: a job description, required and "
            "nice-to-have skills, screening questions and interview "
            "focus. One click carries the job title and skills into the "
            "resume analyzer. For a screened candidate it builds an "
            "interview kit with questions, gap probes, a scorecard and "
            "red flags."
        ),
        "why": (
            "The same skill list should drive the advert, the resume "
            "score and the interview. Generating them together keeps "
            "hiring consistent."
        ),
        "guard": (
            "The prompt forbids inventing salary, benefits or company "
            "facts, and forbids questions about age, gender, marital "
            "status, religion, caste, pregnancy or disability. The kit "
            "is built from the stored screening result, not from an "
            "imagined resume."
        )
    },
]


MODULES = {
    "auth.py": {
        "title": "Sign-in, sign-out and passwords",
        "who": "Public + both roles",
        "purpose": (
            "The single sign-in gate. One form checks the identifier "
            "(employee id or username) and sends HR and employees to "
            "their own home. Also handles sign-out, password change and "
            "the full-screen split sign-in page with the story panel."
        )
    },
    "config.py": {
        "title": "Secret lookup",
        "who": "Internal",
        "purpose": (
            "Finds OPENAI_API_KEY in the project .streamlit/secrets.toml, "
            "then the home .streamlit/secrets.toml, then the environment. "
            "Keeps keys out of source files."
        )
    },
    "session.py": {
        "title": "Session helpers",
        "who": "Internal",
        "purpose": (
            "require_employee() and employee_details() - small guards "
            "used by employee pages so a page can never run without a "
            "signed-in employee."
        )
    },
    "theme.py": {
        "title": "Design system",
        "who": "Both roles",
        "purpose": (
            "One global stylesheet: accent colour, cards, gradient hero, "
            "subtle motion, avatar and assistant styles. Colours and "
            "fonts themselves live in .streamlit/config.toml."
        )
    },
    "nav.py": {
        "title": "Sidebar navigation",
        "who": "Both roles",
        "purpose": (
            "Role-aware sidebar with collapsible blocks. AI features live "
            "together in the AIT Assist block. Also shows the avatar, "
            "sign out and change password."
        )
    },
    "notifications.py": {
        "title": "Notification bell",
        "who": "Both roles",
        "purpose": (
            "In-app notifications at the top right. One row per message, "
            "addressed either to HR or to one employee id. Emits messages "
            "when leave, bills, assets and approvals change."
        )
    },
    "home.py": {
        "title": "Landing splash",
        "who": "Public",
        "purpose": (
            "Branded splash screen shown before sign-in, with the "
            "product name and a way into the login."
        )
    },
    "application.py": {
        "title": "HR dashboard",
        "who": "HR",
        "purpose": (
            "The HR home: welcome header, headcount and payroll numbers, "
            "pending approvals, module cards and shortcuts into every "
            "screen."
        )
    },
    "my_overview.py": {
        "title": "Employee home",
        "who": "Employee",
        "purpose": (
            "The employee home: welcome header, latest payslip, leave "
            "balance, attendance snapshot and quick links to their own "
            "pages."
        )
    },
    "employee.py": {
        "title": "Employee records",
        "who": "HR",
        "purpose": (
            "Directory and full employee records: create and edit people, "
            "personal details, documents, project assignments and exit "
            "details."
        )
    },
    "salary.py": {
        "title": "Salary structures",
        "who": "HR writes, employee reads own",
        "purpose": (
            "Turns annual CTC into a statutory monthly split: basic, HRA, "
            "special allowance, other allowance, employee PF, employer PF "
            "and other deductions. PF can be applied on the EPFO ceiling "
            "or on full basic."
        )
    },
    "revisions.py": {
        "title": "Salary revisions",
        "who": "HR",
        "purpose": (
            "Records a new CTC and rescales every salary component, so a "
            "raise flows into future payslips without retyping the "
            "structure."
        )
    },
    "payslip.py": {
        "title": "Payslips",
        "who": "HR generates, employee reads own",
        "purpose": (
            "Builds monthly salary and PF using calendar-day proration, "
            "includes paid and holiday-aware working-day counts, and shows "
            "the scheduled pay date in the preview and PDF. Catches up all "
            "missing due months from the joining month through month end "
            "(or the preceding Friday on a weekend) through a daily "
            "Windows task and an app fallback. HR can generate a due "
            "month, edit components and payroll closes "
            "after settlement or exit. Employees see only saved, released "
            "payslips."
        )
    },
    "epfo.py": {
        "title": "Provident fund",
        "who": "Both roles",
        "purpose": (
            "PF/EPFO statement reads employee and employer contributions "
            "from saved, released payslips only. The balance is a running "
            "total of contributions, with no interest added; unreleased "
            "months are omitted and the statement is capped at the latest "
            "due period and the employee's exit or final-settlement month."
        )
    },
    "tax.py": {
        "title": "Income tax and Form 16",
        "who": "HR writes, employee reads own",
        "purpose": (
            "Form 16 and monthly TDS workspace, old vs new regime "
            "comparison, and bulk Form 16 upload with AI name matching so "
            "each PDF is issued to the right employee."
        )
    },
    "settlement.py": {
        "title": "Full and final settlement",
        "who": "HR",
        "purpose": (
            "Calculates what a leaver is owed: pending salary, leave "
            "encashment, notice recovery and other dues, with a PDF "
            "statement."
        )
    },
    "reimbursements.py": {
        "title": "Reimbursements and bills",
        "who": "Both roles",
        "purpose": (
            "Employees file expense claims with the bill attached; HR "
            "approves, rejects or marks them paid. The bill is stored as "
            "a BLOB inside the claim. The upload form can be prefilled by "
            "the AI bill reader."
        )
    },
    "bill_reader.py": {
        "title": "AI bill reader",
        "who": "Employee (inside reimbursements)",
        "purpose": (
            "Reads a bill photo or text-based PDF with OpenAI vision and "
            "returns vendor, bill number, date, total, GST, category and "
            "a short description for the claim form."
        )
    },
    "leave.py": {
        "title": "Leave desk",
        "who": "Both roles",
        "purpose": (
            "The corporate leave desk: leave types, yearly entitlements, "
            "balances, working-day counting, half-days, overlap and "
            "policy checks, approval with notes, cancellation, history "
            "and team coverage on the approval card."
        )
    },
    "workdays.py": {
        "title": "Working-day math",
        "who": "Internal",
        "purpose": (
            "One neutral module for questions like how many working days "
            "is this range. Counts Monday to Friday and skips public "
            "holidays, so leave, payslip LOP and the audit all agree."
        )
    },
    "attendance.py": {
        "title": "Attendance",
        "who": "Both roles",
        "purpose": (
            "Clock in and out with Office or Work From Home, late mark, "
            "half-day and full-day rules, break deduction, a daily HR "
            "register, and past days locked to employees. Clock-in is "
            "refused on weekends, holidays and approved leave."
        )
    },
    "shifts.py": {
        "title": "Shift timings",
        "who": "HR",
        "purpose": (
            "Create shifts per client or project, assign employees and notify "
            "them when moved. Attendance uses each person's own shift for "
            "late marks, half-days, the break deduction and the shift caption."
        )
    },
    "payroll_audit.py": {
        "title": "AI payroll audit",
        "who": "HR",
        "purpose": (
            "Pre-payroll checks across payslips, salary structures, "
            "attendance, leave, PF and bills, sorted by severity, with a "
            "CSV export and an AI-written brief."
        )
    },
    "holidays.py": {
        "title": "Holiday calendar",
        "who": "Both roles",
        "purpose": (
            "The current year's upcoming holiday list. Fixed national "
            "holidays plus the curated 2026 festival dates are seeded once "
            "per year; HR can add, edit or remove entries, and employees "
            "see a read-only calendar. Past holidays and future years are "
            "not shown."
        )
    },
    "assets.py": {
        "title": "Company assets",
        "who": "Both roles",
        "purpose": (
            "Assets issued to employees (laptop, phone, access card) with "
            "issue and return dates. HR manages the register; employees "
            "see what is issued to them."
        )
    },
    "projects.py": {
        "title": "Project assignments",
        "who": "HR writes, employee reads own",
        "purpose": (
            "The projects each employee is working on. HR assigns a "
            "project (name, role, status, start date, notes) and removes "
            "old ones; the employee sees the same list read-only on My "
            "overview and gets a notification when a project is assigned."
        )
    },
    "policies.py": {
        "title": "POSH policy",
        "who": "Both roles",
        "purpose": (
            "A read-only page showing the POSH policy from "
            "data/posh_policy.md."
        )
    },
    "profile.py": {
        "title": "My profile",
        "who": "Employee",
        "purpose": (
            "Employees maintain their own personal details and profile "
            "photo, including zoom, position and rotation before saving."
        )
    },
    "avatar.py": {
        "title": "Avatar",
        "who": "Both roles",
        "purpose": (
            "Renders a circular avatar from the stored photo, with "
            "initials as a fallback when there is no photo."
        )
    },
    "offer_letter.py": {
        "title": "AI offer-letter importer",
        "who": "HR",
        "purpose": (
            "Upload or paste an offer letter; AI extracts the employment "
            "terms into an editable preview; saving creates the employee, "
            "the salary structure and optionally the login."
        )
    },
    "resume_analyzer.py": {
        "title": "AI resume analyzer",
        "who": "HR",
        "purpose": (
            "Scores resumes against required skills, stores the results, "
            "and lets HR shortlist or reject candidates."
        )
    },
    "hiring_pack.py": {
        "title": "AI hiring pack",
        "who": "HR",
        "purpose": (
            "Generates a job description, skills and screening questions, "
            "sends the skills to the resume analyzer, and builds an "
            "interview kit for a screened candidate."
        )
    },
    "letter_generator.py": {
        "title": "AI letter generator",
        "who": "HR",
        "purpose": (
            "Drafts experience, relieving, salary, employment "
            "verification and warning letters from database facts, with "
            "optional AI polish and a number guard, then exports a PDF."
        )
    },
    "assistant.py": {
        "title": "AIT Assist popup",
        "who": "Both roles",
        "purpose": (
            "The floating assistant: a robot-head launcher, a small chat "
            "panel, policy answers and fourteen database tools that can "
            "actually perform actions."
        )
    },
    "accounts.py": {
        "title": "Login accounts",
        "who": "HR",
        "purpose": (
            "Creates and manages sign-in accounts, resets passwords and "
            "shows which employee id is linked to each account."
        )
    },
    "database_viewer.py": {
        "title": "Database viewer",
        "who": "HR",
        "purpose": (
            "Read-only browser over every table, useful for checking what "
            "the app actually stored."
        )
    },
    "__init__.py": {
        "title": "Package marker",
        "who": "Internal",
        "purpose": "Tells Python that app/modules is a package."
    },
}


TABLES = {
    "employees": "One row per person: identity, contact details, department, designation, joining and exit dates, CTC and the profile photo BLOB.",
    "salary_structures": "Annual salary components per employee: basic, HRA, special and other allowance, employee and employer PF, other deduction.",
    "payslips": "One row per employee per month: monthly components, gross, PF, deductions, net, LOP days and LOP amount.",
    "users": "Login accounts: username, password hash and salt, role and the linked employee id.",
    "leave_requests": "Every leave request: type, dates, working days, half-day portion, reason, manager/team email, status, decision note and who decided.",
    "leave_entitlements": "Yearly leave allowance per employee and leave type.",
    "attendance": "One row per employee per day: status, note, clock-in and clock-out time.",
    "holidays": "The public holiday calendar (date and name).",
    "holiday_seed": "Marker recording which years already received the default holiday list, so removed defaults stay removed.",
    "shifts": "Shift definitions per client/project (timings, grace, break, full/half-day hours).",
    "salary_revisions": "History of CTC changes per employee, with the old and new figures.",
    "settlements": "Full and final settlement records for leavers.",
    "candidates": "Screened resumes: job, required skills, candidate details, matched and missing skills, score, verdict, summary and HR decision.",
    "form16_documents": "Issued Form 16 PDFs as BLOBs, keyed by employee and financial year.",
    "notifications": "One row per in-app message, addressed to HR or to one employee id.",
    "assets": "Company assets issued to employees, with issue and return dates.",
    "employee_projects": "Project assignments per employee: project name, role, status, start date and notes.",
    "reimbursements": "Expense claims with the bill file stored as a BLOB, status, decision and paid date.",
    "employee_documents": "Employee-submitted education and employment documents stored as BLOBs with HR review status.",
}


PACKAGE_NOTES = {
    "streamlit": "The whole user interface and app runtime.",
    "pandas": "Powers the sortable tables (database viewer and interview scorecard).",
    "fpdf2": "Builds payslip, settlement and letter PDFs.",
    "PyMuPDF": "Extracts text from uploaded offer letters, resumes and text-based bills.",
    "Pillow": "Profile photo editing and shrinking bill photos before AI reading.",
    "openai": "Client for all AI calls: offer letter, resume, assistant, Form 16 matching, bill reader, audit brief, letters and hiring pack.",
}

DEV_TOOLS = [
    ("Streamlit AppTest", "Runs real pages headlessly to catch render and logic errors.",
     "Ships with Streamlit; test-only."),
    ("Headless Chrome + CDP", "Checks layout, computed CSS and the sign-in flow as a browser sees them.",
     "Chrome is free; the websockets client is dev-only."),
    ("cloudflared", "Free quick tunnel that gives the app a temporary public HTTPS URL.",
     "Free; URL changes each restart and needs this PC awake."),
    ("VS Code / any editor", "Editing the code.",
     "Free."),
]


FUTURE_PAID = [
    ("Hosting the app permanently",
     "Render, Railway, Fly.io, AWS, Azure or Streamlit Community Cloud",
     "A stable URL that stays up when this PC is off. Render and Railway "
     "have free tiers; production plans are paid. Streamlit Community "
     "Cloud is free for public apps and paid for private ones."),
    ("Managed database",
     "PostgreSQL on Neon, Supabase or Amazon RDS",
     "Concurrent users, automatic backups, point-in-time restore and no "
     "single-file risk. Free tiers exist; production is paid."),
    ("Higher AI limits and enterprise data terms",
     "OpenAI pay-as-you-go or Azure OpenAI",
     "Usage-based pricing already applies; a paid tier raises rate "
     "limits and Azure adds data residency and enterprise controls. "
     "The same code works - only the key and base URL change."),
    ("Real OCR for scanned documents",
     "Azure Document Intelligence, Google Document AI or AWS Textract",
     "Reads scanned bills, old Form 16 scans and photographed offer "
     "letters. Paid per page; far more accurate than sending an image "
     "to a general model."),
    ("Email and SMS notifications",
     "Resend, SendGrid, Amazon SES, Twilio or MSG91",
     "Sends the in-app notification out by email or SMS (useful for "
     "approvals and payslip release). Paid per message; free tiers "
     "exist."),
    ("Single sign-on",
     "Microsoft Entra ID, Google Workspace, Okta or Auth0",
     "Company SSO, MFA and automatic joiner/leaver handling. Paid per "
     "user; worth it once the team grows."),
    ("Commercial PDF licence",
     "Artifex commercial licence for PyMuPDF",
     "PyMuPDF is AGPL. If this app is distributed as closed-source "
     "software rather than used internally, a commercial licence is "
     "the clean option. Internal use does not trigger distribution."),
    ("Error monitoring and backups",
     "Sentry, Better Stack, S3 or Backblaze B2",
     "Catches production errors and keeps off-site database backups. "
     "Free developer tiers exist; production is paid."),
    ("E-signature for letters",
     "DocuSign, Adobe Sign or Zoho Sign",
     "Sends generated letters for signature and stores the signed "
     "copy. Paid per envelope."),
    ("Statutory filing integrations",
     "EPFO and income-tax filing utilities, or a payroll bureau API",
     "Automates PF ECR and TDS returns once volume justifies it. "
     "Usually paid per filing or per month."),
]


# ============================================================
# CODE READING
# ============================================================

def _read(path: Path) -> str:

    try:

        return path.read_text(encoding="utf-8", errors="replace")

    except OSError:

        return ""


def source_files():
    """Every file whose change should refresh the document."""

    files = []

    for folder in ("app", "database", "scripts"):

        files.extend(sorted((ROOT / folder).rglob("*.py")))

    for name in ("requirements", ".streamlit/config.toml"):

        path = ROOT / name

        if path.exists():

            files.append(path)

    files.extend(sorted((ROOT / "data").glob("*.md")))

    return [
        path
        for path in files
        if "__pycache__" not in str(path)
        and path.name != DOC.name
        and path.name != STATE.name
    ]


def signature():

    digest = hashlib.sha256()

    for path in source_files():

        stat = path.stat()

        digest.update(
            f"{path.relative_to(ROOT)}|{stat.st_mtime_ns}|{stat.st_size}\n"
            .encode("utf-8")
        )

    return digest.hexdigest()


def parse_routes(source):
    """(role, page id, handler) from the two PAGES dicts in main.py."""

    routes = []

    chunks = source.split("PAGES = {")[1:]

    for role, chunk in zip(("HR", "Employee"), chunks):
        role = role.strip()

        body = chunk.split("\n    }")[0]

        for match in re.finditer(
            r'"([a-z_]+)":\s*(lambda:[^\n]+|show_[a-z_]+)', body
        ):
            page = match.group(1)
            handler = match.group(2)
            name = re.search(r"(show_[a-z_]+)", handler)
            routes.append(
                (role, page, name.group(1) if name else handler.strip())
            )

    return routes


def parse_nav(source):
    """{role: [(group, [(label, page, icon), ...]), ...]}"""

    result = {}

    ai_block = "AIT Assist"
    m = re.search(r'^AI_BLOCK\s*=\s*"([^"]+)"', source, re.M)
    if m:
        ai_block = m.group(1)

    for role, marker, end in (
        ("HR", "HR_NAV = [", "EMPLOYEE_NAV"),
        ("Employee", "EMPLOYEE_NAV = [", "def render_sidebar")
    ):
        if marker not in source:

            continue

        block = source.split(marker, 1)[1]

        if end in block:

            block = block.split(end, 1)[0]

        block = block.replace("(AI_BLOCK,", f'("{ai_block}",')

        groups = []

        for group_match in re.finditer(
            r'\("([^"]+)", \[(.*?)\n    \]\),', block, re.S
        ):
            group = group_match.group(1)

            entries = []

            for entry in re.finditer(
                r'\("([^"]+)", (?:ASSISTANT_PAGE|"([^"]+)"), '
                r'"(:material/[^"]+)"\)',
                group_match.group(2)
            ):
                entries.append(
                    (
                        entry.group(1),
                        entry.group(2) or "assistant",
                        entry.group(3)
                    )
                )

            groups.append((group, entries))

        result[role] = groups

    return result


def parse_tables(source):
    """[(table, [columns])] from CREATE TABLE statements."""

    tables = []

    for match in re.finditer(
        r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\s*\)",
        source,
        re.S
    ):
        columns = []

        for line in match.group(2).splitlines():

            line = line.strip().rstrip(",")

            if not line:

                continue

            if line.upper().startswith(
                ("FOREIGN", "UNIQUE", "PRIMARY", "CHECK", "CONSTRAINT")
            ):

                continue

            parts = line.split(None, 1)

            if len(parts) == 2 and re.fullmatch(r"[a-z_]+", parts[0]):

                columns.append(parts[0])

        tables.append((match.group(1), columns))

    return tables


def parse_packages(source):
    """[(package, version)] from the requirements file."""

    packages = []

    for line in source.splitlines():

        line = line.strip()

        if not line or line.startswith("#"):

            continue

        match = re.match(r"([A-Za-z0-9_.-]+)==([^\s#]+)", line)

        if match:

            packages.append((match.group(1), match.group(2)))

    return packages


def module_stats():
    """[{name, lines, functions, ai, models, env}] for app/modules."""

    stats = []

    for path in sorted((ROOT / "app" / "modules").glob("*.py")):

        source = _read(path)

        functions = re.findall(r"^def (\w+)\(", source, re.M)

        models = sorted(set(re.findall(r'"(gpt-[A-Za-z0-9.\-]+)"', source)))

        env_vars = sorted(
            set(
                re.findall(
                    r'os\.environ\.get\(\s*"(OPENAI_[A-Z_]+)"',
                    source
                )
            )
        )

        stats.append(
            {
                "name": path.name,
                "lines": len(source.splitlines()),
                "functions": len(functions),
                "ai": "OpenAI(" in source or "from openai import" in source,
                "models": models,
                "env": env_vars
            }
        )

    return stats


def ai_models_by_module(stats):

    return {
        item["name"]: item
        for item in stats
        if item["ai"]
    }


# ============================================================
# RENDERING
# ============================================================


# ============================================================
# RENDERING
# ============================================================



# ============================================================
# RENDERING
# ============================================================


def render(data):

    stats = data["stats"]
    stat_map = {item["name"]: item for item in stats}
    ai_map = ai_models_by_module(stats)
    now = datetime.datetime.now().strftime("%d %B %Y, %I:%M %p")
    total_lines = sum(item["lines"] for item in stats)
    total_functions = sum(item["functions"] for item in stats)
    hr_routes = [r for r in data["routes"] if r[0] == "HR"]
    emp_routes = [r for r in data["routes"] if r[0] == "Employee"]
    lines = []
    add = lines.append

    add("# AI HR & Payroll Portal - Detailed Documentation")
    add("")
    add(f"**Generated on:** {now}")
    add("**Company:** AIT Solutions | **Location:** Hi-Tech City, Hyderabad")
    add("**Type:** AI-first HR & Payroll Portal (HR + Employees)")
    add("")
    add("> Auto-generated by scripts/update_ai_hr_payroll_details.py. Tables from code update automatically.")
    add("")
    add("---")
    add("")

    add("## 1. Quick Snapshot")
    add("")
    add("| Item | Value | Notes |")
    add("| --- | --- | --- |")
    add(f"| Modules in app/modules/ | {len(stats)} | One file per feature")
    add(f"| Total lines | {total_lines:,} | Auto-counted")
    add(f"| Total functions | {total_functions:,} | Auto-counted")
    add(f"| HR routes | {len(hr_routes)} | From app/main.py")
    add(f"| Employee routes | {len(emp_routes)} | From app/main.py")
    add(f"| DB tables | {len(data['tables'])} | From database/connection.py")
    add(f"| pip packages | {len(data['packages'])} | From requirements")
    add(f"| AI modules | {len(ai_map)} | OpenAI based")
    add("")
    add("---")
    add("")

    add("## 2. Build Order (First to Last)")
    add("")
    add("| Step | Milestone | What was done |")
    add("| --- | --- | --- |")
    for number, title, detail in TIMELINE:
        add(f"| {number} | {title} | {detail} |")
    add("")
    add("---")
    add("")

    add("## 3. Tools Used - Name | What it does | Free/Paid | Why we chose this")
    add("")
    add("### 3.1 Core Stack")
    add("")
    add("| Tool/Library | Version | Free/Paid | What it actually does | Why chosen over others |")
    add("| --- | --- | --- | --- | --- |")
    for layer, tool, version, billing, why, alternatives in STACK:
        add(f"| {tool} ({layer}) | {version} | {billing} | {why} | {alternatives} |")
    add("")
    add("### 3.2 pip Packages")
    add("")
    add("| Package | Version | Free/Paid | What it does here |")
    add("| --- | --- | --- | --- |")
    for package, version in data["packages"]:
        note = PACKAGE_NOTES.get(package, "Used by app")
        add(f"| {package} | {version} | FREE | {note} |")
    add("")
    add("### 3.3 Built-in (FREE)")
    add("sqlite3, datetime, calendar, json, os, re, csv, io, base64, math, hashlib, hmac, secrets, pathlib, sys, ast, tempfile, shutil, subprocess")
    add("")
    add("### 3.4 Dev/Testing/Tunnel")
    add("")
    add("| Tool | Free/Paid | What it does |")
    add("| --- | --- | --- |")
    for tool, why, billing in DEV_TOOLS:
        add(f"| {tool} | {billing} | {why} |")
    add("")
    add("> **Auth:** We did NOT use Google Sign-In/GSuite/SSO. Custom PBKDF2-HMAC-SHA256 with random salt, 200000 iterations in users table. FREE.")
    add("")
    add("---")
    add("")

    add("## 4. Flow: Sign-In -> End")
    add("")
    add("1. **Start** - app/main.py loads, init DB, auth setup, theme, auto-updater")
    add("2. **Login** - Full screen split login. Use Employee ID or Username + password. Verified by authenticate_any() with PBKDF2-SHA256 (200000). Routed by role.")
    add("3. **Inside** - Collapsible sidebar, AIT Assist block has all AI tools. A daily Windows task releases payroll at month end (or the preceding Friday for weekends); the app also checks for the latest due period. Bell + floating assistant shown.")
    add("4. **Logout** - Clears session")
    add("")
    add("---")
    add("")

    add("## 5. HR vs Employee")
    add("")
    add("### HR")
    add("| Area | Modules | Purpose |")
    add("| --- | --- | --- |")
    add("| Dashboard | application | Overview")
    add("| People | employee | Employee master")
    add("| AIT Assist | assistant, offer_letter, resume, hiring_pack, letters, payroll_audit | AI tools")
    add("| Pay & Benefits | salary, revisions, payslip, epfo, tax, reimbursements, settlement | Payroll/PF/Tax/Bills/Settlement")
    add("| Time & Workplace | leave, attendance, shifts, holidays, assets, policies | Leave/Attendance/Shift timings/Holidays/Assets/POSH")
    add("| Admin | accounts, database_viewer | Users/DB")
    add("")
    add("### Employee")
    add("| Area | Modules | Purpose |")
    add("| --- | --- | --- |")
    add("| Profile | application, profile | Overview + details + photo")
    add("| AIT Assist | assistant | Self help")
    add("| Pay & Benefits | salary, payslips, epfo, tax, reimbursements | Own data + AI bill reader")
    add("| Time & Workplace | leave, attendance, shifts, holidays, assets, policies | Leave/apply, clock in/out, view")
    add("")
    add("---")
    add("")

    add("## 6. AI Features")
    add("")
    add("**Billing:** OpenAI = PAID per token | Others FREE")
    add("")
    add("| # | Feature | File | Who | Model | Env | What it does | Why OpenAI | Guardrails |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for number, feature in enumerate(AI_FEATURES, start=1):
        info = ai_map.get(feature["module"], {})
        models = ", ".join(f"`{m}`" for m in info.get("models", [])) or "-"
        envv = ", ".join(f"`{e}`" for e in info.get("env", [])) or "-"
        add(f"| {number} | {feature['name']} | {feature['module']} | {feature['who']} | {models} | {envv} | {feature['what']} | {feature['why']} | {feature['guard']} |")
    add("")
    add("> resume_analyzer/tax use OPENAI_MODEL from offer_letter. assistant uses OPENAI_ASSISTANT_MODEL.")
    add("")
    add("---")
    add("")

    add("## 7. All Modules Explained")
    add("")
    add("| # | File | Lines | Funcs | AI | Title | Who | What it does | Free/Paid |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for number, item in enumerate(stats, start=1):
        name = item["name"]
        meta = MODULES.get(name, {"title": name, "who": "-", "purpose": "-"})
        ai = "YES" if item["ai"] else "NO"
        billing = "PAID (OpenAI)" if item["ai"] else "FREE"
        add(f"| {number} | {name} | {item['lines']:,} | {item['functions']} | {ai} | {meta['title']} | {meta['who']} | {meta['purpose']} | {billing} |")
    add("")
    add("---")
    add("")

    add("## 8. Routes & Sidebar")
    add("")
    add("### HR Routes")
    add("| Page ID | Handler |")
    add("| --- | --- |")
    for role, page, handler in hr_routes:
        add(f"| {page} | {handler} |")
    add("")
    add("### Employee Routes")
    add("| Page ID | Handler |")
    add("| --- | --- |")
    for role, page, handler in emp_routes:
        add(f"| {page} | {handler} |")
    add("")
    add("### Sidebar")
    add("")
    for role, groups in data["nav"].items():
        add(f"**{role}**")
        for group, entries in groups:
            items = " | ".join(f"{lbl} ({pg})" for lbl, pg, _ in entries)
            add(f"- {group}: {items}")
        add("")
    add("---")
    add("")

    add("## 9. Database Schema")
    add("")
    add("| # | Table | Columns | Purpose |")
    add("| --- | --- | --- | --- |")
    for number, (table, columns) in enumerate(data["tables"], start=1):
        note = TABLES.get(table, "Data")
        add(f"| {number} | {table} | {', '.join(columns)} | {note} |")
    add("")
    add("---")
    add("")

    add("## 10. Free/Paid + Future")
    add("")
    add("**FREE NOW:** Streamlit, SQLite, Custom PBKDF2 auth (NO Google/SSO), fpdf2, PyMuPDF, Pillow, pandas, all HR logic")
    add("")
    add("**PAID NOW:** OpenAI API (usage based)")
    add("")
    add("| Need | Option | Reason |")
    add("| --- | --- | --- |")
    for need, option, benefit in FUTURE_PAID:
        add(f"| {need} | {option} | {benefit} |")
    add("")
    add("**Tips:** use gpt-4o-mini/gpt-4.1-mini for bulk, gpt-4o only when needed")
    add("")
    add("---")
    add("")

    add("## 11. Auto Update")
    add("")
    add("- Auto: app/main.py calls refresh_if_changed() on rerun")
    add("- Manual: run scripts/update_ai_hr_payroll_details.py")
    add("- Reads: app/modules, app/main.py, nav.py, database/connection.py, requirements, .streamlit/config.toml, data/*.md")
    add("")
    add("*Clean order with tool names, purpose, free/paid.*")
    add("")

    return "\n".join(lines)




def _group_entries(nav, role, group_name):

    for group, entries in nav.get(role, []):

        if group == group_name:

            return entries

    return []


_ROUTE_NOTES = {
    "assistant": (
        "the floating popup with fourteen tools; it opens from the "
        "sidebar without leaving the current page."
    ),
    "offer_letter": (
        "upload or paste an offer letter; AI drafts the employee, salary "
        "and optional login."
    ),
    "resume": (
        "required skills plus resumes in, match score and verdict out, "
        "then a shortlist decision."
    ),
    "hiring_pack": (
        "job description, skills and screening questions, plus an "
        "interview kit per screened candidate."
    ),
    "letters": (
        "experience, relieving, salary, employment verification and "
        "warning letters, exported as PDF."
    ),
    "payroll_audit": (
        "pre-payroll checks with severities, CSV export and an AI brief."
    ),
}


def _route_note(page):

    return _ROUTE_NOTES.get(page, "see section 7 for the full description.")


# ============================================================
# ENTRY POINTS
# ============================================================

def collect():

    main_source = _read(ROOT / "app" / "main.py")

    nav_source = _read(ROOT / "app" / "modules" / "nav.py")

    connection_source = _read(
        ROOT / "database" / "connection.py"
    )

    requirements_source = _read(ROOT / "requirements")

    return {
        "stats": module_stats(),
        "routes": parse_routes(main_source),
        "nav": parse_nav(nav_source),
        "tables": parse_tables(connection_source),
        "packages": parse_packages(requirements_source)
    }


def regenerate():

    text = render(collect())

    DOC.write_text(text, encoding="utf-8")

    STATE.write_text(
        json.dumps({"signature": signature()}, indent=2),
        encoding="utf-8"
    )

    return DOC


def refresh_if_changed(root=None):
    """Regenerate only when a source file changed. Never raises.

    Used by app/main.py so the document follows the code without a
    manual step.
    """

    try:

        current = signature()

        previous = ""

        if STATE.exists():

            try:

                previous = json.loads(
                    STATE.read_text(encoding="utf-8")
                ).get("signature", "")

            except (OSError, ValueError):

                previous = ""

        if current == previous and DOC.exists():

            return False

        regenerate()

        return True

    except Exception:  # noqa: BLE001 - documentation must never break the app

        return False


def main():

    changed = not DOC.exists() or signature() != _state_signature()

    path = regenerate()

    size = path.stat().st_size

    print(f"{'updated' if changed else 'refreshed'}: {path}")
    print(f"{size:,} bytes")


def _state_signature():

    if not STATE.exists():

        return ""

    try:

        return json.loads(STATE.read_text(encoding="utf-8")).get(
            "signature", ""
        )

    except (OSError, ValueError):

        return ""


if __name__ == "__main__":

    main()
