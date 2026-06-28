import json
import time
import random
import math
import numpy as np
import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURAZIONE
# ============================================================

TOPIC_DATI = "cardiosense/dati"
PAZIENTE_ID = "OMU9YFPR"  # codice paziente di test

# Frequenza di campionamento ECG in Hz
ECG_SAMPLE_RATE = 250

# Durata della finestra ECG pubblicata per ogni messaggio (secondi)
ECG_WINDOW_SEC = 1.0

# Frequenza di pubblicazione messaggi (secondi)
INTERVALLO_PUBBLICAZIONE = 1.0

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
# GENERATORI ACCELEROMETRO
# ============================================================

def genera_accelerometro_normale() -> dict:
    return {
        "acc_x": round(random.uniform(-0.05, 0.05), 3),
        "acc_y": round(random.uniform(-0.05, 0.05), 3),
        "acc_z": round(random.uniform(0.98, 1.02), 3)
    }


def genera_accelerometro_movimento() -> dict:
    return {
        "acc_x": round(random.uniform(-0.6, 0.6), 3),
        "acc_y": round(random.uniform(-0.6, 0.6), 3),
        "acc_z": round(random.uniform(0.5, 1.5), 3)
    }


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
        "acc_fn":  genera_accelerometro_normale,
        "temp_fn": genera_temperatura_normale
    },
    "anomalia_ecg": {
        "descrizione": "Fibrillazione atriale, altri parametri normali",
        "ecg_fn":  genera_ecg_raw_anomalo,
        "rr_fn":   genera_rr_anomalo,
        "acc_fn":  genera_accelerometro_normale,
        "temp_fn": genera_temperatura_normale
    },
    "febbre": {
        "descrizione": "Temperatura elevata, ECG normale",
        "ecg_fn":  genera_ecg_raw_normale,
        "rr_fn":   genera_rr_normale,
        "acc_fn":  genera_accelerometro_normale,
        "temp_fn": genera_temperatura_febbre
    },
    "movimento": {
        "descrizione": "Paziente in movimento, ECG normale",
        "ecg_fn":  genera_ecg_raw_normale,
        "rr_fn":   genera_rr_normale,
        "acc_fn":  genera_accelerometro_movimento,
        "temp_fn": genera_temperatura_normale
    }
}


# ============================================================
# COSTRUZIONE PAYLOAD
# ============================================================

def costruisci_payload(scenario: str) -> dict:
    """
    Costruisce il payload MQTT con:
    - ecg_raw: campioni grezzi sintetici realistici (250 float per 1s a 250Hz)
    - rr_intervals: intervalli R-R pre-calcolati coerenti con lo scenario
      (il subscriber li usa direttamente se presenti, saltando la peak detection)
    """
    s = SCENARI[scenario]
    acc = s["acc_fn"]()

    ecg_raw = s["ecg_fn"]()        # 250 campioni ECG realistici
    rr_intervals = s["rr_fn"]()    # 10 intervalli R-R coerenti

    return {
        "paziente_id": PAZIENTE_ID,
        "ecg_raw":     ecg_raw,
        "rr_intervals": rr_intervals,
        "acc_x":       acc["acc_x"],
        "acc_y":       acc["acc_y"],
        "acc_z":       acc["acc_z"],
        "temperatura": s["temp_fn"]()
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
        choices=list(SCENARI.keys()),
        default="normale",
        help="Scenario da simulare (default: normale)"
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
    args = parser.parse_args()

    print(f"Scenario:  {args.scenario} — {SCENARI[args.scenario]['descrizione']}")
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
    client.connect(
        os.getenv("MQTT_BROKER", "localhost"),
        int(os.getenv("MQTT_PORT", 1883))
    )
    client.loop_start()

    inizio = time.time()
    messaggi_inviati = 0

    try:
        while time.time() - inizio < args.durata:
            payload = costruisci_payload(args.scenario)
            client.publish(
                TOPIC_DATI,
                json.dumps(payload),
                qos=1
            )
            messaggi_inviati += 1
            print(
                f"[{messaggi_inviati:3d}] Pubblicato — "
                f"ECG campioni: {len(payload['ecg_raw'])}, "
                f"RR: {payload['rr_intervals'][:3]}..., "
                f"Temp: {payload['temperatura']}°C"
            )
            time.sleep(args.intervallo)

    except KeyboardInterrupt:
        print("\nSimulazione interrotta.")
    finally:
        client.loop_stop()
        client.disconnect()
        print(f"\nSimulazione completata — {messaggi_inviati} messaggi inviati.")