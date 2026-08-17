# 🧾 Scontrini AI - Estrazione e Analisi Automatica di Scontrini con AI

## 📖 Descrizione del Progetto

Scontrini AI è un sistema che estrae **dati strutturati da foto di scontrini e
ricevute** tramite AI multimodale (**Google Gemini**, visione), li **valida** per
coerenza numerica, li salva in un **database relazionale** (PostgreSQL/Supabase) e
mostra una **dashboard di spesa interattiva** con filtri, KPI e grafici — tutto
tramite un'unica app web (**Streamlit**).

L'obiettivo non è solo tecnico: il sistema applica una logica di **"quarantena"**
tipica delle pipeline dati reali — uno scontrino che non supera i controlli di
coerenza non viene mai scartato, ma salvato comunque con uno stato che lo segnala
per revisione umana, insieme alle motivazioni specifiche dell'anomalia.

---

## 💡 Motivazione: perché questo stack

Questo progetto nasce da un vincolo esplicito, deciso prima ancora di scegliere
un'architettura: usare **solo servizi con un piano gratuito permanente** (non un
trial a tempo), in modo che il progetto resti **sempre dimostrabile online**, senza
scadenze.

Il vincolo nasce da un'esperienza diretta: un mio progetto precedente nel portfolio
(`portfolio_acme_project`, pipeline di intake ordini con agenti AI su Azure) usa
servizi Azure a consumo (Document Intelligence, AI Foundry) le cui credenziali di
sviluppo sono ormai **scadute** — il codice resta consultabile, ma non più
eseguibile o dimostrabile live senza riattivare un abbonamento a pagamento. Per
Scontrini AI ho scelto deliberatamente il percorso opposto:

- **Google Gemini API** — livello gratuito permanente per l'estrazione multimodale
- **Supabase (PostgreSQL)** — database gratuito permanente
- **Streamlit Community Cloud** — hosting gratuito permanente per l'app

Nessuno di questi tre servizi richiede una carta di credito o scade dopo un periodo
di prova: il progetto resta interamente funzionante e dimostrabile a costo zero, a
tempo indefinito.

---

## 🏗️ Architettura

Il flusso applicativo è lineare, dal caricamento della foto fino alla dashboard:

```text
Upload (Streamlit file_uploader)
    │
    ▼  extractor.py — Gemini 2.5 Flash (vision multimodale)
Estrazione: JSON strutturato (negozio, data, prodotti, totale_dichiarato)
            ogni prodotto include categoria e tipo ("prodotto" o "sconto")
    │
    ▼  validator.py — controlli di coerenza numerica (tolleranza 0.05)
Validazione: (is_valid, note[]) — NON blocca mai il salvataggio
    │
    ▼  database.py — Supabase (PostgreSQL)
Salvataggio: sempre eseguito
    ├─ is_valid = True  → stato_validazione = 'valido'
    └─ is_valid = False → stato_validazione = 'da_rivedere'  (quarantena, non scarto)
    │
    ▼  app.py — tab "Dashboard di spesa"
Dashboard: filtri (categoria, intervallo date) → KPI → grafici → tabella "da rivedere"
```

**Estrazione.** Il prompt inviato a Gemini non si limita a chiedere un JSON: codifica
esplicitamente le ambiguità reali osservate sugli scontrini italiani durante i test,
tra cui:

- quantità scritta *dentro* la descrizione del prodotto (es. `"3 X COPERTO"` →
  `nome: "Coperto"`, `quantita: 3`, non lasciata nel testo);
- righe di dettaglio separate sotto un prodotto (es. `"* 2 X 2,50"`), che vanno
  fuse nel prodotto precedente invece di generare una riga fantasma;
- scontrini che non elencano prodotti reali ma solo codici generici di reparto
  (es. `"REPARTO 1"`), da mantenere così come sono anziché inventare un nome
  plausibile;
- parole spezzate a fine riga per mancanza di spazio (es. `"AC"` / `"QUA"` →
  `"Acqua"`), da ricostruire invece di lasciare troncate;
