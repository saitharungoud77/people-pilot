"""Patch assistant.py system prompt to use new leave type names."""
with open('app/modules/assistant.py', 'r', encoding='utf-8') as f:
    content = f.read()

replacements = [
    (
        'apply for leave ("apply casual leave next monday").',
        'apply for leave ("apply general leave next monday").',
    ),
    (
        '("apply casual leave next monday", "book sick leave tomorrow"), call',
        '("apply general leave next monday", "book sick leave tomorrow"), call',
    ),
    (
        '- If they do not name a leave type, apply_leave uses Casual Leave; say',
        '- If they do not name a leave type, apply_leave uses General Leave; say',
    ),
    (
        '  "Apply casual leave next monday",',
        '  "Apply general leave next monday",',
    ),
]

for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        print(f"Replaced: {old[:60]}...")
    else:
        print(f"NOT FOUND: {old[:60]}...")

with open('app/modules/assistant.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done.")

