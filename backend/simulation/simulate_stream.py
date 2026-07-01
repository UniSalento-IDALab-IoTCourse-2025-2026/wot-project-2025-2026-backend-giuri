import json
import time
import random
import math
import numpy as np
import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv

# utility TLS condivisa
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # per importare db.mqtt_tls
from db.mqtt_tls import configura_tls, get_mqtt_port

load_dotenv()

# ============================================================
# CONFIGURAZIONE
# ============================================================

TOPIC_DATI = "cardiosense/dati"
PAZIENTE_ID = "QMQUGLKD"  # codice paziente di test

# Frequenza di campionamento ECG in Hz
ECG_SAMPLE_RATE = 250

# Durata della finestra ECG pubblicata per ogni messaggio (secondi)
ECG_WINDOW_SEC = 1.0

# Frequenza di pubblicazione messaggi (secondi)
INTERVALLO_PUBBLICAZIONE = 1.0

# Aggiungi la costante in cima a simulate_stream.py
IMU_SAMPLE_RATE = 104 

# Accelerazione di gravità standard, in m/s^2. Il modello di postura è
# addestrato su MHEALTH, le cui unità sono ESPLICITAMENTE documentate
# come m/s^2 per l'accelerometro e gradi/s (deg/s) per il giroscopio
# (fonte: https://archive.ics.uci.edu/dataset/319/mhealth+dataset).
# Qualsiasi generatore qui sotto DEVE produrre valori in queste stesse
# unità fisiche, altrimenti le feature statistiche (media, std, min,
# max, SMA) calcolate da PosturaClassifier finiscono in una scala
# completamente diversa da quella vista in training e il Random Forest
# classifica sistematicamente male (es. movimento scambiato per
# sdraiato/salita_scale per mancanza di "energia" nel segnale).
GRAVITA_MS2 = 9.81

# ============================================================
# GENERATORI ECG RAW REALISTICI
# ============================================================

def genera_ecg_raw_normale(n_campioni: int = None) -> list:
    """
    Simula una finestra ECG normale a 250Hz.

    Modella le onde P, QRS (con Q negativa, R positiva, S negativa) e T
    per un ritmo sinusale regolare a ~75 bpm (RR ≈ 0.80s).
    """
    if n_campioni is None:
        n_campioni = int(ECG_SAMPLE_RATE * ECG_WINDOW_SEC)

    segnale = []
    rr = 0.80  # RR nominale in secondi

    for i in range(n_campioni):
        t = i / ECG_SAMPLE_RATE
        # Fase normalizzata all'interno del ciclo cardiaco corrente [0, 1)
        fase = (t % rr) / rr

        if 0.10 < fase < 0.20:
            # Onda P
            v = 0.15 * math.sin(math.pi * (fase - 0.10) / 0.10)
        elif 0.28 < fase < 0.31:
            # Onda Q (negativa)
            v = -0.10 * math.sin(math.pi * (fase - 0.28) / 0.03)
        elif 0.31 < fase < 0.37:
            # Picco R (onda principale)
            v = 1.00 * math.sin(math.pi * (fase - 0.31) / 0.06)
        elif 0.37 < fase < 0.40:
            # Onda S (negativa)
            v = -0.20 * math.sin(math.pi * (fase - 0.37) / 0.03)
        elif 0.44 < fase < 0.58:
            # Onda T (ripolarizzazione ventricolare)
            v = 0.30 * math.sin(math.pi * (fase - 0.44) / 0.14)
        else:
            # Linea isoelettrica
            v = 0.0

        # Rumore fisiologico di baseline
        v += random.gauss(0, 0.018)
        segnale.append(round(v, 4))

    return segnale


