import numpy as np
import pandas as pd
import joblib
import os
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from pathlib import Path

# ============================================================
# CONFIGURAZIONE
# ============================================================
DATASET_PATH = 'dataset/mhealth/'
MODEL_PATH = 'backend/ai/trained/postura_model.pkl'

ETICHETTE = {
    0:  'nessuna_attivita',
    1:  'in_piedi',                      # L1 - Standing still
    2:  'seduto',                        # L2 - Sitting and relaxing
    3:  'sdraiato',                      # L3 - Lying down
    4:  'camminata',                     # L4 - Walking
    5:  'salita_scale',                  # L5 - Climbing stairs
    6:  'piegamento_busto_avanti',       # L6 - Waist bends forward
    7:  'elevazione_frontale_braccia',   # L7 - Frontal elevation of arms
    8:  'piegamento_ginocchia',          # L8 - Knees bending (crouching)
    9:  'ciclismo',                      # L9 - Cycling
    10: 'jogging',                       # L10 - Jogging
    11: 'corsa',                         # L11 - Running
    12: 'salto'                          # L12 - Jump front & back
}

COLONNE = [
    'acc_torace_x', 'acc_torace_y', 'acc_torace_z',
    'ecg_1', 'ecg_2',
    'acc_caviglia_x', 'acc_caviglia_y', 'acc_caviglia_z',
    'giro_caviglia_x', 'giro_caviglia_y', 'giro_caviglia_z',
    'mag_caviglia_x', 'mag_caviglia_y', 'mag_caviglia_z',
    'acc_braccio_x', 'acc_braccio_y', 'acc_braccio_z',
    'giro_braccio_x', 'giro_braccio_y', 'giro_braccio_z',
    'mag_braccio_x', 'mag_braccio_y', 'mag_braccio_z',
    'activity_label'
]

# --------------------------------------------------------
# CAMBIO PUNTO DI ATTACCO: braccio (polso) invece che petto.
# Motivo: in MHEALTH il sensore toracico espone SOLO
# l'accelerometro (nessun giroscopio a quel punto anatomico),
# mentre il sensore da braccio espone sia acc che giroscopio —
# è l'unico che permette di addestrare un modello a 6 assi
# coerente con il dispositivo reale (IIT BioDataAcq), che sul
# polso ha sia accelerometro sia giroscopio disponibili.
# --------------------------------------------------------
FEATURE_COLS = [
    'acc_braccio_x', 'acc_braccio_y', 'acc_braccio_z',
    'giro_braccio_x', 'giro_braccio_y', 'giro_braccio_z',
]

# --------------------------------------------------------
# Bug #3: MHEALTH contiene 12 classi (0-12), ma al dispositivo reale
# interessano solo 8 attività: in_piedi, seduto, sdraiato, camminata,
# salita_scale, corsa, salto, squat. Includere le altre 4
# (piegamento_gomito, piegamento_ginocchio, ciclismo, jogging) nel
# training introduce confusione: il modello può "scivolare" su una di
# queste classi indesiderate anche quando la vera attività è una di
# quelle che servono. Il filtro va applicato PRIMA della segmentazione
# a finestre (estrai_feature_finestra), altrimenti campioni delle
# classi escluse contaminerebbero comunque la maggioranza di una
# finestra confinante.
# --------------------------------------------------------
LABELS_DESIDERATE = {1, 2, 3, 4, 5, 11, 12}

