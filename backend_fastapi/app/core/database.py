
import sqlite3

from pathlib import Path
from contextlib import closing
from datetime import datetime, timezone

from app.models.reading import ReadingCreate


# Localizacao do banco de dados

BASE_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = BASE_DIR / "data"

DB_PATH = DATA_DIR / "medidor.db"


# Abre uma conexao com o banco

def get_connection():

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH, timeout=10)

    connection.row_factory = sqlite3.Row

    return connection


# Cria a tabela de medicoes

def init_db():

    with closing(get_connection()) as connection:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS readings (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                device_id TEXT NOT NULL,

                sensor TEXT NOT NULL,

                temperature_c REAL NOT NULL,

                humidity_pct REAL NOT NULL,

                pressure_hpa REAL NOT NULL,

                gas_resistance_ohm REAL NOT NULL,

                received_at TEXT NOT NULL

            )
        """)

        connection.commit()


# Armazena uma nova medicao

def save_reading(reading: ReadingCreate):

    received_at = datetime.now(timezone.utc).isoformat()

    with closing(get_connection()) as connection:

        cursor = connection.execute("""

            INSERT INTO readings (

                device_id,
                sensor,
                temperature_c,
                humidity_pct,
                pressure_hpa,
                gas_resistance_ohm,
                received_at

            )

            VALUES (?, ?, ?, ?, ?, ?, ?)

        """, (

            reading.device_id,
            reading.sensor,
            reading.temperature_c,
            reading.humidity_pct,
            reading.pressure_hpa,
            reading.gas_resistance_ohm,
            received_at

        ))

        connection.commit()

        row = connection.execute(

            "SELECT * FROM readings WHERE id = ?",

            (cursor.lastrowid,)

        ).fetchone()

        return dict(row)


# Consulta o historico de medicoes

def get_readings(limit: int = 50):

    with closing(get_connection()) as connection:

        rows = connection.execute("""

            SELECT * FROM readings

            ORDER BY id DESC

            LIMIT ?

        """, (limit,)).fetchall()

        return [dict(row) for row in rows]


# Consulta a medicao mais recente

def get_latest_reading():

    with closing(get_connection()) as connection:

        row = connection.execute("""

            SELECT * FROM readings

            ORDER BY id DESC

            LIMIT 1

        """).fetchone()

        return dict(row) if row else None