def genera_ecg_raw_anomalo(n_campioni: int = None) -> list:
    """
    Simula una finestra ECG con fibrillazione atriale a 250Hz.

    Caratteristiche cliniche riprodotte:
    - Assenza di onda P (attività atriale caotica → baseline ondulata)
    - Intervalli RR irregolari (0.3s – 0.9s)
    - Complessi QRS variabili in ampiezza
    - Onda T anomala
    """
    if n_campioni is None:
        n_campioni = int(ECG_SAMPLE_RATE * ECG_WINDOW_SEC)

    durata = n_campioni / ECG_SAMPLE_RATE

    # Genera posizioni temporali dei battiti con RR irregolare
    battiti = []
    t_corrente = random.uniform(0.05, 0.15)  # offset iniziale casuale
    while t_corrente < durata:
        battiti.append(t_corrente)
        t_corrente += random.uniform(0.30, 0.90)  # RR caotico tipico di FA

    segnale = []
    for i in range(n_campioni):
        t = i / ECG_SAMPLE_RATE

        # Baseline ondulata che simula l'attività atriale caotica (fibrillazione)
        # Somma di sinusoidi a frequenze diverse per aspetto irregolare
        v = (0.04 * math.sin(2 * math.pi * 6.2 * t) +
             0.03 * math.sin(2 * math.pi * 8.7 * t + 1.1) +
             0.02 * math.sin(2 * math.pi * 11.3 * t + 2.4))

        # Complessi QRS per ogni battito
        for tb in battiti:
            dt = t - tb
            if 0 < dt < 0.04:
                # Onda Q anomala
                v -= 0.12 * math.sin(math.pi * dt / 0.04)
            elif 0.04 <= dt < 0.10:
                # Picco R con ampiezza variabile (segno di conduzione anomala)
                ampiezza_r = random.uniform(0.55, 1.10)
                v += ampiezza_r * math.sin(math.pi * (dt - 0.04) / 0.06)
            elif 0.10 <= dt < 0.14:
                # Onda S
                v -= 0.18 * math.sin(math.pi * (dt - 0.10) / 0.04)
            elif 0.18 <= dt < 0.32:
                # Onda T appiattita/invertita (anomala)
                v += 0.12 * math.sin(math.pi * (dt - 0.18) / 0.14)

        # Rumore di acquisizione leggermente più alto (muscolo + artefatti)
        v += random.gauss(0, 0.030)
        segnale.append(round(v, 4))

    return segnale


# ============================================================
# GENERATORI R-R (coerenti con il raw)
# ============================================================

def genera_rr_normale(n: int = 10) -> list:
    """Intervalli R-R stabili → ritmo sinusale normale."""
    return [round(random.uniform(0.76, 0.84), 3) for _ in range(n)]


def genera_rr_anomalo(n: int = 10) -> list:
    """Intervalli R-R caotici → fibrillazione atriale."""
    pool = [0.38, 0.41, 0.44, 0.49, 0.52, 1.05, 1.18, 1.32, 1.40, 0.47, 0.97]
    return [random.choice(pool) for _ in range(n)]


# ============================================================
# GENERATORI ACCELEROMETRO + GIROSCOPIO (braccio/polso)
# ============================================================
#
# Il PosturaClassifier è addestrato su 6 assi (acc_x,y,z + gyro_x,y,z
# del braccio, vedi train_postura.py). Questi generatori producono
# quindi entrambi i gruppi di assi in modo coerente: a riposo il
# giroscopio è vicino a zero (nessuna rotazione), in movimento oscilla
# in un range più ampio, proporzionale all'intensità del movimento
# simulato dall'accelerometro.
#
# IMPORTANTE (fix): tutte le ampiezze qui sotto sono espresse nelle
# STESSE unità fisiche di MHEALTH (accelerazione in m/s^2, giroscopio
# in gradi/s — non in "g" e non in unità arbitrarie). In precedenza il
# generatore di movimento usava ampiezze di pochi m/s^2 sull'accelerometro
# e di pochi gradi/s sul giroscopio: valori così piccoli, confrontati
# con le vere ampiezze MHEALTH per camminata/corsa/salto (che arrivano
# a decine di m/s^2 e centinaia di gradi/s per il sensore da polso),
# fanno sembrare "quasi fermo" qualunque movimento simulato — il
# modello quindi lo classifica come sdraiato (bassa energia) o al più
# salita_scale (energia intermedia), mai come camminata/corsa/salto.

def genera_imu_normale(n_campioni: int = 104) -> list[dict]:
    """Paziente fermo/seduto: asse Z dominante vicino a 9.81 m/s2 (gravità standard MHEALTH)."""
    campioni = []
    for _ in range(n_campioni):
        campioni.append({
            "acc_x": round(random.uniform(-0.2, 0.2), 3),
            "acc_y": round(random.uniform(-0.2, 0.2), 3),
            "acc_z": round(GRAVITA_MS2 + random.uniform(-0.3, 0.3), 3),
            "gyro_x": round(random.uniform(-0.1, 0.1), 3),
            "gyro_y": round(random.uniform(-0.1, 0.1), 3),
            "gyro_z": round(random.uniform(-0.1, 0.1), 3),
        })
    return campioni

