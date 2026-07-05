import wfdb
import numpy as np
import joblib
import os
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

# ============================================================
# CONFIGURAZIONE
# ============================================================

# Record disponibili nel database chfdb su PhysioNet
# Sono 15 pazienti, ciascuno con un ID
RECORDS = [
    'chf01', 'chf02', 'chf03', 'chf04', 'chf05',
    'chf06', 'chf07', 'chf08', 'chf09', 'chf10',
    'chf11', 'chf12', 'chf13', 'chf14', 'chf15'
]

# Cartella PhysioNet da cui scaricare (on-demand, no download manuale)
PHYSIONET_DIR = 'chfdb'

# Dove salvare il modello addestrato
MODEL_PATH = 'backend/ai/trained/ecg_model.pkl'

# --------------------------------------------------------
# Cache locale delle feature chfdb già estratte (X, y).
#
# Ancorata alla posizione di QUESTO file (backend/ai/) invece che alla
# cwd del processo che lo importa, per lo stesso motivo già documentato
# in db/mqtt_tls.py: retrain_scheduler.py viene lanciato da backend/,
# ma altri entry point potrebbero girare da directory diverse. Un path
# relativo tipo 'backend/ai/trained/...' risolverebbe in modo diverso
# (e nella maggior parte dei casi sbagliato, creando una cartella
# backend/backend/...) a seconda di da dove viene lanciato lo script.
# --------------------------------------------------------
_AI_DIR = Path(__file__).resolve().parent
CACHE_FEATURES_PATH = str(_AI_DIR / "trained" / "chfdb_features_cache.npz")

# Incrementare se cambia la logica di estrazione feature (estrai_rr):
# la cache viene invalidata automaticamente se il numero di versione
# non combacia, evitando che RetrainService continui silenziosamente
# a usare feature calcolate con una logica ormai superata.
FEATURE_VERSION = 1

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


def carica_dataset_con_cache(forza_refresh: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """
    Variante di carica_dataset() con cache su disco (CACHE_FEATURES_PATH).

    Usata da RetrainService per evitare di riscaricare ~15 record da
    PhysioNet e ricalcolare le finestre R-R ad ogni retrain notturno:
    la prima chiamata popola la cache, le successive la leggono
    direttamente. La cache viene invalidata automaticamente se
    FEATURE_VERSION non combacia (es. dopo una modifica a estrai_rr).

    Args:
        forza_refresh: se True, ignora la cache esistente e ricalcola
            comunque da PhysioNet (utile per rigenerarla manualmente).
    """
    if not forza_refresh and os.path.exists(CACHE_FEATURES_PATH):
        try:
            dati = np.load(CACHE_FEATURES_PATH)
            if int(dati.get('version', -1)) == FEATURE_VERSION:
                print(f"Carico feature chfdb dalla cache: {CACHE_FEATURES_PATH}")
                return dati['X'], dati['y']
            print("Cache chfdb obsoleta (FEATURE_VERSION cambiata), ricalcolo...")
        except Exception as e:
            print(f"Cache chfdb illeggibile ({e}), ricalcolo da PhysioNet...")

    X, y = carica_dataset()

    cartella_cache = os.path.dirname(CACHE_FEATURES_PATH)
    if cartella_cache and not os.path.exists(cartella_cache):
        os.makedirs(cartella_cache)

    np.savez(CACHE_FEATURES_PATH, X=X, y=y, version=FEATURE_VERSION)
    print(f"Feature chfdb salvate in cache: {CACHE_FEATURES_PATH}")

    return X, y


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
    
    # Estrae la cartella di destinazione dal percorso del modello ('backend/ai/trained')
    dir_modello = os.path.dirname(MODEL_PATH)
    
    # Crea la cartella e le sue sottocartelle se non esistono già
    if dir_modello and not os.path.exists(dir_modello):
        os.makedirs(dir_modello)
        print(f"Cartella creata: {dir_modello}")
        
    joblib.dump(modello, MODEL_PATH)
    print(f"\nModello salvato in: {MODEL_PATH}")

    # Popola subito anche la cache delle feature chfdb: il primo
    # retrain notturno (retrain_scheduler.py) non dovrà quindi
    # ricontattare PhysioNet, a patto di aver eseguito questo script
    # almeno una volta durante il setup iniziale del progetto.
    cartella_cache = os.path.dirname(CACHE_FEATURES_PATH)
    if cartella_cache and not os.path.exists(cartella_cache):
        os.makedirs(cartella_cache)
    np.savez(CACHE_FEATURES_PATH, X=X, y=y, version=FEATURE_VERSION)
    print(f"Cache feature chfdb aggiornata in: {CACHE_FEATURES_PATH}")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == '__main__':
    train()