# ============================================================
# NUOVO STEP: ESTRAZIONE FEATURE A FINESTRE (SLIDING WINDOW)
# ============================================================
def estrai_feature_finestra(segnali_grezzi: np.ndarray, labels_grezze: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Trasforma i segnali continui in finestre temporali ed estrae feature statistiche.
    MHEALTH è a 50Hz -> 100 campioni = 2 secondi di attività.

    Generico rispetto al numero di colonne in FEATURE_COLS: con 6 colonne
    (acc_x,y,z + giro_x,y,z) ogni finestra produce 6*4 + 1 = 25 feature
    (media, std, min, max per asse + SMA aggregato), contro le 13 di
    prima quando si usava solo l'accelerometro a 3 assi.
    """
    WINDOW_SIZE = 100 
    STEP_SIZE = 50     # Overlap del 50%
    
    features = []
    labels = []
    
    for i in range(0, len(segnali_grezzi) - WINDOW_SIZE, STEP_SIZE):
        finestra = segnali_grezzi[i:i + WINDOW_SIZE]
        finestra_labels = labels_grezze[i:i + WINDOW_SIZE]
        
        # Sincronizzazione label: prendiamo l'attività più frequente nella finestra
        # (Se l'utente cambia attività a metà, vince la maggioranza)
        valori, conteggi = np.unique(finestra_labels, return_counts=True)
        label_finestra = valori[np.argmax(conteggi)]
        
        # Estrazione feature per asse (Ax, Ay, Az, Gx, Gy, Gz)
        medie = np.mean(finestra, axis=0)
        stds = np.std(finestra, axis=0)
        mins = np.min(finestra, axis=0)
        maxs = np.max(finestra, axis=0)
        
        # Signal Magnitude Area (SMA) -> Ottimo indicatore di energia motoria complessiva.
        # Calcolata sulla somma di TUTTI gli assi disponibili (ora anche il giroscopio),
        # quindi cattura sia intensità del movimento lineare che rotazionale del polso.
        sma = np.mean(np.sum(np.abs(finestra), axis=1))
        
        # Uniamo tutte le feature calcolate in un unico vettore
        vettore_feature = np.hstack([medie, stds, mins, maxs, sma])
        
        features.append(vettore_feature)
        labels.append(label_finestra)
        
    return np.array(features), np.array(labels)

# ============================================================
# STEP 1 — CARICAMENTO E PRE-ELABORAZIONE
# ============================================================
def carica_dataset() -> tuple[np.ndarray, np.ndarray]:
    print("Caricamento dataset MHEALTH con Feature Engineering (acc+giro braccio)...")
    
    X_totale = []
    y_totale = []
    
    files = sorted(Path(DATASET_PATH).glob('mHealth_subject*.log'))
    if len(files) == 0:
        raise FileNotFoundError(f"Nessun file .log trovato in {DATASET_PATH}.")
    
    for file in files:
        print(f"  Elaborazione {file.name}...")
        df = pd.read_csv(file, sep='\t', names=COLONNE, header=None)
        
        # Rimuoviamo i momenti di inattività
        df = df[df['activity_label'] != 0]

        # Bug #3: teniamo solo le 8 classi che interessano al dispositivo
        # reale, scartando le 4 attività MHEALTH non rilevanti
        df = df[df['activity_label'].isin(LABELS_DESIDERATE)]

        if df.empty:
            continue
            
        X_grezzo = df[FEATURE_COLS].values
        y_grezzo = df['activity_label'].values.astype(int)
        
        # Trasformiamo i dati grezzi di questo soggetto in finestre significative
        X_finestre, y_finestre = estrai_feature_finestra(X_grezzo, y_grezzo)
        
        if len(X_finestre) > 0:
            X_totale.append(X_finestre)
            y_totale.append(y_finestre)
    
    X_totale = np.concatenate(X_totale, axis=0)
    y_totale = np.concatenate(y_totale, axis=0)
    
    print(f"\nDataset convertito in {X_totale.shape[0]} finestre temporali "
          f"({X_totale.shape[1]} feature per finestra: 6 assi × 4 statistiche + 1 SMA).")
    print("Distribuzione nuove macro-attività:")
    for label, count in zip(*np.unique(y_totale, return_counts=True)):
        print(f"  {ETICHETTE[label]}: {count}")
    
    return X_totale, y_totale

# ============================================================
# STEP 2 — TRAINING DEL MODELLO
# ============================================================
def train():
    X, y = carica_dataset()
    
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=0.2,
        random_state=42,
        stratify=y
    )
    
    print(f"\nTraining di Random Forest su {X_train.shape[0]} finestre "
          f"({X_train.shape[1]} feature: acc+giro braccio)...")
    
    modello = RandomForestClassifier(
        n_estimators=100,
        random_state=42,
        class_weight='balanced', # Bilancia le classi (come squat)
        n_jobs=-1
    )
    modello.fit(X_train, y_train)
    
    print("\nValutazione sul test set modificato:")
    y_pred = modello.predict(X_test)
    
    # Estraiamo i nomi delle etichette effettivamente presenti nel set
    classi_presenti = sorted(list(np.unique(y)))
    nomi_target = [ETICHETTE[i] for i in classi_presenti]
    
    print(classification_report(
        y_test, y_pred,
        target_names=nomi_target
    ))
    
    # Assicuriamoci che la cartella esista prima del dump
    dir_modello = os.path.dirname(MODEL_PATH)
    if dir_modello and not os.path.exists(dir_modello):
        os.makedirs(dir_modello)
        
    joblib.dump({
        'modello': modello,
        'etichette': ETICHETTE
    }, MODEL_PATH)
    
    print(f"\nModello ottimizzato (acc+giro braccio) salvato in: {MODEL_PATH}")

if __name__ == '__main__':
    train()