def genera_imu_movimento(n_campioni: int = 104) -> list[dict]:
    """
    Paziente in movimento dinamico (cammino deciso / corsa / attività
    ad alta energia). Ampiezze scalate su ordini di grandezza reali per
    un sensore da polso/braccio in movimento (coerenti con le unità
    MHEALTH: accelerazione in m/s^2, giroscopio in gradi/s):

    - L'asse Z mantiene la componente di gravità (~9.81 m/s^2) come
      baseline, con il movimento sovrapposto sopra — non sostituita da
      un'altra costante arbitraria: un braccio che si muove non smette
      di "sentire" la gravità.
    - Le oscillazioni di accelerazione arrivano a ampiezze picco-picco
      dell'ordine di 10-25 m/s^2, plausibili per lo swing del braccio
      durante camminata/corsa.
    - Il giroscopio arriva a ampiezze dell'ordine di 80-150 gradi/s,
      plausibili per la rotazione del polso/avambraccio durante un
      movimento energico — non più i pochi gradi/s della versione
      precedente, indistinguibili dal rumore di quiete.
    """
    campioni = []
    for i in range(n_campioni):
        t = i / 104.0
        # Onda a 2.5 Hz (tipica cadenza di camminata veloce/jogging)
        onda = math.sin(2 * math.pi * 2.5 * t)
        cosonda = math.cos(2 * math.pi * 2.5 * t)

        campioni.append({
            # Accelerazione: gravità di base + oscillazione da movimento,
            # in m/s^2 (stessa unità del training MHEALTH)
            "acc_x": round((onda * 12.0) + random.uniform(-2.0, 2.0), 3),
            "acc_y": round((cosonda * 10.0) + random.uniform(-2.0, 2.0), 3),
            "acc_z": round(GRAVITA_MS2 + (onda * 14.0) + random.uniform(-2.5, 2.5), 3),
            # Giroscopio in gradi/s, ampiezza realistica per rotazione del
            # polso durante un movimento energico
            "gyro_x": round((onda * 120.0) + random.uniform(-10.0, 10.0), 3),
            "gyro_y": round((cosonda * 150.0) + random.uniform(-10.0, 10.0), 3),
            "gyro_z": round((onda * 90.0) + random.uniform(-10.0, 10.0), 3),
        })
    return campioni


# ============================================================
# GENERATORI TEMPERATURA
# ============================================================

def genera_temperatura_normale() -> float:
    return round(random.uniform(36.4, 36.9), 1)


def genera_temperatura_febbre() -> float:
    return round(random.uniform(38.8, 39.5), 1)


# ============================================================
# SCENARI DI TEST
# ============================================================

SCENARI = {
    "normale": {
        "descrizione": "Paziente a riposo, parametri nella norma",
        "ecg_fn":  genera_ecg_raw_normale,
        "rr_fn":   genera_rr_normale,
        "imu_fn":  genera_imu_normale,
        "temp_fn": genera_temperatura_normale
    },
    "anomalia_ecg": {
        "descrizione": "Fibrillazione atriale, altri parametri normali",
        "ecg_fn":  genera_ecg_raw_anomalo,
        "rr_fn":   genera_rr_anomalo,
        "imu_fn":  genera_imu_normale,
        "temp_fn": genera_temperatura_normale
    },
    "febbre": {
        "descrizione": "Temperatura elevata, ECG normale",
        "ecg_fn":  genera_ecg_raw_normale,
        "rr_fn":   genera_rr_normale,
        "imu_fn":  genera_imu_normale,
        "temp_fn": genera_temperatura_febbre
    },
    "movimento": {
        "descrizione": "Paziente in movimento, ECG normale",
        "ecg_fn":  genera_ecg_raw_normale,
        "rr_fn":   genera_rr_normale,
        "imu_fn":  genera_imu_movimento,
        "temp_fn": genera_temperatura_normale
    }
}