- ogni prodotto viene classificato in una tra **10 categorie**: Ristorazione,
  Alimentari, Abbigliamento, Farmacia, Trasporti, Casa & Bricolage, Bellezza &
  Cura personale, Tempo libero, Tabacchi, Altro.

**Prodotto vs. sconto.** Ogni riga estratta ha anche un campo `tipo`, che vale
`"prodotto"` oppure `"sconto"`. La distinzione esiste perché sconti, annullamenti
cassiera o altre rettifiche **non sono acquisti reali**: trattarli come prodotti
normali generava falsi allarmi in validazione — un prezzo negativo su un prodotto
vero è un'incoerenza da segnalare, ma su una riga di sconto è normale e atteso. Il
prompt istruisce il modello a riconoscere questi casi anche quando la dicitura non
contiene parole esplicite come "sconto" o "annullo", usando un indizio strutturale:
un importo negativo il cui valore assoluto coincide con il prezzo del prodotto
immediatamente precedente sullo scontrino è quasi sempre l'annullamento di quel
prodotto specifico.

**Validazione.** `validator.py` controlla — senza mai bloccare il salvataggio — che:
i campi obbligatori siano presenti, che la data sia una data calendaristica reale,
che per ogni riga di tipo `"prodotto"` `quantità × prezzo_unitario ≈ prezzo_totale`
(tolleranza assoluta **0.05**, per arrotondamenti) e che non ci siano quantità o
prezzi negativi, e che la somma di **tutte** le righe (prodotti e sconti insieme)
corrisponda al totale dichiarato sullo scontrino. Le righe di tipo `"sconto"` sono
esentate dai controlli di segno e di coerenza quantità×prezzo, che per una rettifica
non avrebbero senso.

**Salvataggio.** Qualsiasi esito della validazione produce comunque una scrittura
su database: la differenza è solo nel valore di `stato_validazione`. Questa è la
logica di **quarantena** del progetto — un dato incoerente è un segnale da
controllare, non un errore da nascondere.

**Dashboard.** Un unico set di filtri (categoria prodotto, intervallo di date)
alimenta in modo condiviso 4 KPI, un grafico di andamento della spesa nel tempo, due
grafici di ripartizione (per categoria e per negozio) e una tabella dedicata agli
scontrini in stato `da_rivedere`, sempre visibile quando ce ne sono. I KPI e il
grafico "Spesa nel tempo" includono **sempre tutte le righe**, sconti compresi,
perché riflettono la spesa netta reale; i grafici "Spesa per categoria" e "Spesa per
negozio" **escludono le righe di tipo `"sconto"`**, per non distorcere il confronto
tra categorie o negozi con importi che non sono acquisti.

### Nota metodologica: i limiti dell'estrazione via LLM

L'estrazione tramite modello multimodale **non è perfettamente deterministica** tra
chiamate identiche sulla stessa immagine. Durante i test sono stati osservati diversi
casi concreti:

- La stessa foto di uno scontrino, estratta due volte in momenti diversi, ha
  restituito una volta il prodotto come `"Cozze Marinara"` e un'altra volta come
  `"Sozze Marinara"` (una lettera diversa, C → S).
- Un prezzo composto da quantità × prezzo unitario è stato, in un caso, semplificato
  in un valore aggregato, perdendo il dettaglio della scomposizione originale pur
  restando numericamente coerente con il totale — nessun errore di importo, solo una
  ricostruzione meno fedele della struttura originale della riga.
- Una riga di annullo cassiera con importo negativo è stata, in un altro scontrino
  reale, classificata come `tipo: "prodotto"` invece che `"sconto"`, nonostante il
  prompt contenga un'istruzione esplicita pensata proprio per riconoscere questo
  pattern (importo negativo pari al prezzo del prodotto immediatamente precedente).
  La validazione numerica ha comunque intercettato l'anomalia — un prezzo negativo su
  un prodotto reale è per definizione un'incoerenza — mandando lo scontrino in
  quarantena invece di lasciare corrompere silenziosamente i dati.
