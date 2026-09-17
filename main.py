from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sqlite3

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "fipav.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/campionati")
def get_campionati():
    conn = get_db_connection()
    campionati = conn.execute("SELECT id, nome FROM campionati ORDER BY nome").fetchall()
    conn.close()
    return [dict(c) for c in campionati]

@app.get("/api/campionato/{campionato_id}")
def get_dettaglio_campionato(campionato_id: str):
    conn = get_db_connection()
    
    classifica = conn.execute(
        "SELECT pos, squadra, punti FROM classifica WHERE campionato_id = ? ORDER BY pos ASC",
        (campionato_id,)
    ).fetchall()
    
    partite = conn.execute(
        """SELECT giornata, numero_gara, data_ora, squadra_casa, squadra_ospite, risultato, parziali 
           FROM partite WHERE campionato_id = ? ORDER BY id ASC""",
        (campionato_id,)
    ).fetchall()
    
    conn.close()
    
    return {
        "classifica": [dict(c) for c in classifica],
        "partite": [dict(p) for p in partite]
    }