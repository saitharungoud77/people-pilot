"""
Systematic removal of casual emojis across all app python files.
Replaces emojis with clean, corporate, professional wording.
Preserves Python code indentation exactly.
"""
import os
import re

# Specific string replacements to preserve exact text quality
REPLACEMENTS = [
    # Payslip actions
    ("🙈 Hide details", "Hide details"),
    ("👁️ View payslip", "View payslip"),
    ("👁 View payslip", "View payslip"),
    ("⬇️ Download PDF", "Download PDF"),
    ("⬇️ Download Payslip (PDF)", "Download Payslip (PDF)"),
    ("⬇️ Download Form 16", "Download Form 16"),
    ("⬇️ Download this Form 16", "Download this Form 16"),
    ("⚡ Generate all payslips", "Generate all payslips"),
    ("✏️ Edit this payslip", "Edit this payslip"),
    ("💾 Save Payslip", "Save Payslip"),
    ("🕒 Recent Payslips", "Recent Payslips"),
    
    # Employee actions
    ("➕ Add Employee", "Add Employee"),
    ("➕ Add New Employee", "Add New Employee"),
    ("👥 View Employees", "View Employees"),
    ("👥 Employee Records", "Employee Records"),
    ("🔍 Search Employee", "Search Employee"),
    ("✏️ Edit Employee", "Edit Employee"),
    ("💾 Save Employee", "Save Employee"),
    ("💾 Update Employee", "Update Employee"),
    ("✅ Employee added successfully!", "Employee added successfully!"),
    ("✅ Yes, delete", "Yes, delete"),
    ("🗑️ Delete", "Delete"),
    
    # Salary actions
    ("➕ Create / Update Salary Structure", "Create / Update Salary Structure"),
    ("📋 Salary Structures", "Salary Structures"),
    ("🔍 Search by Employee Name", "Search by Employee Name"),
    ("⚙️ Statutory auto-generation settings", "Statutory auto-generation settings"),
    ("🔄 Auto-fill from CTC while editing.", "Auto-fill from CTC while editing."),
    ("🔄 Auto-fill from CTC", "Auto-fill from CTC"),
    ("Saved salary structure. Click ✏️ Edit to ", "Saved salary structure. Click Edit to "),
    ("Click ✏️ Edit to adjust them, ", "Click Edit to adjust them, "),
    ("✏️ Edit Salary Details", "Edit Salary Details"),
    ("✏️ Edit Salary Components", "Edit Salary Components"),
    ("💾 Update Salary Structure", "Update Salary Structure"),
    
    # AI Modules
    ("✨ Extract with AI", "Extract with AI"),
    ("💾 Create employee", "Create employee"),
    ("✨ Build the role pack", "Build the role pack"),
    ("✨ Build the interview kit", "Build the interview kit"),
    ("🎯 Role pack", "Role pack"),
    ("🗣️ Interview kit", "Interview kit"),
    ("🗣 Interview kit", "Interview kit"),
    ("➕ Screen new resumes", "Screen new resumes"),
    ("✨ Analyze resumes", "Analyze resumes"),
    ("👥 Screened candidates", "Screened candidates"),
    ("🗑 Clear all candidates", "Clear all candidates"),
    ("💾 Save decisions", "Save decisions"),
    ("🗑 Remove this candidate", "Remove this candidate"),
    ("✨ Draft the letter", "Draft the letter"),
    ("✨ Write the AI brief", "Write the AI brief"),
    ("✨ Read bill with AI", "Read bill with AI"),
    ("**✅ Matched skills**", "**Matched skills**"),
    ("**⚠️ Missing skills**", "**Missing skills**"),
    
    # Dashboard / application.py
    ("💼 Workforce & People", "Workforce & People"),
    ("💰 Payroll, PF & Taxes", "Payroll, PF & Taxes"),
    ("🤖 AI Intelligence Hub", "AI Intelligence Hub"),
    ("⏱️ Time, Leave & Claims", "Time, Leave & Claims"),
    ("**⚡ Quick Operations**", "**Quick Operations**"),
    ("👤 Add Employee", "Add Employee"),
    ("⚡ 1-Click Payroll", "1-Click Payroll"),
    ("📅 Leave Desk", "Leave Desk"),
    ("🧾 Review Claims", "Review Claims"),
    ("🤖 Launch Assist", "Launch Assist"),
    ("##### 📅 Upcoming Corporate Holidays", "##### Upcoming Corporate Holidays"),
    ("##### 🛡️ Governance & Statutory Compliance", "##### Governance & Statutory Compliance"),
    
    # Profile & Revisions & Settlement
    ("✏️ Edit personal details", "Edit personal details"),
    ("➕ Add family member", "Add family member"),
    ("💾 Save changes", "Save changes"),
    ("💾 Save settlement & mark exit", "Save settlement & mark exit"),
    ("✅ Apply revision", "Apply revision"),
    ("🏛️ EPFO — Contribution & Balance", "EPFO — Contribution & Balance"),
    
    # Common buttons
    ("✖ Cancel", "Cancel"),
    ("✏️ Edit", "Edit"),
    ("🗑️", "Delete"),
    ("🗑 Remove", "Remove"),
    
    # Database viewer
    ('"employees": "👨‍💼 Employees"', '"employees": "Employees"'),
    ('"salary_structures": "💰 Salary Structures"', '"salary_structures": "Salary Structures"'),
    ('"payslips": "📄 Payslips"', '"payslips": "Payslips"'),
    ('st.caption(f"📁 {DATABASE_NAME}")', 'st.caption(f"{DATABASE_NAME}")'),
    ('🧱 Table schema', 'Table schema'),
    ('🔍 Run a read-only SQL query', 'Run a read-only SQL query'),
    
    # Tax module
    ("✅ Issue the selected Form 16s", "Issue the selected Form 16s"),
    ("✅ Issued", "Issued"),
    ("➕ Upload Form 16 files", "Upload Form 16 files"),
    ("🔍 Read & match", "Read & match"),
    ("📄 Issued Form 16s", "Issued Form 16s"),
    
    # Leave module
    ('<span style="font-size:20px;">🗓️</span> ', ''),
    ('<span style="font-size:20px;">🗓️</span>', ''),
    ('<span>🗓️</span> ', ''),
    ('<span>🗓️</span>', ''),
    ('<span>📋</span> ', ''),
    ('<span>📋</span>', ''),
    ('<span>✉️</span> ', ''),
    ('<span>✉️</span>', ''),
    ('📖 Leave Policy', 'Leave Policy'),
    
    # Assistant
    ('👋  How can I help you today?', 'How can I help you today?'),
    ('👋 How can I help you today?', 'How can I help you today?'),
    
    # Main page icon
    ('page_icon="🏢"', 'page_icon=":material/business:"'),
    
    # Headings with person icon
    ("### 👤 ", "### "),
    ("👤 ", ""),
    ("⚠️ ", ""),
    ("⚠️", ""),
]