- Un'abbreviazione ambigua nel nome di un prodotto (es. un prefisso che identifica
  una variante specifica di un menu) è stata categorizzata in modo plausibile ma
  sbagliato, per mancanza di un contesto che nessun sistema — umano compreso, senza
  conoscere il menu specifico dell'esercizio — potrebbe risolvere con certezza.
- Un prodotto comparso su due righe identiche consecutive dello scontrino è stato, in
  un caso, ricondotto a una sola riga, perdendo il duplicato. Anche qui la
  validazione ha segnalato correttamente l'incoerenza tra somma dei prodotti e
  totale dichiarato, mandando lo scontrino in quarantena invece di salvare un dato
  silenziosamente sbagliato.

La validazione numerica intercetta correttamente le incoerenze su prezzi e quantità,
ma **non può** verificare la correttezza ortografica o semantica del testo libero (il
nome o la categoria di un prodotto): non esiste, né avrebbe senso costruire per
questo progetto, un dizionario di riferimento di tutti i possibili nomi di prodotto o
il menu di ogni esercizio commerciale. È un **limite strutturale accettato**
dell'approccio "AI multimodale come OCR intelligente", non un bug da correggere nel
codice — ed è anche la ragione d'essere della coda "da rivedere": quando la
validazione numerica non basta a garantire la correttezza, il dato resta comunque
disponibile per un controllo umano invece di sparire.

### Nota sui limiti del tier gratuito Gemini

Il modello `gemini-2.5-flash` ha un limite di circa **20 richieste al giorno** sul
piano gratuito (ridotto da Google a **dicembre 2025** — in precedenza era circa
250/giorno). La demo pubblica potrebbe quindi mostrare temporaneamente un messaggio
di *"limite giornaliero raggiunto"* se la quota del giorno è già esaurita; si
resetta ogni 24 ore. È un limite del servizio esterno, non del progetto — l'errore
**429 (`RESOURCE_EXHAUSTED`)** restituito dall'API viene intercettato esplicitamente
nel codice (`extract_receipt()` in `src/extractor.py`) e tradotto in un messaggio
chiaro per l'utente, invece di lasciar propagare un traceback tecnico grezzo fino
all'interfaccia.

---

## 📂 Struttura del Repository

```text
scontrini-ai/
│
├── .streamlit/
│   ├── config.toml               # Tema dell'app (colori, upload massimo)
│   └── secrets.toml.example      # Template credenziali, SENZA valori veri
│
├── src/
│   ├── __init__.py
│   ├── extractor.py              # Estrazione dati da immagine (Gemini vision)
│   ├── validator.py              # Validazione di coerenza numerica
│   └── database.py               # Accesso a Supabase (salvataggio/lettura)
│
├── app.py                        # Entry point Streamlit (Upload + Dashboard)
├── requirements.txt              # Dipendenze Python del progetto
├── .gitignore
└── README.md                     # Questo file
```

---

## 🗄️ Schema Dati

Due tabelle relazionali su Supabase, collegate da una foreign key:

```sql
CREATE TABLE scontrini (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    negozio            TEXT NOT NULL,
    data               DATE,              -- NULL se la stringa estratta non è una data valida
    data_raw           TEXT NOT NULL DEFAULT '',  -- valore originale SEMPRE preservato, anche se non valido
    totale_dichiarato  NUMERIC NOT NULL,
    stato_validazione  TEXT NOT NULL CHECK (stato_validazione IN ('valido', 'da_rivedere')),
    creato_il          TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE prodotti (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scontrino_id       BIGINT NOT NULL REFERENCES scontrini(id),
    nome               TEXT NOT NULL,
    quantita           NUMERIC NOT NULL,
    prezzo_unitario    NUMERIC NOT NULL,
    prezzo_totale      NUMERIC NOT NULL,
    categoria          TEXT,
    tipo               TEXT NOT NULL DEFAULT 'prodotto'  -- 'prodotto' oppure 'sconto'
);

ALTER TABLE scontrini ENABLE ROW LEVEL SECURITY;
ALTER TABLE prodotti ENABLE ROW LEVEL SECURITY;

-- Policy permissive: progetto mono-utente senza autenticazione. In un'app
-- multi-utente reale andrebbero ristrette per utente (es. auth.uid()).
CREATE POLICY "Consenti tutto - scontrini" ON scontrini FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Consenti tutto - prodotti" ON prodotti FOR ALL USING (true) WITH CHECK (true);
```

