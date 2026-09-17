import requests
import re
import sqlite3
import time
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://www.fipavbarifoggia.it/gare"
STAGIONE_ID = "2272"
COMITATO_ID = "10"
DB_NAME = "fipav.db"
MAX_WORKERS = 10

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def inizializza_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS campionati (
            id TEXT PRIMARY KEY,
            nome TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS classifica (
            campionato_id TEXT,
            pos INTEGER,
            squadra TEXT,
            punti INTEGER,
            PRIMARY KEY (campionato_id, squadra)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS partite (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campionato_id TEXT,
            giornata TEXT,
            numero_gara TEXT,
            data_ora TEXT,
            squadra_casa TEXT,
            squadra_ospite TEXT,
            risultato TEXT,
            parziali TEXT
        )
    ''')
    conn.commit()
    conn.close()

def ottieni_lista_campionati():
    url = f"{BASE_URL}?stagioneId={STAGIONE_ID}&ComitatoId={COMITATO_ID}"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200: return []
        soup = BeautifulSoup(response.text, 'html.parser')
        select = soup.find('select', {'id': 'campionatoId'}) or soup.find('select', {'name': 'campionatoId'})
        campionati = []
        if select:
            for opt in select.find_all('option'):
                cid = opt.get('value', '').strip()
                nome = opt.get_text(strip=True)
                if cid and cid != '0':
                    campionati.append({'id': cid, 'nome': nome})
        return campionati
    except Exception as e:
        print(f"Errore recupero campionati: {e}")
        return []

def pulisci_testo(testo):
    if not testo: return ""
    return re.sub(r'\s+', ' ', testo).strip()

def estrai_dati_campionato(campionato):
    campionato_id = campionato['id']
    # statoGara vuoto per scaricare l'intero calendario senza filtri
    url = f"{BASE_URL}?stagioneId={STAGIONE_ID}&dataDa=&statoGara=&campionatoId={campionato_id}&societaId=&ComitatoId={COMITATO_ID}"
    classifica = []
    partite = []

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200: 
            return campionato_id, classifica, partite

        soup = BeautifulSoup(response.text, 'html.parser')
        tabelle = soup.find_all('table')

        # 1. CLASSIFICA
        if len(tabelle) > 0:
            for riga in tabelle[0].find_all('tr'):
                celle = [pulisci_testo(td.get_text()) for td in riga.find_all(['td', 'th'])]
                if len(celle) >= 3 and celle[0].isdigit():
                    try:
                        classifica.append((campionato_id, int(celle[0]), celle[1], int(celle[2])))
                    except ValueError:
                        continue

        # 2. PARTITE
        if len(tabelle) > 1:
            righe = tabelle[1].find_all('tr')
            
            for i, riga in enumerate(righe):
                celle = [pulisci_testo(td.get_text()) for td in riga.find_all(['td', 'th'])]
                
                if len(celle) < 2 or not re.search(r'Gara|G\.', celle[0], re.IGNORECASE):
                    continue

                info_raw = celle[0]
                squadre_raw = celle[1]

                # --- Parsing Info (Giornata, Gara N., Data/Ora) ---
                giornata, num_gara, data_ora = "Generica", "", ""
                m_info = re.search(r'(G\.\s*\d+)\s*-\s*Gara\s*n\.\s*(\d+)\s*(.*)', info_raw, re.IGNORECASE)
                if m_info:
                    giornata = m_info.group(1).replace(" ", "")
                    num_gara = m_info.group(2)
                    data_ora = m_info.group(3).strip()
                else:
                    giornata = info_raw if info_raw else "Generica"

                # --- Parsing Squadre e Risultato ---
                sq_casa, sq_ospite, risultato = "", "", "VS"

                m_played = re.search(r'^(.*?)\s+([0-3])\s*(?:VS|-|–)\s*([0-3])\s+(.*?)$', squadre_raw, re.IGNORECASE)
                if m_played:
                    sq_casa = m_played.group(1).strip()
                    res_casa = m_played.group(2)
                    res_ospite = m_played.group(3)
                    sq_ospite = m_played.group(4).strip()
                    risultato = f"{res_casa} - {res_ospite}"
                else:
                    m_future = re.search(r'^(.*?)\s+(?:VS|-|–)\s+(.*?)$', squadre_raw, re.IGNORECASE)
                    if m_future:
                        sq_casa = m_future.group(1).strip()
                        sq_ospite = m_future.group(2).strip()
                        risultato = "Da Giocare"
                    else:
                        sq_casa = squadre_raw
                        sq_ospite = "N/D"
                        risultato = "N/D"

                # --- Parsing Parziali ---
                parziali = ""
                if i + 1 < len(righe):
                    riga_next = [pulisci_testo(td.get_text()) for td in righe[i+1].find_all(['td', 'th'])]
                    testo_next = " ".join(riga_next)
                    m_sets = re.findall(r'\b\d{1,2}[-\/]\d{1,2}\b', testo_next)
                    if m_sets:
                        parziali = " ".join(m_sets)

                partite.append((campionato_id, giornata, num_gara, data_ora, sq_casa, sq_ospite, risultato, parziali))

    except Exception as e:
        print(f"Errore su {campionato['nome']}: {e}")

    return campionato_id, classifica, partite

def main():
    inizio = time.time()
    inizializza_db()
    
    print("Recupero elenco campionati...")
    campionati = ottieni_lista_campionati()
    if not campionati:
        print("Nessun campionato trovato.")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM campionati")
    cursor.execute("DELETE FROM classifica")
    cursor.execute("DELETE FROM partite")
    
    for camp in campionati:
        cursor.execute("INSERT INTO campionati (id, nome) VALUES (?, ?)", (camp['id'], camp['nome']))
    conn.commit()

    print(f"Trovati {len(campionati)} campionati. Scaricamento ed estrazione...")
    
    tutte_classifiche, tutte_partite = [], []
    completati = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(estrai_dati_campionato, camp): camp for camp in campionati}
        
        for future in as_completed(futures):
            _, classifica, partite = future.result()
            tutte_classifiche.extend(classifica)
            tutte_partite.extend(partite)
            
            completati += 1
            if completati % 20 == 0 or completati == len(campionati):
                print(f"Avanzamento: {completati}/{len(campionati)} campionati...")

    print("Salvataggio nel database...")
    cursor.executemany(
        "INSERT OR REPLACE INTO classifica (campionato_id, pos, squadra, punti) VALUES (?, ?, ?, ?)",
        tutte_classifiche
    )
    cursor.executemany(
        """INSERT INTO partite 
           (campionato_id, giornata, numero_gara, data_ora, squadra_casa, squadra_ospite, risultato, parziali) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        tutte_partite
    )
    
    conn.commit()
    conn.close()

    fine = time.time()
    print(f"\nCompletato in {round(fine - inizio, 2)}s! Salvate {len(tutte_partite)} partite.")

if __name__ == "__main__":
    main()