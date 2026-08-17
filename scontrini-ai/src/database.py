"""
Modulo di accesso al database Supabase (Postgres) per il salvataggio e la
lettura degli scontrini.

Le credenziali vengono lette da st.secrets (mai hardcoded):
SUPABASE_URL, SUPABASE_KEY (vedi .streamlit/secrets.toml).

Schema atteso su Supabase:
- scontrini(id, negozio, data [nullable], data_raw [text], totale_dichiarato,
  stato_validazione, creato_il)
  stato_validazione ∈ {'valido', 'da_rivedere'} (vincolo CHECK)
  data è NULL quando la stringa estratta non è una data calendaristica valida;
  data_raw contiene sempre la stringa originale così com'è stata estratta.
- prodotti(id, scontrino_id [FK -> scontrini.id], nome, quantita, prezzo_unitario,
  prezzo_totale, categoria, tipo)
  tipo ∈ {'prodotto', 'sconto'} — 'sconto' per righe di sconto/rettifica, che
  possono avere prezzo_totale negativo.
"""

from datetime import datetime

import streamlit as st
from supabase import Client, create_client

_client: Client | None = None


def get_client() -> Client:
    """Crea e restituisce il client Supabase usando le credenziali da st.secrets."""
    global _client
    if _client is None:
        supabase_url = st.secrets.get("SUPABASE_URL")
        supabase_key = st.secrets.get("SUPABASE_KEY")
        if not supabase_url or not supabase_key:
            raise RuntimeError(
                "SUPABASE_URL/SUPABASE_KEY non impostate. Controlla .streamlit/secrets.toml."
            )
        _client = create_client(supabase_url, supabase_key)
    return _client


def save_scontrino(dati: dict, is_valid: bool) -> int:
    """Salva uno scontrino (validato o da rivedere) e i suoi prodotti nel database.

    Logica di quarantena: qualsiasi scontrino viene salvato indipendentemente
    dall'esito della validazione — se non valido, viene marcato 'da_rivedere'
    per revisione umana, mai scartato.

    Args:
        dati: dizionario con i dati estratti dello scontrino (output di
            extract_receipt), con negozio, data, totale_dichiarato, prodotti.
        is_valid: esito della validazione (output di validate()).

    Returns:
        L'id dello scontrino appena inserito.

    Raises:
        RuntimeError: se l'inserimento nel database fallisce.
    """
    client = get_client()
    stato_validazione = "valido" if is_valid else "da_rivedere"

    data_raw = dati.get("data")
    data_valida = None
    if isinstance(data_raw, str):
        try:
            datetime.strptime(data_raw, "%Y-%m-%d")
            data_valida = data_raw
        except ValueError:
            data_valida = None

    try:
        risposta_scontrino = (
            client.table("scontrini")
            .insert(
                {
                    "negozio": dati.get("negozio"),
                    "data": data_valida,
                    "data_raw": data_raw,
                    "totale_dichiarato": dati.get("totale_dichiarato"),
                    "stato_validazione": stato_validazione,
                }
            )
            .execute()
        )
    except Exception as e:
        raise RuntimeError(f"Errore durante il salvataggio dello scontrino: {e}") from e

    scontrino_id = risposta_scontrino.data[0]["id"]

    prodotti = dati.get("prodotti", [])
    if prodotti:
        righe_prodotti = []
        for prodotto in prodotti:
            tipo_raw = prodotto.get("tipo")
            if tipo_raw not in ("prodotto", "sconto"):
                print(f"[WARNING] Campo 'tipo' non valido/mancante: {tipo_raw!r} per prodotto "
                      f"'{prodotto.get('nome')}' — normalizzato a 'prodotto' come fallback.")
                tipo_normalizzato = "prodotto"
            else:
                tipo_normalizzato = tipo_raw

            righe_prodotti.append(
                {
                    "scontrino_id": scontrino_id,
                    "nome": prodotto.get("nome"),
                    "quantita": prodotto.get("quantita"),
                    "prezzo_unitario": prodotto.get("prezzo_unitario"),
                    "prezzo_totale": prodotto.get("prezzo_totale"),
                    "categoria": prodotto.get("categoria"),
                    "tipo": tipo_normalizzato,
                }
            )
        try:
            client.table("prodotti").insert(righe_prodotti).execute()
        except Exception as e:
            raise RuntimeError(
                f"Errore durante il salvataggio dei prodotti dello scontrino {scontrino_id}: {e}"
            ) from e

    return scontrino_id


def get_all_scontrini() -> list[dict]:
    """Recupera tutti gli scontrini salvati, con i relativi prodotti annidati.

    Non filtra per stato_validazione: restituisce sia gli scontrini 'valido'
    che quelli 'da_rivedere' — il filtro è responsabilità di chi chiama questa
    funzione (dashboard di spesa, vista "da rivedere", ecc.).

    Returns:
        Lista di dizionari, uno per scontrino, ciascuno con una chiave
        "prodotti" contenente la lista dei prodotti associati.

    Raises:
        RuntimeError: se la lettura dal database fallisce.
    """
    client = get_client()

    try:
        risposta = client.table("scontrini").select("*, prodotti(*)").execute()
    except Exception as e:
        raise RuntimeError(f"Errore durante la lettura degli scontrini: {e}") from e

    return risposta.data
