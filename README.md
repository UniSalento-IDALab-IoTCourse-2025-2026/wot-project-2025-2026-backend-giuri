<div align="center">

<img src="dashboard/static/favicon.svg" width="80" height="80" alt="CardioSense logo">

# CardioSense

### Sistema IoT real-time per il monitoraggio closed-loop di pazienti con scompenso cardiaco

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![MongoDB](https://img.shields.io/badge/MongoDB-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/)
[![MySQL](https://img.shields.io/badge/MySQL-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)
[![MQTT](https://img.shields.io/badge/MQTT-Mosquitto-3C5280?logo=eclipsemosquitto&logoColor=white)](https://mosquitto.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-F7931E?logo=scikit-learn&logoColor=white)](https://scikit-learn.org/)
[![Kivy](https://img.shields.io/badge/Kivy-Patient%20App-1B6CA8?logo=python&logoColor=white)](https://kivy.org/)
[![License](https://img.shields.io/badge/License-Academic%20Use-lightgrey)](#licenza--copyright)

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

**CardioSense** è un sistema IoT end-to-end per il monitoraggio in tempo reale di pazienti affetti da **insufficienza cardiaca congestizia**. Il sistema acquisisce segnali fisiologici (ECG, postura tramite accelerometro, temperatura corporea) da un dispositivo wearable, li classifica tramite modelli di Machine Learning per rilevare anomalie cliniche, e mette in comunicazione diretta **paziente** e **medico** attraverso un'architettura event-driven basata su MQTT, con persistenza su database e validazione clinica delle anomalie rilevate.

Il progetto nasce con l'obiettivo di costruire — partendo da un dispositivo di acquisizione biomedicale esistente (**IIT BioDataAcq**) — un sistema cloud-like completo: dall'acquisizione del segnale grezzo fino alla dashboard clinica, passando per classificazione automatica, notifiche in tempo reale e un ciclo di **retraining periodico** dei modelli sulla base delle validazioni mediche.

> 📦 **Nota sui repository**: questo repository contiene il **backend** (classificazione, API, persistenza, notifiche) e la **dashboard medico**. L'app paziente **IIT BioDataAcq** — di proprietà dell'Istituto Italiano di Tecnologia — risiede in un repository separato, non incluso qui. In questo repo viene solo documentato a livello architetturale il layer di integrazione MQTT che si aggancia ad essa (`mqtt_bridge.py`, `patient_login.py`, `patient_session.py`, `patient_anomalies.py`), citato a scopo descrittivo ma non distribuito in questo codice.

> 🩺 **Closed-loop**: ogni anomalia rilevata automaticamente viene validata da un medico (vero positivo / falso allarme); queste validazioni rientrano nel dataset di addestramento per ri-calibrare periodicamente il classificatore ECG, chiudendo il ciclo tra IA e giudizio clinico.

---

## Architettura

> Lo schema sotto mostra l'intero sistema end-to-end.

```
                ┌───────────────────────────────────────────────────────────────┐
                │ App Python "IIT BioDataAcq" + dongle USB/BLE  (repo separato) │
                │ (acquisizione segnali grezzi: ECG, IMU, Temperatura)          │
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
  │ • TemperaturaClassifier (soglie cliniche)     │       │ • Validazione episodi    │
  │ • Salvataggio annotazioni su MongoDB          │       │ • Storico anomalie       │
  │ • Notifiche allarme → medico                  │       └──────────────────────────┘
  └───────────────────────────────────────────────┘
                          │                                            │
                          ▼                                            ▼
         ┌─────────────────────────────────┐            ┌────────────────────────────┐
         │ MongoDB (annotazioni)           │            │ Dashboard Web (medico)     │
         │ MySQL (profili medico/paziente) │            │ HTML + JS · MQTT WebSocket │
         └─────────────────────────────────┘            └────────────────────────────┘
                          │ retrain notturno
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
| **Dashboard medico** | HTML5 · CSS · JavaScript vanilla · MQTT.js (WebSocket) |
| **App paziente** | Python · Kivy |
| **Containerizzazione** | Docker · Docker Compose |

---

## Funzionalità principali

- 📡 **Acquisizione in tempo reale** di ECG (250 Hz), accelerometro IMU (104 Hz) e temperatura corporea, tramite layer MQTT non invasivo sopra il core headless dell'app di acquisizione esistente
- 🔐 **Login paziente** tramite codice di accesso univoco a 8 caratteri generato dal medico
- 🧠 **Classificazione automatica multi-segnale**:
  - ECG → normale / anomalo (con score di confidenza)
  - Postura → 13 classi di attività motoria (da fermo a corsa/salti)
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
| **PosturaClassifier** | Random Forest (`class_weight='balanced'`) | [MHEALTH](https://archive.ics.uci.edu/dataset/319/mhealth+dataset) (UCI) | statistiche su finestre accelerometriche di 100 campioni (2s @ 50Hz, overlap 50%) + Signal Magnitude Area |
| **TemperaturaClassifier** | Regole deterministiche (soglie cliniche) | — | valore di temperatura corporea |

Tutti i classificatori implementano un'interfaccia comune (`BaseClassifier.predict()`), secondo il **Strategy Pattern**, rendendo intercambiabile la logica di classificazione senza impatto sul resto del sistema.

---

## Struttura del repository

> Questo repository contiene **solo** backend e dashboard medico. L'app paziente IIT BioDataAcq vive in un repository a parte (vedi [Repository collegati](#repository-collegati)).

```
cardiosense/
├── docker-compose.yml
├── mosquitto/
│   ├── config/mosquitto.conf       # listener TLS 8883 + WSS 9002
│   └── certs/                       # certificati (non versionati)
├── backend/
│   ├── fastapi_server.py            # REST API + JWT auth
│   ├── mqtt_subscriber.py           # pipeline classificazione + persistenza
│   ├── retrain_scheduler.py         # job notturno APScheduler
│   ├── classifiers/                 # ECG · Postura · Temperatura (Strategy)
│   ├── services/                    # Annotation · Notification · Retrain · ECGBuffer
│   ├── repositories/                # Annotation (Mongo) · User (MySQL) — Repository Pattern
│   ├── models/                      # Pydantic (Mongo) + SQLAlchemy ORM (MySQL)
│   ├── ai/                          # script di training + modelli .pkl
│   ├── db/                          # client Mongo/MySQL (Singleton) + utility TLS
│   └── simulation/                  # simulatore di stream paziente per test end-to-end
└── dashboard/
    ├── index.html / medico.html     # login + dashboard clinica
    └── static/app.js                # MQTT WebSocket + polling REST
```

### Repository collegati

| Repository | Contenuto | Stato |
|---|---|---|
| **CardioSense** *(questo repo)* | Backend, classificazione, API, dashboard medico | Privato |
| **IIT BioDataAcq** *(repo separato)* | App Kivy di acquisizione segnali via dongle USB/BLE, proprietà IIT, con layer di integrazione MQTT (`mqtt_bridge.py`, `patient_login.py`, `patient_session.py`, `patient_anomalies.py`) | Repository distinto, non incluso qui |

Il layer di integrazione lato paziente è descritto in questo README a scopo di documentazione architetturale (sezione [App paziente](#app-paziente)), ma il relativo codice sorgente risiede esclusivamente nel repository IIT BioDataAcq.

---

## Sicurezza — TLS end-to-end

Tutte le comunicazioni di rete del sistema sono cifrate:

- **MQTT** (paziente → broker → subscriber): TLS 1.2 su porta `8883`
- **WebSocket** (dashboard browser → broker): TLS su porta `9002`
- **REST API** (dashboard/app → FastAPI): HTTPS su porta `8443`

Per l'ambiente di sviluppo/demo locale, i certificati sono generati con **[mkcert](https://github.com/FiloSottile/mkcert)**, che installa una CA root correttamente strutturata (`basicConstraints = CA:TRUE`) nel trust store del sistema operativo — eliminando i prompt di sicurezza ricorrenti tipici dei certificati self-signed generati con OpenSSL "a mano". Uno script di fallback (`genera_certificati.sh`) basato su OpenSSL puro resta disponibile per chi necessiti di un metodo portabile multi-macchina.

> ⚠️ La CA generata da mkcert è di fiducia solo sulla macchina su cui è stata installata. Per la riproducibilità su altre macchine, rigenerare i certificati localmente con `mkcert -install`.

---

## Installazione e avvio

### Prerequisiti

- Python 3.10–3.12
- Docker + Docker Compose
- [mkcert](https://github.com/FiloSottile/mkcert) (per TLS locale)

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

## 3. Dashboard medico

Servire la cartella `dashboard/` con l'estensione **Live Server** di VS Code, configurata per servire in HTTPS con i certificati mkcert.

In `.vscode/settings.json`:

```json
{
  "liveServer.settings.https": {
    "enable": true,
    "cert": "<percorso-assoluto-a>/mosquitto/certs/server.crt",
    "key": "<percorso-assoluto-a>/mosquitto/certs/server.key"
  }
}
```

> ℹ️ Usando gli stessi certificati mkcert già generati per FastAPI e Mosquitto, il browser li riconosce come fidati (grazie a `mkcert -install`) senza bisogno di un certificato separato per la dashboard. Navigare quindi su `https://localhost:5500` (o la porta configurata) anziché `http://`.

### 4. Test senza dispositivo fisico

```bash
cd backend/simulation
python simulate_stream.py --scenario misto --durata 120
```

### 5. App paziente (repository separato)

L'app paziente **IIT BioDataAcq** non è contenuta in questo repository. Per eseguirla con il dispositivo wearable fisico e il layer di integrazione MQTT:

```bash
git clone <url-repo-IIT-BioDataAcq>     # repository separato
cd IIT-BioDataAcq
python software.py
```

Assicurarsi che il file `.env` dell'app paziente punti allo stesso broker Mosquitto (host, porta TLS, percorso del certificato CA) configurato per questo backend.

---

## Flusso dati

1. Il dispositivo wearable trasmette via BLE → l'app paziente acquisisce ECG/IMU/temperatura
2. `mqtt_bridge.py` pubblica un messaggio al secondo su `cardiosense/dati` (solo se acquisizione attiva e paziente loggato)
3. `mqtt_subscriber.py` riceve, classifica con i tre modelli, salva su MongoDB
4. Se l'ECG è anomalo → `NotificationService` pubblica su `cardiosense/allarmi`
5. La dashboard medico riceve l'allarme via WebSocket (notifica istantanea) **e** aggiorna la lista completa via polling REST ogni 8s
6. Il medico valida l'episodio (vero positivo / falso allarme + note) → scritto su MongoDB
7. Ogni notte, `retrain_scheduler.py` ri-addestra `ECGClassifier` sulle annotazioni validate, sovrascrivendo il modello in modo atomico (hot-reload via `mtime`, zero downtime)

---

## Dashboard medico

- **Panoramica**: KPI in tempo reale (pazienti monitorati, anomalie in attesa, validazioni del giorno)
- **Anomalie**: coda di episodi da validare, raggruppati clinicamente
- **Pazienti**: creazione e gestione, con generazione automatica del codice di accesso
- **Storico**: episodi passati per paziente, validati e in attesa, con traccia ECG e note cliniche
- **Notifiche desktop**: Web Notifications API + allarme sonoro via Web Audio API

## App paziente

> ℹ️ Codice in repository separato — sezione descrittiva a scopo architetturale.

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
- **Portabilità certificati TLS**: la CA mkcert non è multi-macchina; per deployment distribuiti è necessaria una CA condivisa o certificati firmati da un'autorità riconosciuta.

---

## Contesto accademico

Progetto sviluppato come elaborato/tesi universitaria presso l'**Università del Salento**, in collaborazione con:

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
- L'applicazione di acquisizione dati **IIT BioDataAcq** e l'hardware dongle associato sono proprietà dell'Istituto Italiano di Tecnologia (IIT) e risiedono in un **repository separato**, non incluso in questo progetto. Il presente repository ne documenta soltanto, a livello architetturale, il layer di comunicazione MQTT che vi si integra in modo non invasivo, senza distribuirne né modificarne il codice originale.
- I dataset utilizzati per l'addestramento dei modelli (**chfdb** via PhysioNet, **MHEALTH** via UCI Machine Learning Repository) sono soggetti alle rispettive licenze d'uso accademico/ricerca pubblicate dai fornitori originali.

**Uso del codice:** salvo diversa indicazione, il riuso, la modifica e la redistribuzione del codice di questo repository per finalità didattiche o di ricerca sono consentiti con citazione dell'autore e dell'ateneo di riferimento. Per usi commerciali o clinici reali, contattare l'autore: il sistema è stato sviluppato come prototipo dimostrativo e **non è certificato come dispositivo medico**.

---

<div align="center">

Realizzato da **Francesco Giuri** — Università del Salento

</div>