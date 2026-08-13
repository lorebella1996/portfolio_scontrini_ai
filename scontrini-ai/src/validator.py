"""
Modulo di validazione dei dati estratti da uno scontrino.
"""

from datetime import datetime

TOLLERANZA = 0.05


def validate(dati: dict) -> tuple[bool, list[str]]:
    """Valida i dati estratti da uno scontrino.

    Args:
        dati: dizionario con i dati estratti (output di extract_receipt).

    Returns:
        Tupla (is_valid, note) dove note è una lista di messaggi relativi
        a eventuali problemi riscontrati. (True, []) solo se non ci sono note.
    """
    note: list[str] = []

    # 1. Campi obbligatori

    negozio = dati.get("negozio")
    if not isinstance(negozio, str) or not negozio.strip():
        note.append("Il campo 'negozio' è mancante o vuoto.")

    data = dati.get("data")
    if not isinstance(data, str) or not data.strip():
        note.append("Il campo 'data' è mancante o vuoto.")
    else:
        try:
            datetime.strptime(data, "%Y-%m-%d")
        except ValueError:
            note.append(
                f"Il campo 'data' ('{data}') non è una data valida nel formato YYYY-MM-DD."
            )

    prodotti = dati.get("prodotti")
    if not isinstance(prodotti, list) or len(prodotti) == 0:
        note.append("Il campo 'prodotti' è mancante o è una lista vuota.")
        prodotti = []

    totale_dichiarato = dati.get("totale_dichiarato")
    if not isinstance(totale_dichiarato, (int, float)) or isinstance(
        totale_dichiarato, bool
    ) or totale_dichiarato <= 0:
        note.append(
            f"Il campo 'totale_dichiarato' ('{totale_dichiarato}') deve essere un numero maggiore di zero."
        )
        totale_dichiarato = None

    # 2. Coerenza per singolo prodotto

    somma_prodotti = 0.0
    somma_valida = True

    for i, prodotto in enumerate(prodotti):
        nome = prodotto.get("nome", f"riga {i + 1}")
        quantita = prodotto.get("quantita")
        prezzo_unitario = prodotto.get("prezzo_unitario")
        prezzo_totale = prodotto.get("prezzo_totale")

        campi_numerici_ok = True
        for campo, valore in (
            ("quantita", quantita),
            ("prezzo_unitario", prezzo_unitario),
            ("prezzo_totale", prezzo_totale),
        ):
            if not isinstance(valore, (int, float)) or isinstance(valore, bool):
                note.append(
                    f"Prodotto '{nome}': il campo '{campo}' ('{valore}') non è un numero valido."
                )
                campi_numerici_ok = False

        if not campi_numerici_ok:
            somma_valida = False
            continue

        if quantita <= 0:
            note.append(f"Prodotto '{nome}': la quantità ({quantita}) deve essere maggiore di zero.")

        if prezzo_unitario < 0:
            note.append(
                f"Prodotto '{nome}': il prezzo unitario ({prezzo_unitario}) non può essere negativo."
            )

        if prezzo_totale < 0:
            note.append(
                f"Prodotto '{nome}': il prezzo totale ({prezzo_totale}) non può essere negativo."
            )

        if prezzo_totale != 0:
            atteso = quantita * prezzo_unitario
            if abs(atteso - prezzo_totale) > TOLLERANZA:
                note.append(
                    f"Prodotto '{nome}': quantità × prezzo unitario "
                    f"({quantita} × {prezzo_unitario:.2f} = {atteso:.2f}) non corrisponde "
                    f"al prezzo totale dichiarato ({prezzo_totale:.2f})."
                )

        somma_prodotti += prezzo_totale

    # 3. Coerenza globale

    if totale_dichiarato is not None and somma_valida and prodotti:
        if abs(somma_prodotti - totale_dichiarato) > TOLLERANZA:
            note.append(
                f"La somma dei prezzi totali dei prodotti ({somma_prodotti:.2f}) non "
                f"corrisponde al totale dichiarato dello scontrino ({totale_dichiarato:.2f})."
            )

    return (len(note) == 0, note)
