import pandas as pd
import sqlite3

DB = "parkeeruitzonderingen.db"

def conn():
    return sqlite3.connect(DB)

df = pd.read_excel("met gps.xlsx")

c = conn()
for _, r in df.iterrows():
    c.execute("""
        INSERT OR REPLACE INTO parkeervakken
        (vak_id, straat, district, latitude, longitude)
        VALUES (?,?,?,?,?)
    """, (
        int(r["shape_id"]),
        r["street"],
        r["district"],
        float(r["latitude"]),
        float(r["longitude"])
    ))

c.commit()
c.close()

print("✅ parkeervakken geïmporteerd")
