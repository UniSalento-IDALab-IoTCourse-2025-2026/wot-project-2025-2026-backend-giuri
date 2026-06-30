import os
import tempfile
import numpy as np
import joblib
from repositories.annotation_repository import AnnotationRepository
from sklearn.ensemble import RandomForestClassifier

ECG_MODEL_PATH = "backend/ai/trained/ecg_model.pkl"


class RetrainService:
    """
    Gestisce il ri-addestramento periodico del modello ECG
    con i dati validati dal medico.
    """

    def __init__(self, annotation_repo: AnnotationRepository, model_path: str = ECG_MODEL_PATH):
        self.repo = annotation_repo
        self.model_path = model_path

    def _estrai_features(self, rr_intervals: list) -> np.ndarray:
        """
        Estrae le stesse feature usate durante il training iniziale.
        """
        rr = np.array(rr_intervals)
        return [
            np.mean(rr),
            np.std(rr),
            np.min(rr),
            np.max(rr),
            np.max(rr) - np.min(rr)
        ]

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
        Estrae le annotazioni validate dal medico,
        le usa per ri-addestrare il modello ECG
        e salva il nuovo .pkl.

        Restituisce True se il ri-addestramento è andato a buon fine.
        """
        documenti = self.repo.find_validated_for_retraining()

        if len(documenti) < 10:
            print("Dati insufficienti per il ri-addestramento "
                  f"({len(documenti)} documenti validati).")
            return False

        X = []
        y = []

        for doc in documenti:
            rr = doc.get("rr_intervals")
            esito = doc.get("esito_medico")

            if not rr or not esito:
                continue

            X.append(self._estrai_features(rr))
            # vero_positivo = 1 (anomalia confermata)
            # falso_allarme = 0 (normale)
            y.append(1 if esito == "vero_positivo" else 0)

        if len(X) < 10:
            print("Feature insufficienti dopo il filtraggio.")
            return False

        X = np.array(X)
        y = np.array(y)

        # Addestra il nuovo modello
        modello = RandomForestClassifier(
            n_estimators=100,
            class_weight='balanced',
            random_state=42,
            n_jobs=1
        )
        modello.fit(X, y)

        self._salva_modello_atomico(modello)
        print(f"Modello ri-addestrato con {len(X)} campioni validati "
              f"e salvato in {self.model_path}.")
        return True