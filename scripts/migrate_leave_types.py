"""
One-shot migration: move from old leave types to new corporate leave types.
Run once after deploying the updated leave.py.
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from database.connection import DATABASE_NAME

FEMALE_NAMES = {
    'naveena', 'priya', 'ananya', 'meera', 'sneha', 'ishita',
    'neha', 'pooja', 'deepika', 'swathi', 'shreya', 'divya',
    'aarti', 'anjali', 'lakshmi', 'radha', 'geeta', 'sunita',
    'rekha', 'meena', 'pallavi', 'bhavana', 'sravani', 'ramya',
    'lavanya', 'keerthi', 'harini', 'sushma', 'meghana', 'aditi',
    'rupa', 'nisha', 'tanvi', 'aishwarya', 'smitha', 'preethi',
    'mary', 'sarah', 'kavya', 'fatima'
}


def is_female(name, gender):
    if (gender or '').strip().lower() in ('female', 'f', 'woman', 'girl'):
        return True
    first = (name or '').strip().split()[0].lower().rstrip('.')
    return first in FEMALE_NAMES


con = sqlite3.connect(DATABASE_NAME, timeout=60)
cur = con.cursor()

print("Step 1: Removing Earned Leave entitlements...")
cur.execute("DELETE FROM leave_entitlements WHERE leave_type = 'Earned Leave'")

print("Step 2: Migrating Casual Leave to General Leave in entitlements...")
cur.execute(
    "UPDATE leave_entitlements SET leave_type='General Leave', entitled=12 "
    "WHERE leave_type='Casual Leave'"
)

print("Step 3: Migrating Casual Leave to General Leave in requests...")
cur.execute(
    "UPDATE leave_requests SET leave_type='General Leave' "
    "WHERE leave_type='Casual Leave'"
)

print("Step 4: Fixing Sick Leave entitled from 12 to 3...")
cur.execute(
    "UPDATE leave_entitlements SET entitled=3 "
    "WHERE leave_type='Sick Leave' AND entitled=12"
)

print("Step 5: Migrating Earned Leave requests to General Leave...")
cur.execute(
    "UPDATE leave_requests SET leave_type='General Leave' "
    "WHERE leave_type='Earned Leave'"
)

print("Step 6: Upserting all employees with new leave entitlements for 2026...")
employees = cur.execute(
    "SELECT employee_id, employee_name, gender FROM employees"
).fetchall()

YEAR = 2026

for eid, name, gen in employees:
    fem = is_female(name, gen)
    pat_days = 180 if fem else 7
    entitlements = [
        ("General Leave",    12),
        ("Sick Leave",       3),
        ("Optional Leave",   2),
        ("Bereavement Leave", 7),
        ("Paternity Leave",  pat_days),
        ("Loss of Pay",      0),
    ]
    for lt, days in entitlements:
        cur.execute(
            "INSERT OR REPLACE INTO leave_entitlements "
            "(employee_id, leave_type, year, entitled) VALUES (?, ?, ?, ?)",
            (eid, lt, YEAR, days)
        )
    gender_label = "Female" if fem else "Male"
    print(f"  {eid}: {name} ({gender_label}) — Paternity: {pat_days} days")

con.commit()
con.close()

print("\nMigration complete!")
