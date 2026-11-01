import csv
import mysql.connector
from datetime import datetime

CSV_FILE = r"C:\Users\Ankushh\Downloads\9ef84268-d588-465a-a308-a864a43d0070.csv"

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "Ankush@123",
    "database": "kisan_mitra",
}

conn = mysql.connector.connect(**DB_CONFIG)
cursor = conn.cursor()

sql = """
INSERT INTO mandi_prices (
    state,
    district,
    market,
    commodity,
    variety,
    grade,
    arrival_date,
    min_price,
    max_price,
    modal_price
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

rows = []

with open(CSV_FILE, "r", encoding="utf-8-sig", newline="") as file:
    reader = csv.DictReader(file)

    print("CSV columns:")
    print(reader.fieldnames)

    for row in reader:

        date_value = row.get("Arrival_Date", "").strip()

        if date_value:
            try:
                arrival_date = datetime.strptime(
                    date_value,
                    "%d/%m/%Y"
                ).date()
            except ValueError:
                arrival_date = None
        else:
            arrival_date = None

        def number(value):
            value = (value or "").strip()

            if not value:
                return None

            try:
                return float(value)
            except ValueError:
                return None

        rows.append((
            row.get("State", "").strip(),
            row.get("District", "").strip(),
            row.get("Market", "").strip(),
            row.get("Commodity", "").strip(),
            row.get("Variety", "").strip(),
            row.get("Grade", "").strip(),
            arrival_date,
            number(row.get("Min_x0020_Price")),
            number(row.get("Max_x0020_Price")),
            number(row.get("Modal_x0020_Price")),
        ))

print(f"Prepared {len(rows)} records.")

cursor.executemany(sql, rows)
conn.commit()

print(f"Imported {cursor.rowcount} mandi records successfully.")

cursor.close()
conn.close()