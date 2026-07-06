<div align="center">

<img src="favicon.svg" width="80" height="80" alt="CardioSense logo">

# CardioSense - Backend

### Sistema IoT real-time per il monitoraggio closed-loop di pazienti con scompenso cardiaco

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![MongoDB](https://img.shields.io/badge/MongoDB-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/)
[![MySQL](https://img.shields.io/badge/MySQL-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)
[![MQTT](https://img.shields.io/badge/MQTT-Mosquitto-3C5280?logo=eclipsemosquitto&logoColor=white)](https://mosquitto.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-F7931E?logo=scikit-learn&logoColor=white)](https://scikit-learn.org/)
</div>

---

## Indice

- [Panoramica](#panoramica)
- [Architettura](#architettura)
- [Stack tecnologico](#stack-tecnologico)
- [Funzionalità principali](#funzionalità-principali)
- [Modelli di Machine Learning](#modelli-di-machine-learning)
- [Struttura del repository](#struttura-del-repository)
  - [Repository collegati](#repository-collegati)
- [Sicurezza — TLS end-to-end](#sicurezza--tls-end-to-end)
- [Installazione e avvio](#installazione-e-avvio)
- [Flusso dati](#flusso-dati)
- [Dashboard medico](#dashboard-medico)
- [App paziente](#app-paziente)
- [Design pattern adottati](#design-pattern-adottati)
- [Limiti noti e lavori futuri](#limiti-noti-e-lavori-futuri)
- [Contesto accademico](#contesto-accademico)
- [Licenza & Copyright](#licenza--copyright)

---

## Panoramica

**CardioSense** è un sistema IoT end-to-end per il monitoraggio in tempo reale di pazienti affetti da **insufficienza cardiaca congestizia**. Il sistema acquisisce segnali fisiologici (ECG, postura tramite IMU a 6 assi — accelerometro + giroscopio, temperatura corporea) da un dispositivo wearable, li classifica tramite modelli di Machine Learning per rilevare anomalie cliniche, e mette in comunicazione diretta **paziente** e **medico** attraverso un'architettura event-driven basata su MQTT, con persistenza su database e validazione clinica delle anomalie rilevate.

Il progetto nasce con l'obiettivo di costruire — partendo da un dispositivo di acquisizione biomedicale esistente (**IIT BioDataAcq**) — un sistema cloud-like completo: dall'acquisizione del segnale grezzo fino alla dashboard clinica, passando per classificazione automatica, notifiche in tempo reale e un ciclo di **retraining periodico** dei modelli sulla base delle validazioni mediche.

> 📦 **Nota sui repository**: questo repository contiene **solo il backend** (classificazione, API, persistenza, notifiche). La **dashboard medico** è stata portata a React e vive in un repository separato — vedi [Repository collegati](#repository-collegati). L'app paziente **IIT BioDataAcq** — fornita da IIT come base per l'acquisizione dei segnali, di cui è stata autorizzata la modifica e la redistribuzione nell'ambito di questo progetto — risiede anch'essa in un repository separato, contenente sia il core originale IIT sia il layer di integrazione MQTT sviluppato in questo lavoro (`mqtt_bridge.py`, `patient_login.py`, `patient_session.py`, `patient_anomalies.py`).

> 🩺 **Closed-loop**: ogni anomalia rilevata automaticamente viene validata da un medico (vero positivo / falso allarme); queste validazioni rientrano nel dataset di addestramento per ri-calibrare periodicamente il classificatore ECG, chiudendo il ciclo tra IA e giudizio clinico.

---

## Architettura

> Lo schema sotto mostra l'intero sistema end-to-end.

```
                ┌───────────────────────────────────────────────────────────────┐
                │ App Python "IIT BioDataAcq" + dongle USB/BLE  (repo separato) │
                │ (acquisizione segnali grezzi: ECG, IMU acc+gyro, Temperatura) │
                └───────────────────────────────────────────────────────────────┘
                                                │
                                                │  layer non invasivo (mqtt_bridge.py)
                                                ▼
                                                  MQTT su TLS (mkcert)
                                                │
                                 ┌─────────────────────────────┐
                                 │ Broker Mosquitto            │
                                 │ (porte 8883 TLS · 9002 WSS) │
                                 └─────────────────────────────┘
                                                │
                          ┌─────────────────────┴──────────────────────┐
                          ▼                                            ▼
  ┌───────────────────────────────────────────────┐       ┌──────────────────────────┐
  │ mqtt_subscriber.py                            │       │ fastapi_server.py        │
  │                                               │       │                          │
  │ • ECGClassifier (Random Forest / chfdb)       │       │ • REST API (JWT auth)    │
  │ • PosturaClassifier (Random Forest / MHEALTH) │       │ • CRUD pazienti / medici │
  │   — feature su accelerometro + giroscopio     │       │ • Validazione episodi    │
  │ • TemperaturaClassifier (soglie cliniche)     │       │ • Storico anomalie       │
  │ • Salvataggio annotazioni su MongoDB          │       └──────────────────────────┘
  │ • Notifiche allarme → medico                  │
  └───────────────────────────────────────────────┘
                          │                                            │
                          ▼                                            ▼
         ┌─────────────────────────────────┐            ┌──────────────────────────────┐
         │ MongoDB (annotazioni)           │            │ Dashboard Web (medico)       │
         │ MySQL (profili medico/paziente) │            │ React (Vite) · repo separato │
         └─────────────────────────────────┘            │ MQTT via WebSocket           │
                          │ retrain notturno            └──────────────────────────────┘
                          ▲
              ┌──────────────────────┐
              │ retrain_scheduler.py │
              │ + RetrainService     │
              └──────────────────────┘
```

---

## Stack tecnologico

| Livello | Tecnologia |
|---|---|
| **Acquisizione segnale** | App Python Kivy "IIT BioDataAcq" + dongle USB/BLE |
| **Broker eventi** | Eclipse Mosquitto (MQTT su TLS, WebSocket su TLS) |
| **Backend API** | Python · FastAPI · JWT auth · Uvicorn (HTTPS) |
| **Machine Learning** | scikit-learn (Random Forest) |
| **Database documentale** | MongoDB (annotazioni, serie temporali) |
| **Database relazionale** | MySQL (profili medico/paziente) |
| **Scheduling** | APScheduler (retrain notturno) |
| **Sicurezza trasporto** | TLS 1.2+ — certificati locali trusted via [mkcert](https://github.com/FiloSottile/mkcert) |
| **Dashboard medico** | React (Vite) · MQTT.js (WebSocket) — **repository separato**, vedi [Repository collegati](#repository-collegati) |
| **App paziente** | Python · Kivy |
| **Containerizzazione** | Docker · Docker Compose |

---

## Funzionalità principali

- 📡 **Acquisizione in tempo reale** di ECG (250 Hz), IMU a 6 assi — accelerometro + giroscopio del sensore da polso/braccio (104 Hz) — e temperatura corporea, tramite layer MQTT non invasivo sopra il core headless dell'app di acquisizione esistente
- 🔐 **Login paziente** tramite codice di accesso univoco a 8 caratteri generato dal medico
- 🧠 **Classificazione automatica multi-segnale**:
  - ECG → normale / anomalo (con score di confidenza)
  - Postura → 8 classi di attività motoria (da fermo a corsa/salti), su feature statistiche congiunte di accelerometro e giroscopio
  - Temperatura → ipotermia / normale / febbre / febbre alta
- 🚨 **Notifiche in tempo reale** al medico via MQTT + Web Notifications native del browser, con beep sonoro
- 📊 **Raggruppamento clinico in episodi**: letture anomale consecutive (gap < 10s) vengono unite in un singolo episodio da validare, invece di mostrare decine di righe per lo stesso evento
- ✅ **Validazione medica**: ogni episodio può essere classificato come *vero positivo* o *falso allarme*, con note cliniche opzionali
- 📈 **Traccia ECG estesa**: finestra di ±15s intorno al picco anomalo, costruita in modo asincrono e visualizzata come grafico SVG nel modal di validazione
- 🔁 **Retraining automatico notturno** del modello ECG sulla base delle validazioni accumulate, con hot-reload basato su `mtime` del file del modello (nessun downtime, nessun riavvio dei processi in produzione)
- 🗂️ **Storico anomalie per paziente**, consultabile sia da medico che da paziente
- 📱 **App paziente**: badge anomalie in tempo reale, popup dettagliato con esito medico

---

## Modelli di Machine Learning

| Classificatore | Algoritmo | Dataset di training | Feature |
|---|---|---|---|
| **ECGClassifier** | Random Forest (`class_weight='balanced'`) | [chfdb](https://physionet.org/content/chfdb/) (PhysioNet) | media, std, min, max, range degli intervalli R-R su finestre di 10 battiti |
| **PosturaClassifier** | Random Forest (`class_weight='balanced'`) | [MHEALTH](https://archive.ics.uci.edu/dataset/319/mhealth+dataset) (UCI) | media, std, min, max per asse + Signal Magnitude Area, su finestre a 6 assi (accelerometro X/Y/Z + giroscopio X/Y/Z) del sensore da polso/braccio — 100 campioni in training (2s @ 50Hz, overlap 50%), 208 campioni a runtime (2s @ 104Hz, hop 1s, per allinearsi al sample rate reale del sensore IMU del dongle) |
| **TemperaturaClassifier** | Regole deterministiche (soglie cliniche) | — | valore di temperatura corporea |

Tutti i classificatori implementano un'interfaccia comune (`BaseClassifier.predict()`), secondo il **Strategy Pattern**, rendendo intercambiabile la logica di classificazione senza impatto sul resto del sistema.

### Nota sulle unità fisiche del segnale IMU

Il dataset MHEALTH esprime esplicitamente l'accelerazione in **m/s²** e la velocità angolare in **°/s** ([documentazione ufficiale UCI](https://archive.ics.uci.edu/dataset/319/mhealth+dataset)). Tutta la pipeline che alimenta `PosturaClassifier` — sia i dati reali (`mqtt_bridge.py`, che converte i conteggi raw ADC del dongle in unità fisiche) sia i dati simulati (`backend/simulation/simulate_stream.py`) — è tenuta coerente con queste stesse unità: qualunque discrepanza di scala (es. accelerazione lasciata in *g* invece che convertita in m/s², oppure ampiezze di movimento non plausibili rispetto ai reali range MHEALTH) fa sì che il Random Forest, addestrato su una distribuzione di valori diversa, sottostimi sistematicamente l'energia del segnale e classifichi movimento reale come posture a bassa energia (es. `sdraiato`). Questo vincolo va preservato in ogni futura modifica ai generatori di dati di test o al layer di acquisizione.

### Nota sull'isolamento per-paziente del buffer IMU

`PosturaClassifier` viene istanziato una sola volta e condiviso da `mqtt_subscriber.py` per tutti i pazienti connessi (stesso motivo per cui esiste un solo `ECGClassifier`/`TemperaturaClassifier` globale: evitare di ricaricare il modello ad ogni messaggio). Poiché il modello richiede finestre di 2s con overlap 50% mentre ogni messaggio MQTT porta solo ~1s di IMU, il classificatore deve mantenere uno stato tra un messaggio e l'altro — a differenza dell'ECG, dove ogni messaggio porta già una finestra `rr_intervals` completa e autosufficiente. Buffer, ultima label e ultimo score sono quindi tenuti in dizionari indicizzati per `paziente_id` (protetti da un lock), così i campioni IMU di pazienti diversi non vengono mai mescolati nella stessa finestra, anche con più pazienti connessi simultaneamente.

---

## Struttura del repository

> Questo repository contiene **solo il backend**. La dashboard medico (React) e l'app paziente IIT BioDataAcq vivono in repository a parte — vedi [Repository collegati](#repository-collegati).

```
cardiosense/
├── docker-compose.yml
├── mosquitto/
│   ├── config/mosquitto.conf       # listener TLS 8883 + WSS 9002
│   └── certs/                       # certificati (non versionati)
└── backend/
    ├── fastapi_server.py            # REST API + JWT auth
    ├── mqtt_subscriber.py           # pipeline classificazione + persistenza
    ├── retrain_scheduler.py         # job notturno APScheduler
    ├── classifiers/                 # ECG · Postura · Temperatura (Strategy)
    ├── services/                    # Annotation · Notification · Retrain · ECGBuffer
    ├── repositories/                # Annotation (Mongo) · User (MySQL) — Repository Pattern
    ├── models/                      # Pydantic (Mongo) + SQLAlchemy ORM (MySQL)
    ├── ai/                          # script di training + modelli .pkl
    ├── db/                          # client Mongo/MySQL (Singleton) + utility TLS
    └── simulation/                  # simulatore di stream paziente per test end-to-end
```

### Repository collegati

| Repository | Contenuto | Stato |
|---|---|---|
| **[CardioSense — Backend](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-backend-giuri)** *(questo repo)* | Backend, classificazione, API, persistenza, notifiche | Privato |
| **[cardiosense-dashboard](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-dashboard-giuri)** | Dashboard medico in React (Vite) — porting della dashboard originariamente vanilla HTML/CSS/JS, stessa identità visiva e logica applicativa | Privato |
| **[IIT BioDataAcq](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-patient-app-giuri)** | App Kivy di acquisizione segnali via dongle USB/BLE — base fornita da IIT, di cui è stata autorizzata la modifica per questo progetto — con layer di integrazione MQTT (`mqtt_bridge.py`, `patient_login.py`, `patient_session.py`, `patient_anomalies.py`) | Repository distinto |

Il layer di integrazione lato paziente è descritto in questo README a scopo di documentazione architetturale (sezione [App paziente](#app-paziente)), ma il relativo codice sorgente — insieme al core dell'app IIT su cui si appoggia — risiede nel repository `IIT BioDataAcq` linkato sopra. Allo stesso modo, la sezione [Dashboard medico](#dashboard-medico) qui sotto descrive le funzionalità esposte dalla dashboard React, il cui codice risiede nel repository `cardiosense-dashboard`.

> La dashboard HTML/CSS/JS vanilla usata in precedenza (cartella `dashboard/` di questo repository) è stata dismessa in favore del porting React. Resta consultabile nella cronologia Git di questo repository, ma non è più mantenuta né distribuita.

---

## Sicurezza — TLS end-to-end

Tutte le comunicazioni di rete del sistema sono cifrate:

- **MQTT** (paziente → broker → subscriber): TLS 1.2 su porta `8883`
- **WebSocket** (dashboard browser → broker): TLS su porta `9002`
- **REST API** (dashboard/app → FastAPI): HTTPS su porta `8443`

Per l'ambiente di sviluppo/demo locale, i certificati sono generati con **[mkcert](https://github.com/FiloSottile/mkcert)**, che installa una CA root correttamente strutturata (`basicConstraints = CA:TRUE`) nel trust store del sistema operativo — eliminando i prompt di sicurezza ricorrenti tipici dei certificati self-signed generati con OpenSSL "a mano". Uno script di fallback (`genera_certificati.sh`) basato su OpenSSL puro resta disponibile per chi necessiti di un metodo portabile multi-macchina.

I certificati generati (`.crt`/`.key`) non sono versionati in nessuno dei repository, compreso quello della dashboard React: quest'ultima li referenzia tramite percorso assoluto configurato in variabile d'ambiente (`VITE_TLS_CERT`/`VITE_TLS_KEY`), puntando agli stessi file usati da Mosquitto e FastAPI in questo repository, invece di duplicarli.

> ⚠️ La CA generata da mkcert è di fiducia solo sulla macchina su cui è stata installata. Per la riproducibilità su altre macchine, rigenerare i certificati localmente con `mkcert -install`.

---

## Installazione e avvio

### Prerequisiti

- Python 3.10–3.12
- Docker + Docker Compose
- [mkcert](https://github.com/FiloSottile/mkcert) (per TLS locale)
- Node.js 18+ (solo se si vuole avviare anche la dashboard React — vedi repo `cardiosense-dashboard`)

### 1. Infrastruttura

```bash
docker-compose up -d        # Mosquitto, MongoDB, MySQL
```

### 2. Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate   # o .\venv\Scripts\activate su Windows
pip install -r requirements.txt

# Training dei modelli (una tantum)
python ai/train_ecg.py
python ai/train_postura.py

# Avvio servizi
python fastapi_server.py            # terminale 1
python retrain_scheduler.py         # terminale 2 (opzionale, retrain notturno)
cd ..
python backend/mqtt_subscriber.py   # terminale 3

```

### 3. Dashboard medico

La dashboard medico **non è più contenuta in questo repository**: è stata portata a React e vive nel repository separato **`cardiosense-dashboard`**.

```bash
git clone https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-dashboard-giuri.git
cd wot-project-2025-2026-dashboard-giuri
npm install
cp .env.example .env.local
```

In `.env.local`, valorizzare i percorsi verso gli **stessi certificati mkcert** già usati da Mosquitto/FastAPI in questo repository (cartella `mosquitto/certs/` qui sopra):

```bash
VITE_API_URL=https://localhost:8443
VITE_BROKER_URL=wss://localhost:9002
VITE_TLS_CERT=/percorso/assoluto/a/mosquitto/certs/server.crt
VITE_TLS_KEY=/percorso/assoluto/a/mosquitto/certs/server.key
```

Poi:

```bash
npm run dev
```

Il dev server parte su `https://localhost:5173`. Per i dettagli completi (struttura del progetto, test end-to-end, note di porting) fare riferimento al README del repository `cardiosense-dashboard`.

> ℹ️ Non serve nessuna modifica al backend per far funzionare la dashboard React in locale: CORS in `fastapi_server.py` è già configurato per accettare l'origine del dev server Vite. In produzione, `allow_origins` va invece ristretto al dominio reale della dashboard deployata.

### 4. Test senza dispositivo fisico

```bash
cd backend/simulation
python simulate_stream.py --scenario misto --durata 120
```

> Lo scenario `movimento` genera dati accelerometrici e giroscopici in unità fisiche coerenti con il training MHEALTH (m/s² e °/s), così da attivare correttamente le classi di attività motoria ad alta energia (`camminata`, `salita_scale`, `corsa`, `salto`) invece di essere confuso con posture a riposo.

### 5. App paziente (repository separato)

L'app paziente **IIT BioDataAcq**, base fornita da IIT con l'autorizzazione a modificarla per questo progetto, non è contenuta in questo repository. Per eseguirla con il dispositivo wearable fisico e il layer di integrazione MQTT:

```bash
git clone https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-patient-app-giuri.git
cd wot-project-2025-2026-patient-app-giuri
python software.py
```

Assicurarsi che il file `.env` dell'app paziente punti allo stesso broker Mosquitto (host, porta TLS, percorso del certificato CA) configurato per questo backend.

---

## Flusso dati

1. Il dispositivo wearable trasmette via BLE → l'app paziente acquisisce ECG, IMU (accelerometro + giroscopio) e temperatura
2. `mqtt_bridge.py` pubblica un messaggio al secondo su `cardiosense/dati` (solo se acquisizione attiva e paziente loggato), convertendo i conteggi raw del dongle nelle stesse unità fisiche usate in training (accelerazione in m/s², velocità angolare in °/s)
3. `mqtt_subscriber.py` riceve, classifica con i due modelli, salva su MongoDB
4. Se l'ECG è anomalo → `NotificationService` pubblica su `cardiosense/allarmi`
5. La dashboard medico (React, repo separato) riceve l'allarme via WebSocket (notifica istantanea) **e** aggiorna la lista completa via polling REST ogni 8s
6. Il medico valida l'episodio (vero positivo / falso allarme + note) → scritto su MongoDB
7. Ogni notte, `retrain_scheduler.py` ri-addestra `ECGClassifier` sulle annotazioni validate, sovrascrivendo il modello in modo atomico (hot-reload via `mtime`, zero downtime)

---

## Dashboard medico

> Codice in repository separato ([`cardiosense-dashboard`](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-dashboard-giuri), React + Vite) — sezione descrittiva a scopo architetturale.

- **Panoramica**: KPI in tempo reale (pazienti monitorati, anomalie in attesa, validazioni del giorno)
- **Anomalie**: coda di episodi da validare, raggruppati clinicamente
- **Pazienti**: creazione e gestione, con generazione automatica del codice di accesso
- **Storico**: episodi passati per paziente, validati e in attesa, con traccia ECG e note cliniche
- **Notifiche desktop**: Web Notifications API + allarme sonoro via Web Audio API

La dashboard consuma esclusivamente le API REST esposte da `fastapi_server.py` e il topic MQTT `cardiosense/allarmi` via WebSocket (porta `9002`), esattamente come faceva la precedente versione vanilla: nessuna API o comportamento del backend è stato modificato per supportare il porting.

## App paziente

> ℹ️ Codice in repository separato ([`IIT BioDataAcq`](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-patient-app-giuri)) — sezione descrittiva a scopo architetturale.

- Login tramite codice di accesso fornito dal medico
- Badge anomalie in tempo reale (via sottoscrizione MQTT)
- Popup storico episodi con esito medico, raggruppati con la stessa logica di clustering usata dalla dashboard

---

## Design pattern adottati

| Pattern | Dove |
|---|---|
| **Strategy** | `BaseClassifier` → `ECGClassifier`, `PosturaClassifier`, `TemperaturaClassifier` |
| **Repository** | `AnnotationRepository` (MongoDB), `UserRepository` (MySQL) |
| **Service Layer** | `AnnotationService`, `NotificationService`, `RetrainService` |
| **Singleton** | `MongoDBClient` |
| **Factory implicito** | costruzione documenti `Annotation` (Pydantic) |

---

## Limiti noti e lavori futuri

- **Badge anomalie paziente non persistente tra sessioni**: il contatore lato app paziente è in-memory (azzerato al riavvio), mentre il badge medico è basato su query REST persistenti su MongoDB. Scelta di design motivata da semplicità/basso overhead lato dispositivo; lo storico completo resta sempre accessibile e corretto. Estendibile con polling REST periodico anche lato paziente.
- **Soglia di classificazione ECG** (0.5) calibrata empiricamente; suscettibile di affinamento con dataset più ampi o tecniche di calibrazione delle probabilità.
- **Portabilità certificati TLS**: la CA mkcert non è multi-macchina; per deployment distribuiti è necessaria una CA condivisa o certificati firmati da un'autorità riconosciuta. Questo vale anche per la dashboard React, che referenzia gli stessi certificati via percorso assoluto.
- **`PosturaClassifier` — nessun cleanup automatico dei buffer per paziente**: dopo la fix del buffer mono-istanza (ora keyed per `paziente_id`, vedi [Modelli di Machine Learning](#modelli-di-machine-learning)), lo stato interno di ogni paziente resta in memoria per l'intera vita del processo `mqtt_subscriber.py`, anche dopo la disconnessione. È disponibile un metodo `dimentica_paziente(paziente_id)` per liberarlo esplicitamente, ma nessun chiamante lo invoca ancora automaticamente. Irrilevante con un numero limitato di pazienti; da valutare (es. cleanup su timeout di inattività) per deployment con molti pazienti diversi nel tempo.
- **CORS in sviluppo**: `allow_origins` in `fastapi_server.py` è configurato per l'origine locale della dashboard React in sviluppo; prima di un deployment pubblico va ristretto esplicitamente al dominio di produzione della dashboard, evitando wildcard combinati con `allow_credentials=True`.

---

## Contesto accademico

Elaborato progettuale sviluppato per l'esame di Internet of Things presso l'Università del Salento, in collaborazione con:

- **IDA Lab** - Università del Salento
- **IIT — Istituto Italiano di Tecnologia**

L'app di acquisizione dati **"IIT BioDataAcq"**, su cui è stato costruito il layer di integrazione MQTT descritto in questo repository, è fornita da IIT come base hardware/software per l'acquisizione dei segnali fisiologici tramite dongle USB/BLE.

---

## Licenza & Copyright

```
CardioSense — Sistema IoT per il monitoraggio dello scompenso cardiaco

Copyright © 2026 Francesco Giuri
Università del Salento

Sviluppato in collaborazione con:
  - IDA Lab - Università del Salento
  - IIT — Istituto Italiano di Tecnologia
```

Questo progetto è stato realizzato a scopo accademico nell'ambito di un esame universitario.

**Componenti di terze parti:**
- L'applicazione di acquisizione dati **IIT BioDataAcq** e l'hardware dongle associato sono proprietà dell'Istituto Italiano di Tecnologia (IIT). Il codice, di cui è stata autorizzata la modifica e la redistribuzione nell'ambito di questo progetto, risiede nel **repository separato** [`IIT BioDataAcq`](https://github.com/UniSalento-IDALab-IoTCourse-2025-2026/wot-project-2025-2026-patient-app-giuri), insieme al layer di integrazione MQTT sviluppato in questo lavoro.
- I dataset utilizzati per l'addestramento dei modelli (**chfdb** via PhysioNet, **MHEALTH** via UCI Machine Learning Repository) sono soggetti alle rispettive licenze d'uso accademico/ricerca pubblicate dai fornitori originali.

**Uso del codice:** salvo diversa indicazione, il riuso, la modifica e la redistribuzione del codice di questo repository per finalità didattiche o di ricerca sono consentiti con citazione dell'autore e dell'ateneo di riferimento. Per usi commerciali o clinici reali, contattare l'autore: il sistema è stato sviluppato come prototipo dimostrativo e **non è certificato come dispositivo medico**.

---

<div align="center">

Realizzato da **Francesco Giuri** — Università del Salento

</div>