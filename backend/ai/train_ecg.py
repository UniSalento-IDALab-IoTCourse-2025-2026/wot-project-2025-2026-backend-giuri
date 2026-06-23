import wfdb
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

# ============================================================
# CONFIGURAZIONE
# ============================================================

# Record disponibili nel database chfdb su PhysioNet
# Sono 15 pazienti, ciascuno con un ID
RECORDS = [
    'chf201', 'chf202', 'chf203', 'chf204', 'chf205',
    'chf206', 'chf207', 'chf208', 'chf209', 'chf210',
    'chf211', 'chf212', 'chf213', 'chf214', 'chf215'
]

# Cartella PhysioNet da cui scaricare (on-demand, no download manuale)
PHYSIONET_DIR = 'chfdb'

# Dove salvare il modello addestrato
MODEL_PATH = 'backend/ai/trained/ecg_model.pkl'

# ============================================================
# STEP 1 — ESTRAZIONE INTERVALLI R-R
# ============================================================

def estrai_rr(record_name: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Scarica un record da PhysioNet e estrae gli intervalli R-R
    e le relative annotazioni (normale/anomalo).
    
    Restituisce:
        features: array di finestre di intervalli R-R
        labels: array di etichette (0=normale, 1=anomalo)
    """
    print(f"  Carico record {record_name}...")
    
    try:
        # Scarica le annotazioni del record da PhysioNet
        # Le annotazioni indicano la posizione di ogni battito
        ann = wfdb.rdann(record_name, 'ecg', pn_dir=PHYSIONET_DIR)
    except Exception as e:
        print(f"  Errore su {record_name}: {e}")
        return np.array([]), np.array([])
    
    # I campioni sono le posizioni temporali dei battiti (in campioni)
    campioni = ann.sample
    
    # I simboli indicano il tipo di battito
    # 'N' = normale, tutto il resto = anomalo
    simboli = ann.symbol
    
    # Calcola gli intervalli R-R (differenza tra battiti consecutivi)
    # L'intervallo R-R è il tempo tra due battiti in ms
    # chfdb è campionato a 250 Hz → dividiamo per 250 per avere secondi
    rr_intervals = np.diff(campioni) / 250.0
    
    # Le label corrispondono al secondo battito di ogni coppia
    labels_raw = simboli[1:]
    
    # Converti simboli in binario: 0=normale, 1=anomalo
    labels = np.array([0 if s == 'N' else 1 for s in labels_raw])
    
    # --------------------------------------------------------
    # Crea finestre di 10 intervalli R-R consecutivi
    # Il modello analizza una sequenza, non un singolo valore
    # --------------------------------------------------------
    WINDOW_SIZE = 10
    features = []
    label_finestre = []
    
    for i in range(len(rr_intervals) - WINDOW_SIZE):
        finestra = rr_intervals[i:i + WINDOW_SIZE]
        
        # Estrai feature statistiche dalla finestra
        features.append([
            np.mean(finestra),    # media R-R
            np.std(finestra),     # variabilità R-R (HRV)
            np.min(finestra),     # minimo
            np.max(finestra),     # massimo
            np.max(finestra) - np.min(finestra),  # range
        ])
        
        # L'etichetta della finestra è anomala se almeno
        # un battito nella finestra è anomalo
        label_finestre.append(
            1 if np.any(labels[i:i + WINDOW_SIZE] == 1) else 0
        )
    
    return np.array(features), np.array(label_finestre)


# ============================================================
# STEP 2 — CARICAMENTO DI TUTTI I RECORD
# ============================================================

def carica_dataset() -> tuple[np.ndarray, np.ndarray]:
    """
    Itera su tutti i record di chfdb e costruisce
    il dataset completo di training.
    """
    print("Caricamento dataset chfdb da PhysioNet...")
    
    X_totale = []
    y_totale = []
    
    for record in RECORDS:
        X, y = estrai_rr(record)
        if len(X) > 0:
            X_totale.append(X)
            y_totale.append(y)
    
    # Concatena tutti i record in un unico array
    X_totale = np.concatenate(X_totale, axis=0)
    y_totale = np.concatenate(y_totale, axis=0)
    
    print(f"Dataset caricato: {X_totale.shape[0]} finestre totali")
    print(f"  Normali:  {np.sum(y_totale == 0)}")
    print(f"  Anomale:  {np.sum(y_totale == 1)}")
    
    return X_totale, y_totale


# ============================================================
# STEP 3 — TRAINING DEL MODELLO
# ============================================================

def train():
    # Carica il dataset
    X, y = carica_dataset()
    
    # Split 80% training, 20% test
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=0.2,
        random_state=42,
        stratify=y  # mantieni proporzione classi in entrambi i set
    )
    
    print(f"\nTraining su {X_train.shape[0]} finestre...")
    
    # Addestra Random Forest
    # class_weight='balanced' compensa lo sbilanciamento
    # tra battiti normali (molti) e anomali (pochi)
    modello = RandomForestClassifier(
        n_estimators=100,       # numero di alberi
        class_weight='balanced',
        random_state=42,
        n_jobs=-1               # usa tutti i core disponibili
    )
    modello.fit(X_train, y_train)
    
    # --------------------------------------------------------
    # Valutazione sul test set
    # --------------------------------------------------------
    print("\nValutazione sul test set:")
    y_pred = modello.predict(X_test)
    print(classification_report(
        y_test, y_pred,
        target_names=['Normale', 'Anomalo']
    ))
    
    # --------------------------------------------------------
    # Salva il modello addestrato
    # --------------------------------------------------------
    joblib.dump(modello, MODEL_PATH)
    print(f"\nModello salvato in: {MODEL_PATH}")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == '__main__':
    train()