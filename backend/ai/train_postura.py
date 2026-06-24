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
    1:  'in_piedi',
    2:  'seduto',
    3:  'sdraiato',
    4:  'camminata',
    5:  'salita_scale',
    6:  'piegamento_gomito',
    7:  'piegamento_ginocchio',
    8:  'ciclismo',
    9:  'jogging',
    10: 'corsa',
    11: 'salto',
    12: 'squat'
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

FEATURE_COLS = ['acc_torace_x', 'acc_torace_y', 'acc_torace_z']

# ============================================================
# NUOVO STEP: ESTRAZIONE FEATURE A FINESTRE (SLIDING WINDOW)
# ============================================================
def estrai_feature_finestra(segnali_grezzi: np.ndarray, labels_grezze: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Trasforma i segnali continui in finestre temporali ed estrae feature statistiche.
    MHEALTH è a 50Hz -> 100 campioni = 2 secondi di attività.
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
        
        # Estrazione feature per asse (X, Y, Z)
        medie = np.mean(finestra, axis=0)
        stds = np.std(finestra, axis=0)
        mins = np.min(finestra, axis=0)
        maxs = np.max(finestra, axis=0)
        
        # Signal Magnitude Area (SMA) -> Ottimo indicatore di energia motoria complessiva
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
    print("Caricamento dataset MHEALTH con Feature Engineering...")
    
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
    
    print(f"\nDataset convertito in {X_totale.shape[0]} finestre temporali.")
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
    
    print(f"\nTraining di Random Forest su {X_train.shape[0]} finestre...")
    
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
    
    print(f"\nModello ottimizzato salvato in: {MODEL_PATH}")

if __name__ == '__main__':
    train()