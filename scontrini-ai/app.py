"""
Entry point dell'app Streamlit "scontrini-ai".

Struttura UI a due tab:
1. Upload scontrino + visualizzazione del JSON estratto (Gemini).
2. Dashboard di spesa personale (grafici a partire dai dati salvati).
"""

from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from PIL import Image

from src.database import get_all_scontrini, save_scontrino
from src.extractor import extract_receipt
from src.validator import validate

COLORE_ACCENTO = "#4F8BF9"  # stesso primaryColor di .streamlit/config.toml
DIMENSIONE_FONT_GRAFICI = 14  # più leggibile del default (~12) quando il grafico si restringe

st.set_page_config(page_title="Scontrini AI", page_icon="🧾", layout="wide")

st.title("🧾 Scontrini AI")

tab_upload, tab_dashboard = st.tabs(["Upload scontrino", "Dashboard di spesa"])

with tab_upload:
    st.header("Carica uno scontrino")

    uploaded_file = st.file_uploader(
        "Carica una foto dello scontrino", type=["png", "jpg", "jpeg"]
    )

    if uploaded_file is not None:
        st.image(uploaded_file, caption="Scontrino caricato", width=300)

        # Streamlit riesegue l'intero script ad ogni interazione (es. click su
        # "Conferma e salva"). Per non ripetere una chiamata a Gemini ad ogni
        # rerun, l'estrazione viene fatta una sola volta per file caricato:
        # confrontiamo il file_id univoco assegnato da Streamlit con quello
        # dell'ultimo file già processato, salvato in session_state.
        if st.session_state.get("scontrino_file_id") != uploaded_file.file_id:
            st.session_state["scontrino_file_id"] = uploaded_file.file_id
            st.session_state["scontrino_dati"] = None
            st.session_state["scontrino_valido"] = None
            st.session_state["scontrino_note"] = None
            st.session_state["scontrino_errore"] = None
            st.session_state["scontrino_salvato_id"] = None

            with st.spinner("Estrazione dati in corso..."):
                try:
                    image = Image.open(uploaded_file)
                    dati = extract_receipt(image)
                except Exception as e:
                    st.session_state["scontrino_errore"] = str(e)
                else:
                    is_valid, note = validate(dati)
                    st.session_state["scontrino_dati"] = dati
                    st.session_state["scontrino_valido"] = is_valid
                    st.session_state["scontrino_note"] = note

        if st.session_state.get("scontrino_errore"):
            st.error(
                f"Errore durante l'estrazione dei dati: {st.session_state['scontrino_errore']}"
            )
        elif st.session_state.get("scontrino_dati") is not None:
            dati = st.session_state["scontrino_dati"]
            is_valid = st.session_state["scontrino_valido"]
            note = st.session_state["scontrino_note"]

            st.subheader("Dati estratti")
            st.json(dati)

            if is_valid:
                st.success("Dati coerenti, pronti per il salvataggio.")
            else:
                messaggio_note = "\n".join(f"- {n}" for n in note)
                st.warning(
                    "Sono state rilevate incoerenze nei dati estratti. Lo scontrino "
                    "verrà comunque salvato, ma segnalato per revisione:\n\n"
                    f"{messaggio_note}"
                )

            scontrino_salvato_id = st.session_state.get("scontrino_salvato_id")
            if scontrino_salvato_id is not None:
                st.success(f"Scontrino già salvato nel database con id {scontrino_salvato_id}.")
            else:
                if st.button("Conferma e salva"):
                    try:
                        nuovo_id = save_scontrino(dati, is_valid)
                    except Exception as e:
                        st.error(f"Errore durante il salvataggio: {e}")
                    else:
                        st.session_state["scontrino_salvato_id"] = nuovo_id
                        st.rerun()

