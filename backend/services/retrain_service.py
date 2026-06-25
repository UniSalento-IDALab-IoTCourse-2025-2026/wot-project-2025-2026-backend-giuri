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

    def __init__(self, annotation_repo: AnnotationRepository):
        self.repo = annotation_repo

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

        # Carica il modello esistente e ri-addestra
        modello = RandomForestClassifier(
            n_estimators=100,
            class_weight='balanced',
            random_state=42,
            n_jobs=-1
        )
        modello.fit(X, y)

        joblib.dump(modello, ECG_MODEL_PATH)
        print(f"Modello ri-addestrato con {len(X)} campioni validati.")
        return True