# ============================================================
# SCENARIO MISTO — episodi alternati normale/anomalia
# ============================================================
#
# A differenza degli altri scenari (stateless, ogni messaggio è
# indipendente), il misto simula episodi con una durata: il paziente
# resta per un po' in ritmo normale, poi entra in un episodio di
# fibrillazione atriale che dura qualche secondo/decina di secondi
# (paroxistica), poi torna normale. È più realistico di un semplice
# "tira un dado a ogni messaggio", che genererebbe anomalie isolate
# di un singolo secondo — clinicamente poco plausibili per la FA.
#
# La proporzione di tempo passato in anomalia è controllata da
# perc_anomalia (0.0-1.0): regola il rapporto fra la durata media
# degli episodi normali e quella degli episodi anomali, non la
# probabilità istantanea di transizione.

class GeneratoreMisto:
    """
    Mantiene lo stato (episodio corrente e quanto manca alla fine)
    tra una chiamata e l'altra di costruisci_payload_misto().
    """

    # Durata media di un episodio anomalo (FA paroxistica): 5-20s
    DURATA_ANOMALIA_MIN = 5
    DURATA_ANOMALIA_MAX = 20

    def __init__(self, perc_anomalia: float = 0.2):
        if not 0.0 < perc_anomalia < 1.0:
            raise ValueError("perc_anomalia deve essere compreso tra 0 e 1 (esclusi)")

        self.perc_anomalia = perc_anomalia

        # Dalla percentuale di tempo desiderata in anomalia deriviamo
        # la durata media degli episodi normali, mantenendo fissa la
        # durata media degli episodi anomali.
        durata_media_anomalia = (self.DURATA_ANOMALIA_MIN + self.DURATA_ANOMALIA_MAX) / 2
        durata_media_normale = durata_media_anomalia * (1 - perc_anomalia) / perc_anomalia

        # Range ±40% intorno alla media per variabilità. Il minimo assoluto
        # è 1s (un solo messaggio): per perc_anomalia molto alte (>~0.7) la
        # durata media naturale degli episodi normali scende sotto i 5s, ed
        # è corretto che accada — un clamp più alto distorcerebbe il
        # rapporto richiesto invece di limitarsi a renderlo più "a scatti".
        self._durata_normale_min = max(1, durata_media_normale * 0.6)
        self._durata_normale_max = max(self._durata_normale_min + 1, durata_media_normale * 1.4)

        self.stato = "normale"
        self.tempo_rimanente = self._nuova_durata_normale()

    def _nuova_durata_normale(self) -> float:
        return random.uniform(self._durata_normale_min, self._durata_normale_max)

    def _nuova_durata_anomalia(self) -> float:
        return random.uniform(self.DURATA_ANOMALIA_MIN, self.DURATA_ANOMALIA_MAX)

    def _transizione(self) -> None:
        """Passa all'episodio successivo e stampa il cambio di stato."""
        if self.stato == "normale":
            self.stato = "anomalia_ecg"
            self.tempo_rimanente = self._nuova_durata_anomalia()
            print(f"    ┗━ ⚡ Inizio episodio FA — durata ~{self.tempo_rimanente:.1f}s")
        else:
            self.stato = "normale"
            self.tempo_rimanente = self._nuova_durata_normale()
            print(f"    ┗━ ✓ Fine episodio FA — ritorno a ritmo normale (~{self.tempo_rimanente:.1f}s)")

    def prossimo_scenario(self, delta_t: float) -> str:
        """
        Avanza l'orologio interno di delta_t secondi e restituisce
        la chiave dello scenario (in SCENARI) da usare per il
        messaggio corrente.
        """
        if self.tempo_rimanente <= 0:
            self._transizione()

        self.tempo_rimanente -= delta_t
        return self.stato


def costruisci_payload_misto(generatore: GeneratoreMisto, delta_t: float = INTERVALLO_PUBBLICAZIONE) -> dict:
    """
    Costruisce un payload usando lo scenario corrente del generatore
    a episodi (normale/anomalia_ecg alternati con durate variabili).
    Riusa costruisci_payload() per non duplicare la logica di
    generazione dei singoli campi.
    """
    scenario_corrente = generatore.prossimo_scenario(delta_t)
    return costruisci_payload(scenario_corrente)


# ============================================================
# COSTRUZIONE PAYLOAD
# ============================================================