Il campo **`data_raw`** è la scelta di design più importante dello schema: quando
Gemini estrae una data non calendaristicamente valida (es. `"2026-13-45"`, mese 13),
la colonna `data` resta `NULL` — ma `data_raw` conserva sempre la stringa originale
così com'è stata letta. Nessuna informazione va persa nemmeno per gli scontrini in
quarantena: la dashboard mostra `data_raw` al posto di `data` quando quest'ultima è
assente.

Il campo **`tipo`** distingue le righe che rappresentano un acquisto reale da quelle
che sono sconti o rettifiche — vedi la sezione Architettura per la logica completa e
per come viene usato nella dashboard.

---

## 🛠️ Stack Tecnico

- **Python** — logica applicativa (estrazione, validazione, accesso dati)
- **Google Gemini API** (`google-genai`, modello `gemini-2.5-flash`) — visione
  multimodale per l'estrazione dati da immagine, livello gratuito
- **Streamlit** — interfaccia web (upload, dashboard) e hosting su Streamlit
  Community Cloud
- **PostgreSQL / Supabase** — database relazionale gratuito, con **Row Level
  Security abilitata** e policy esplicite (permissive, coerenti con l'assenza di
  autenticazione — vedi Nota sulla demo pubblica) sulle tabelle `scontrini` e
  `prodotti`
- **Plotly** — grafici interattivi della dashboard (andamento spesa, ripartizioni
  per categoria/negozio)
- **Pandas** — aggregazione e filtro dei dati per la dashboard

---

## 🚀 Come Eseguirlo in Locale

### 1. Setup dell'ambiente

```bash
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. Configurazione delle credenziali

Le credenziali (Gemini API key, URL e chiave Supabase) sono gestite tramite il
meccanismo nativo di Streamlit (`st.secrets`), per compatibilità diretta tra
sviluppo locale e Streamlit Community Cloud, senza logica condizionale nel codice.

Copia il template e compilalo con le tue chiavi:

```bash
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
```

```toml
# .streamlit/secrets.toml
GEMINI_API_KEY = "la-tua-chiave-gemini"
SUPABASE_URL = "https://tuo-progetto.supabase.co"
SUPABASE_KEY = "la-tua-chiave-supabase"
```

`.streamlit/secrets.toml` non va mai committato (è escluso via `.gitignore`); solo
il file `.example`, senza valori veri, fa parte del repository.

### 3. Avvio dell'app

```bash
streamlit run app.py
```

L'app si apre su `http://localhost:8501`, con due tab: **Upload scontrino**
(caricamento foto → estrazione → validazione → salvataggio) e **Dashboard di
spesa** (filtri, KPI, grafici, revisione).

---

### 📢 Nota sulla demo pubblica

Questa demo non implementa autenticazione: tutti i dati caricati sono salvati in un
database condiviso, visibile a chiunque usi l'app — non c'è separazione tra utenti
(l'interfaccia stessa lo segnala esplicitamente, con un avviso prima dell'upload e
uno nella dashboard). È una scelta deliberata per mantenere il progetto semplice come
pezzo di portfolio; le policy RLS su Supabase sono già scritte in un modo che
renderebbe l'aggiunta di autenticazione multi-utente un'estensione naturale, non una
riscrittura: basterebbe collegare **Supabase Auth**, aggiungere una colonna
`user_id` alle tabelle, e restringere le policy da `USING (true)` a
`USING (auth.uid() = user_id)`.

---

## 🌐 Demo Live

[Prova la demo live](https://portfolioscontriniai-cw9dto9vgrfhdumzn8inlv.streamlit.app/)

---

Lorenzo Bellardi — [LinkedIn](https://www.linkedin.com/in/lorenzo-bellardi) ·
[GitHub](https://github.com/lorebella1996)