with tab_dashboard:
    st.header("Dashboard di spesa")

    scontrini = get_all_scontrini()

    if not scontrini:
        st.info("Nessun dato disponibile, carica il tuo primo scontrino dal tab Upload.")
    else:
        # Tabella "piatta" prodotto × scontrino: base unica condivisa da tutti
        # i visual sotto, così i filtri applicati una volta sola determinano
        # coerentemente KPI, grafici e tabella di revisione.
        righe = []
        for s in scontrini:
            data_str = s.get("data")
            data_valida = None
            if isinstance(data_str, str):
                try:
                    data_valida = datetime.strptime(data_str, "%Y-%m-%d").date()
                except ValueError:
                    data_valida = None

            for p in s.get("prodotti", []):
                categoria = p.get("categoria")
                if not categoria or not str(categoria).strip():
                    categoria = "Non specificato"
                righe.append(
                    {
                        "scontrino_id": s.get("id"),
                        "negozio": s.get("negozio") or "Sconosciuto",
                        "data": data_valida,
                        "totale_dichiarato": s.get("totale_dichiarato") or 0,
                        "stato_validazione": s.get("stato_validazione"),
                        "categoria": categoria,
                        "prezzo_totale": p.get("prezzo_totale") or 0,
                    }
                )

        df = pd.DataFrame(righe)

        # --- FILTRI ---
        st.subheader("Filtri")
        col_cat, col_da, col_a = st.columns(3)

        categorie_disponibili = ["Tutte"] + sorted(df["categoria"].unique().tolist())
        with col_cat:
            categoria_selezionata = st.selectbox("Categoria", categorie_disponibili)

        date_valide = df["data"].dropna()
        data_minima = date_valide.min() if not date_valide.empty else datetime.today().date()
        data_massima = date_valide.max() if not date_valide.empty else datetime.today().date()

        with col_da:
            data_da = st.date_input("Data da", value=data_minima)
        with col_a:
            data_a = st.date_input("Data a", value=data_massima)

        # Applicazione filtri: base condivisa per tutto ciò che segue.
        df_filtrato = df.copy()
        if categoria_selezionata != "Tutte":
            df_filtrato = df_filtrato[df_filtrato["categoria"] == categoria_selezionata]

        def _dentro_intervallo(data_val):
            # Le righe senza una data valida (es. scontrino "da rivedere" con
            # data illeggibile) restano sempre visibili: non hanno un valore
            # su cui applicare il filtro, e nasconderle contraddirebbe la
            # logica di quarantena (non si scarta/nasconde mai nulla).
            if data_val is None:
                return True
            return data_da <= data_val <= data_a

        df_filtrato = df_filtrato[df_filtrato["data"].apply(_dentro_intervallo)]

        if df_filtrato.empty:
            st.warning("Nessuno scontrino corrisponde ai filtri selezionati.")
        else:
            # --- KPI ---
            totale_speso = df_filtrato["prezzo_totale"].sum()
            numero_scontrini = df_filtrato["scontrino_id"].nunique()
            spesa_media = totale_speso / numero_scontrini if numero_scontrini else 0
            scontrini_da_rivedere_ids = set(
                df_filtrato.loc[
                    df_filtrato["stato_validazione"] == "da_rivedere", "scontrino_id"
                ].unique()
            )
            numero_da_rivedere = len(scontrini_da_rivedere_ids)

            # Griglia 2x2 invece di 4 colonne affiancate: su schermi stretti
            # (mobile) 4 colonne in fila diventano illeggibili, mentre 2x2
            # resta leggibile sia su desktop sia su smartphone.
            riga1_col1, riga1_col2 = st.columns(2)
            riga1_col1.metric("Totale speso", f"€ {totale_speso:.2f}")
            riga1_col2.metric("Numero di scontrini", numero_scontrini)

            riga2_col1, riga2_col2 = st.columns(2)
            riga2_col1.metric("Spesa media per scontrino", f"€ {spesa_media:.2f}")
            with riga2_col2:
                st.metric("Scontrini da rivedere", numero_da_rivedere)
                if numero_da_rivedere > 0:
                    st.error(f"⚠️ {numero_da_rivedere} da controllare")

            # --- Grafico: spesa nel tempo ---
            st.subheader("Spesa nel tempo")
            df_tempo = df_filtrato.dropna(subset=["data"])
            if df_tempo.empty:
                st.info("Nessuna data valida disponibile per il grafico nel periodo selezionato.")
            else:
                spesa_per_data = df_tempo.groupby("data", as_index=False)["prezzo_totale"].sum().sort_values("data")
                fig_tempo = px.line(
                    spesa_per_data,
                    x="data",
                    y="prezzo_totale",
                    markers=True,
                    labels={"data": "Data", "prezzo_totale": "Spesa (€)"},
                )
                fig_tempo.update_traces(line_color=COLORE_ACCENTO, line_width=2)
                fig_tempo.update_layout(
                    yaxis_tickprefix="€ ", hovermode="x unified", font=dict(size=DIMENSIONE_FONT_GRAFICI)
                )
                st.plotly_chart(fig_tempo, use_container_width=True)

            # Grafici impilati verticalmente (non più affiancati in colonne):
            # su schermi stretti (mobile) due grafici affiancati diventano
            # troppo compressi per essere leggibili, mentre a piena larghezza
            # restano leggibili sia su desktop sia su smartphone.
            st.subheader("Spesa per categoria")
            spesa_categoria = (
                df_filtrato.groupby("categoria", as_index=False)["prezzo_totale"]
                .sum()
                .sort_values("prezzo_totale", ascending=True)
            )
            fig_categoria = px.bar(
                spesa_categoria,
                x="prezzo_totale",
                y="categoria",
                orientation="h",
                labels={"prezzo_totale": "Spesa (€)", "categoria": "Categoria"},
            )
            fig_categoria.update_traces(marker_color=COLORE_ACCENTO)
            fig_categoria.update_layout(xaxis_tickprefix="€ ", font=dict(size=DIMENSIONE_FONT_GRAFICI))
            st.plotly_chart(fig_categoria, use_container_width=True)

            st.subheader("Spesa per negozio")
            spesa_negozio = (
                df_filtrato.groupby("negozio", as_index=False)["prezzo_totale"]
                .sum()
                .sort_values("prezzo_totale", ascending=True)
            )
            fig_negozio = px.bar(
                spesa_negozio,
                x="prezzo_totale",
                y="negozio",
                orientation="h",
                labels={"prezzo_totale": "Spesa (€)", "negozio": "Negozio"},
            )
            fig_negozio.update_traces(marker_color=COLORE_ACCENTO)
            fig_negozio.update_layout(xaxis_tickprefix="€ ", font=dict(size=DIMENSIONE_FONT_GRAFICI))
            st.plotly_chart(fig_negozio, use_container_width=True)

            # --- Tabella scontrini da rivedere ---
            if numero_da_rivedere > 0:
                etichetta_scontrino = "scontrino" if numero_da_rivedere == 1 else "scontrini"
                st.warning(
                    f"⚠️ {numero_da_rivedere} {etichetta_scontrino} da rivedere nel periodo/categoria selezionati"
                )

                righe_rivedere = []
                for s in scontrini:
                    if s.get("id") not in scontrini_da_rivedere_ids:
                        continue
                    # Le note di validazione non sono persistite nel database
                    # (schema attuale: solo lo stato valido/da_rivedere) — le
                    # ricalcoliamo al volo rieseguendo validate() sui dati già
                    # salvati, riusando la stessa logica già approvata in
                    # validator.py invece di duplicarla qui.
                    _, note = validate(s)
                    righe_rivedere.append(
                        {
                            "Negozio": s.get("negozio"),
                            "Data": s.get("data") or s.get("data_raw"),
                            "Totale dichiarato": f"€ {(s.get('totale_dichiarato') or 0):.2f}",
                            "Note di validazione": len(note),
                        }
                    )
                st.dataframe(pd.DataFrame(righe_rivedere), use_container_width=True, hide_index=True)