def costruisci_payload(scenario: str) -> dict:
    """
    Costruisce il payload MQTT passando correttamente IMU_SAMPLE_RATE (104).
    """
    s = SCENARI[scenario]
    
    # Chiama la funzione passando la costante (104) per avere campioni realistici
    imu_window = s["imu_fn"](n_campioni=IMU_SAMPLE_RATE)
    ultimo_campione = imu_window[-1]

    ecg_raw = s["ecg_fn"]()        
    rr_intervals = s["rr_fn"]()    

    return {
        "paziente_id":  PAZIENTE_ID,
        "ecg_raw":      ecg_raw,
        "rr_intervals": rr_intervals,
        "imu_window":   imu_window,   # Serie temporale densa inviata al server
        **ultimo_campione,            # Campi flat per la dashboard live
        "temperatura":  s["temp_fn"]()
    }

# ============================================================
# CALLBACKS MQTT
# ============================================================

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("Connesso al broker MQTT")
    else:
        print(f"Connessione fallita — codice: {reason_code}")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="CardioSense — Simulatore streaming dati paziente"
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARI.keys()) + ["misto"],
        default="normale",
        help="Scenario da simulare (default: normale). 'misto' alterna "
             "episodi normale/anomalia_ecg con durate variabili."
    )
    parser.add_argument(
        "--durata",
        type=int,
        default=60,
        help="Durata della simulazione in secondi (default: 60)"
    )
    parser.add_argument(
        "--intervallo",
        type=float,
        default=INTERVALLO_PUBBLICAZIONE,
        help="Intervallo tra messaggi in secondi (default: 1.0)"
    )
    parser.add_argument(
        "--perc-anomalia",
        type=float,
        default=0.2,
        help="Solo con --scenario misto: percentuale di tempo totale "
             "(0.0-1.0) passato in episodi di anomalia ECG (default: 0.2)"
    )
    args = parser.parse_args()

    is_misto = args.scenario == "misto"

    if is_misto:
        descrizione = (
            f"Misto — episodi alternati normale/anomalia_ecg "
            f"(~{args.perc_anomalia * 100:.0f}% del tempo in anomalia)"
        )
        generatore_misto = GeneratoreMisto(perc_anomalia=args.perc_anomalia)
    else:
        descrizione = SCENARI[args.scenario]['descrizione']
        if args.perc_anomalia != 0.2:
            print("Attenzione: --perc-anomalia è ignorato perché --scenario non è 'misto'\n")

    print(f"Scenario:  {args.scenario} — {descrizione}")
    print(f"Durata:    {args.durata}s")
    print(f"Intervallo: {args.intervallo}s")
    print(f"Paziente ID: {PAZIENTE_ID}")
    print(f"Campioni ECG per messaggio: {int(ECG_SAMPLE_RATE * ECG_WINDOW_SEC)}")
    print("-" * 60)

    client = mqtt.Client(
        client_id="cardiosense_simulator",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )
    client.on_connect = on_connect
    configura_tls(client)
    client.connect(
        os.getenv("MQTT_BROKER", "localhost"),
        get_mqtt_port()
    )
    client.loop_start()

    inizio = time.time()
    messaggi_inviati = 0

    try:
        while time.time() - inizio < args.durata:
            if is_misto:
                payload = costruisci_payload_misto(generatore_misto, delta_t=args.intervallo)
                scenario_label = generatore_misto.stato
            else:
                payload = costruisci_payload(args.scenario)
                scenario_label = args.scenario

            client.publish(
                TOPIC_DATI,
                json.dumps(payload),
                qos=1
            )
            messaggi_inviati += 1
            print(
                f"[{messaggi_inviati:3d}] ({scenario_label:13s}) Pubblicato — "
                f"ECG campioni: {len(payload['ecg_raw'])}, "
                f"RR: {payload['rr_intervals'][:3]}..., "
                f"Gyro: ({payload['gyro_x']:.1f}, {payload['gyro_y']:.1f}, {payload['gyro_z']:.1f}), "
                f"Temp: {payload['temperatura']}°C"
            )
            time.sleep(args.intervallo)

    except KeyboardInterrupt:
        print("\nSimulazione interrotta.")
    finally:
        client.loop_stop()
        client.disconnect()
        print(f"\nSimulazione completata — {messaggi_inviati} messaggi inviati.")