import os
import tempfile
import numpy as np
import joblib
from repositories.annotation_repository import AnnotationRepository
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

from ai.train_ecg import carica_dataset_con_cache

ECG_MODEL_PATH = "backend/ai/trained/ecg_model.pkl"

# Numero minimo di NUOVE validazioni mediche richieste per giustificare
# un retrain notturno. Non è più (come in precedenza) la dimensione
# dell'intero training set: chfdb resta sempre la base statistica,
# questa soglia serve solo a evitare retrain inutili quando non è
# arrivato nuovo segnale clinico dal medico.
MIN_VALIDAZIONI_PER_RETRAIN = 10


class RetrainService:
    """
    Gestisce il ri-addestramento periodico del modello ECG.

    A differenza di una versione precedente, il modello NON viene più
    addestrato da zero solo sulle validazioni mediche: viene invece
    addestrato sull'UNIONE di:

      1. Il dataset chfdb originale (via cache locale, vedi
         ai/train_ecg.py — carica_dataset_con_cache), che resta la
         base statistica di migliaia di finestre R-R;
      2. Le annotazioni validate dal medico su MongoDB, che aggiungono
         segnale clinico specifico ai pazienti reali monitorati.

    Questo evita che un numero ancora ridotto di validazioni (10-50,
    statisticamente fragili e potenzialmente sbilanciate) sovrascriva
    la conoscenza di base appresa da chfdb — le validazioni SI
    AGGIUNGONO, non sostituiscono.
    """

    def __init__(self, annotation_repo: AnnotationRepository, model_path: str = ECG_MODEL_PATH):
        self.repo = annotation_repo
        self.model_path = model_path

    def _estrai_features(self, rr_intervals: list) -> list:
        """
        Estrae le stesse 5 feature usate in train_ecg.py/ECGClassifier
        (media, std, min, max, range degli intervalli R-R), così le
        feature delle validazioni sono nello stesso spazio di quelle
        di chfdb e possono essere concatenate direttamente.
        """
        rr = np.array(rr_intervals)
        return [
            np.mean(rr),
            np.std(rr),
            np.min(rr),
            np.max(rr),
            np.max(rr) - np.min(rr)
        ]

    def _estrai_features_validazioni(self) -> tuple[np.ndarray, np.ndarray, int]:
        """
        Estrae (X, y) dalle annotazioni validate dal medico su MongoDB.
        Restituisce anche il conteggio di documenti effettivamente
        utilizzabili (dopo il filtraggio), usato per decidere se
        procedere col retrain.
        """
        documenti = self.repo.find_validated_for_retraining()

        X, y = [], []
        for doc in documenti:
            rr = doc.get("rr_intervals")
            esito = doc.get("esito_medico")

            if not rr or not esito:
                continue

            X.append(self._estrai_features(rr))
            # vero_positivo = 1 (anomalia confermata dal medico)
            # falso_allarme = 0 (il medico ha giudicato non clinico l'evento)
            y.append(1 if esito == "vero_positivo" else 0)

        if not X:
            return np.array([]).reshape(0, 5), np.array([]), 0

        return np.array(X), np.array(y), len(X)

    def _salva_modello_atomico(self, modello) -> None:
        """
        Scrive il nuovo modello su un file temporaneo nella stessa
        cartella di destinazione e poi lo rinomina sopra il .pkl
        definitivo con os.replace().

        os.replace() è atomico sullo stesso filesystem: i processi che
        tengono il modello in memoria (ECGClassifier in
        mqtt_subscriber.py e fastapi_server.py) controllano il mtime
        del file prima di ogni predizione e lo ricaricano quando
        cambia — la scrittura atomica garantisce che non lo trovino
        mai a metà scrittura, evitando un joblib.load() corrotto o
        parziale durante il reload a caldo.
        """
        cartella_destinazione = os.path.dirname(self.model_path) or "."
        os.makedirs(cartella_destinazione, exist_ok=True)

        fd, percorso_temp = tempfile.mkstemp(
            dir=cartella_destinazione,
            prefix=".ecg_model_",
            suffix=".pkl.tmp"
        )
        os.close(fd)

        try:
            joblib.dump(modello, percorso_temp)
            os.replace(percorso_temp, self.model_path)
        except Exception:
            # Pulizia del file temporaneo in caso di errore a metà scrittura
            if os.path.exists(percorso_temp):
                os.remove(percorso_temp)
            raise

    def ritrain(self) -> bool:
        """
        Combina chfdb (via cache) + validazioni mediche, addestra un
        nuovo Random Forest sull'unione e salva il modello in modo
        atomico.

        Restituisce True se il retrain è stato eseguito, False se
        saltato (validazioni insufficienti o dataset chfdb non
        disponibile).
        """
        X_validazioni, y_validazioni, n_validazioni = self._estrai_features_validazioni()

        if n_validazioni < MIN_VALIDAZIONI_PER_RETRAIN:
            print(f"Validazioni insufficienti per il retrain "
                  f"({n_validazioni}/{MIN_VALIDAZIONI_PER_RETRAIN}). Salto.")
            return False

        try:
            print(f"Carico base chfdb (cache) + {n_validazioni} validazioni mediche...")
            X_chfdb, y_chfdb = carica_dataset_con_cache()
        except Exception as e:
            # Se la cache non esiste ancora e PhysioNet non è
            # raggiungibile (es. macchina offline nel cuore della
            # notte), il retrain va saltato invece di propagare
            # l'eccezione: meglio nessun retrain che un modello
            # addestrato solo su poche decine di validazioni.
            print(f"Impossibile caricare la base chfdb, retrain saltato: {e}")
            return False

        if X_chfdb.shape[0] == 0:
            print("Base chfdb vuota, retrain saltato.")
            return False

        # Unione dei due dataset: chfdb resta la base statistica, le
        # validazioni si aggiungono senza sostituirla.
        X = np.concatenate([X_chfdb, X_validazioni], axis=0)
        y = np.concatenate([y_chfdb, y_validazioni], axis=0)

        print(f"Dataset combinato: {X.shape[0]} finestre totali "
              f"({X_chfdb.shape[0]} chfdb + {n_validazioni} validate)")

        # Split di valutazione: utile per loggare le metriche di ogni
        # ciclo notturno (non solo in fase di training iniziale), così
        # da accorgersi se le nuove validazioni stanno peggiorando le
        # prestazioni invece di scoprirlo solo in produzione.
        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=0.2,
            random_state=42,
            stratify=y
        )

        modello_valutazione = RandomForestClassifier(
            n_estimators=100,
            class_weight='balanced',
            random_state=42,
            n_jobs=1
        )
        modello_valutazione.fit(X_train, y_train)

        print("\nValutazione sul test set (dataset combinato):")
        y_pred = modello_valutazione.predict(X_test)
        print(classification_report(
            y_test, y_pred,
            target_names=['Normale', 'Anomalo']
        ))

        # Modello finale addestrato su TUTTI i dati disponibili
        # (train+test), quello effettivamente distribuito: lo split
        # sopra serve solo a valutare la qualità di questo ciclo di
        # retrain, non a ridurre i dati usati in produzione.
        modello_finale = RandomForestClassifier(
            n_estimators=100,
            class_weight='balanced',
            random_state=42,
            n_jobs=1
        )
        modello_finale.fit(X, y)

        self._salva_modello_atomico(modello_finale)
        print(f"Modello ri-addestrato con {X.shape[0]} campioni totali "
              f"e salvato in {self.model_path}.")
        return True