# Specific tuple fixes in resume_analyzer & tax
CODE_TUPLE_FIXES = [
    ('(85, "Perfect fit", "🟢")', '(85, "Perfect fit", "")'),
    ('(70, "Strong match", "🟢")', '(70, "Strong match", "")'),
    ('(50, "Possible fit", "🟠")', '(50, "Possible fit", "")'),
    ('(0, "Not a fit", "🔴")', '(0, "Not a fit", "")'),
    ('return "Not a fit", "🔴"', 'return "Not a fit", ""'),
    ('return "High", "🟢"', 'return "High", ""'),
    ('return "Medium", "🟠"', 'return "Medium", ""'),
    ('return "Low", "🔴"', 'return "Low", ""'),
    ('return "No match", "⚪"', 'return "No match", ""'),
    ('"emoji": "⚪"', '"emoji": ""'),
    ('emoji = match.get("emoji", "⚪")', 'emoji = match.get("emoji", "")'),
    ("{emoji} {score}/100", "{score}/100"),
    ("{emoji} {row['candidate_name']}", "{row['candidate_name']}"),
    ('📞 {member.get(\'phone\')}', 'Phone: {member.get(\'phone\')}'),
    ('line += f" · 📞 {member.get(\'phone\')}"', 'line += f" · Phone: {member.get(\'phone\')}"'),
    ('f"✅ {employee_name}', 'f"{employee_name}'),
]

# Any remaining raw emojis (preserving Rupee symbol \u20B9)
EMOJI_REGEX = re.compile(
    r'[\U00010000-\U0010ffff]'
    r'|[\u2600-\u27BF]'
    r'|[\u2B00-\u2BFF]'
    r'|[\u2300-\u23FF]'
)

def strip_emojis_from_string(s):
    def repl(m):
        c = m.group(0)
        if ord(c) == 0x20B9:  # Keep ₹
            return c
        return ""
    return EMOJI_REGEX.sub(repl, s)

def process_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    orig = content

    # 1. Apply code tuple and structure fixes
    for old, new in CODE_TUPLE_FIXES:
        content = content.replace(old, new)

    # 2. Apply text and button replacements
    for old, new in REPLACEMENTS:
        content = content.replace(old, new)

    # 3. Strip any remaining emojis
    content = strip_emojis_from_string(content)

    if content != orig:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False

def main():
    changed = []
    for root, dirs, files in os.walk('app'):
        if '__pycache__' in root:
            continue
        for file in files:
            if file.endswith('.py'):
                p = os.path.join(root, file)
                if process_file(p):
                    changed.append(p)
                    print(f"Updated: {p}")
    print(f"\nCompleted! Removed emojis from {len(changed)} files.")

if __name__ == "__main__":
    main()
