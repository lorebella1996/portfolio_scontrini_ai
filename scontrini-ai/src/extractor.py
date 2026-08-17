"""
Modulo di estrazione dati strutturati da immagini di scontrini/ricevute
tramite Google Gemini API (vision).
"""

import json

import streamlit as st
from google import genai
from PIL import Image

MODEL_NAME = "gemini-2.5-flash"  # veloce ed economico, adatto a questo task

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = st.secrets.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY non impostata. Controlla .streamlit/secrets.toml."
            )
        _client = genai.Client(api_key=api_key)
    return _client


EXTRACTION_PROMPT = """Sei un sistema di estrazione dati da scontrini/ricevute italiani.
Analizza l'immagine e restituisci SOLO un oggetto JSON valido (nessun testo prima o dopo,
nessun blocco markdown ```), con questa struttura esatta:

{
  "negozio": "nome dell'esercizio commerciale",
  "data": "YYYY-MM-DD",
  "prodotti": [
    {
      "nome": "descrizione del prodotto/servizio",
      "quantita": numero,
      "prezzo_unitario": numero,
      "prezzo_totale": numero,
      "categoria": "una tra: Ristorazione, Alimentari, Abbigliamento, Farmacia, Trasporti, Casa & Bricolage, Bellezza & Cura personale, Tempo libero, Tabacchi, Altro"
    }
  ],
  "totale_dichiarato": numero
}

REGOLE IMPORTANTI per casi ambigui, molto comuni sugli scontrini reali:

1. Se la quantità è scritta DENTRO la descrizione (es. "3 X COPERTO", "2 X PANINO"),
   estrai il moltiplicatore come "quantita" e ripulisci il "nome" (es. "Coperto", non
   "3 X COPERTO"). Se il prezzo totale della riga è 0, imposta anche prezzo_unitario a 0
   (non lasciare vuoto, non inventare un valore).

2. Se sotto una riga prodotto compare una riga separata tipo "* 2 X 2,50" (dettaglio di
   come è composto il prezzo), NON creare un prodotto nuovo per quella riga: usala per
   arricchire il prodotto immediatamente precedente con la quantità e il prezzo unitario
   corretti (verifica che quantità × prezzo unitario torni vicino al prezzo totale già
   letto per quella riga).

3. Se lo scontrino non elenca prodotti veri ma solo codici generici (es. "REPARTO 1",
   "REPARTO 2"), usa quel testo così com'è come "nome" (non inventare un nome di prodotto
   plausibile), quantita 1, categoria "Altro" se non è deducibile dal contesto/nome negozio.

4. Le date possono comparire in formati diversi (GG/MM/AA, GG/MM/AAAA, GG-MM-AAAA):
   normalizza sempre in "YYYY-MM-DD".

5. Se un campo non è determinabile con certezza, usa 0 per i numeri o stringa vuota per
   il testo — non inventare mai dati plausibili ma non presenti sullo scontrino.

6. Se una parola risulta visivamente spezzata su due righe per mancanza di spazio 
   (es. "AC" a fine riga e "QUA" sulla riga successiva, che insieme formano "ACQUA"), 
   ricostruisci la parola intera nel campo "nome" — non lasciarla troncata a metà.

Rispondi ESCLUSIVAMENTE con il JSON, nient'altro.
"""


def extract_receipt(image: Image.Image) -> dict:
    """Estrae i dati strutturati da un'immagine di scontrino.

    Args:
        image: immagine dello scontrino (PIL.Image).

    Returns:
        dict con i dati estratti secondo lo schema documentato in EXTRACTION_PROMPT.

    Raises:
        ValueError: se la risposta del modello non è un JSON valido.
    """
    client = _get_client()

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[EXTRACTION_PROMPT, image],
        )
    except genai.errors.ClientError as e:
        if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e):
            raise RuntimeError(
                "Limite giornaliero del servizio AI raggiunto. Riprova più tardi "
                "(la quota si resetta ogni 24 ore)."
            ) from e
        raise

    testo_risposta = response.text.strip()

    # Pulizia difensiva: a volte i modelli aggiungono blocchi markdown
    # anche quando gli si chiede esplicitamente di non farlo.
    if testo_risposta.startswith("```"):
        testo_risposta = testo_risposta.split("\n", 1)[1]
        if testo_risposta.rstrip().endswith("```"):
            testo_risposta = testo_risposta.rstrip()[:-3]
        testo_risposta = testo_risposta.strip()

    try:
        dati = json.loads(testo_risposta)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Risposta del modello non è un JSON valido: {e}\n"
            f"Risposta grezza: {testo_risposta[:500]}"
        )

    for prodotto in dati.get("prodotti", []):
        if isinstance(prodotto.get("nome"), str):
            prodotto["nome"] = prodotto["nome"].strip().title()

    return dati
