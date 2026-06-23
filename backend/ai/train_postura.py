import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from pathlib import Path

# ============================================================
# CONFIGURAZIONE
# ============================================================

# Cartella dove hai messo i file .log di MHEALTH
DATASET_PATH = 'dataset/mhealth/'

# Dove salvare il modello addestrato
MODEL_PATH = 'backend/ai/trained/postura_model.pkl'

# ============================================================
# ETICHETTE MHEALTH
# Le attività sono codificate come numeri interi nel dataset
# Fonte: documentazione ufficiale MHEALTH
# ============================================================
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

# Nomi delle colonne secondo documentazione MHEALTH
COLONNE = [
    # Accelerometro torace (3 assi)
    'acc_torace_x', 'acc_torace_y', 'acc_torace_z',
    # ECG (non lo usiamo per la postura)
    'ecg_1', 'ecg_2',
    # Accelerometro caviglia sinistra (3 assi)
    'acc_caviglia_x', 'acc_caviglia_y', 'acc_caviglia_z',
    # Giroscopio caviglia sinistra
    'giro_caviglia_x', 'giro_caviglia_y', 'giro_caviglia_z',
    # Magnetometro caviglia sinistra
    'mag_caviglia_x', 'mag_caviglia_y', 'mag_caviglia_z',
    # Accelerometro braccio destro (3 assi)
    'acc_braccio_x', 'acc_braccio_y', 'acc_braccio_z',
    # Giroscopio braccio destro
    'giro_braccio_x', 'giro_braccio_y', 'giro_braccio_z',
    # Magnetometro braccio destro
    'mag_braccio_x', 'mag_braccio_y', 'mag_braccio_z',
    # Etichetta attività
    'activity_label'
]

# Feature che usiamo — solo accelerometro torace
FEATURE_COLS = ['acc_torace_x', 'acc_torace_y', 'acc_torace_z']

# ============================================================
# STEP 1 — CARICAMENTO DEL DATASET
# ============================================================

def carica_dataset() -> tuple[np.ndarray, np.ndarray]:
    """
    Carica tutti i file .log di MHEALTH e costruisce
    il dataset completo di training.
    """
    print("Caricamento dataset MHEALTH...")
    
    X_totale = []
    y_totale = []
    
    # Cerca tutti i file .log nella cartella dataset
    files = sorted(Path(DATASET_PATH).glob('mHealth_subject*.log'))
    
    if len(files) == 0:
        raise FileNotFoundError(
            f"Nessun file .log trovato in {DATASET_PATH}. "
            f"Assicurati di aver copiato i file di MHEALTH nella cartella corretta."
        )
    
    for file in files:
        print(f"  Carico {file.name}...")
        
        df = pd.read_csv(
            file,
            sep='\t',
            names=COLONNE,
            header=None
        )
        
        # Rimuovi righe con etichetta 0 (nessuna attività)
        df = df[df['activity_label'] != 0]
        
        # Estrai feature e label
        X = df[FEATURE_COLS].values
        y = df['activity_label'].values.astype(int)
        
        X_totale.append(X)
        y_totale.append(y)
    
    X_totale = np.concatenate(X_totale, axis=0)
    y_totale = np.concatenate(y_totale, axis=0)
    
    print(f"Dataset caricato: {X_totale.shape[0]} campioni totali")
    print("Distribuzione attività:")
    for label, count in zip(*np.unique(y_totale, return_counts=True)):
        print(f"  {ETICHETTE[label]}: {count}")
    
    return X_totale, y_totale


# ============================================================
# STEP 2 — TRAINING DEL MODELLO
# ============================================================

def train():
    X, y = carica_dataset()
    
    # Split 80/20
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=0.2,
        random_state=42,
        stratify=y
    )
    
    print(f"\nTraining su {X_train.shape[0]} campioni...")
    
    modello = RandomForestClassifier(
        n_estimators=100,
        random_state=42,
        n_jobs=-1
    )
    modello.fit(X_train, y_train)
    
    # Valutazione
    print("\nValutazione sul test set:")
    y_pred = modello.predict(X_test)
    print(classification_report(
        y_test, y_pred,
        target_names=[ETICHETTE[i] for i in sorted(ETICHETTE.keys()) if i != 0]
    ))
    
    # Salva modello e dizionario etichette insieme
    # così quando facciamo predict sappiamo a cosa
    # corrisponde ogni numero
    joblib.dump({
        'modello': modello,
        'etichette': ETICHETTE
    }, MODEL_PATH)
    
    print(f"\nModello salvato in: {MODEL_PATH}")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == '__main__':
    train()