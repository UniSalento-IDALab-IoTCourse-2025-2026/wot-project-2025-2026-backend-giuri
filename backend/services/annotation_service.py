from datetime import datetime
import numpy as np
from repositories.annotation_repository import AnnotationRepository
from classifiers.ecg_classifier import ECGClassifier
from classifiers.postura_classifier import PosturaClassifier
from classifiers.temperatura_classifier import TemperaturaClassifier
from models.annotation import Annotation, TipoAnnotazione, EsitoMedico


class AnnotationService:
    """
    Orchestra la classificazione dei dati in arrivo
    e il salvataggio delle annotazioni su MongoDB.
    """

    # Frequenza di campionamento ECG in Hz
    ECG_SAMPLE_RATE = 250

    def __init__(
        self,
        annotation_repo: AnnotationRepository,
        ecg_classifier: ECGClassifier,
        postura_classifier: PosturaClassifier,
        temperatura_classifier: TemperaturaClassifier
    ):
        self.repo = annotation_repo
        self.ecg = ecg_classifier
        self.postura = postura_classifier
        self.temperatura = temperatura_classifier

    def _estrai_rr_da_raw(self, ecg_raw: list) -> list:
        """
        Estrae gli intervalli R-R da una finestra di campioni ECG raw.

        Il metodo rileva i picchi R cercando i massimi locali nel segnale,
        poi calcola la distanza temporale tra picchi consecutivi in secondi.

        Args:
            ecg_raw: lista di campioni ECG raw (interi)

        Returns:
            lista di intervalli R-R in secondi
        """
        if len(ecg_raw) < 3:
            return []

        signal = np.array(ecg_raw, dtype=float)

        # Trova i picchi locali — un campione è un picco se è
        # maggiore del precedente e del successivo
        picchi = []
        for i in range(1, len(signal) - 1):
            if signal[i] > signal[i - 1] and signal[i] > signal[i + 1]:
                picchi.append(i)

        if len(picchi) < 2:
            return []

        # Calcola intervalli R-R in secondi
        # dividendo la distanza in campioni per la frequenza
        rr_intervals = [
            (picchi[i + 1] - picchi[i]) / self.ECG_SAMPLE_RATE
            for i in range(len(picchi) - 1)
        ]

        return rr_intervals

    def processa_lettura(self, payload: dict) -> tuple[Annotation, bool]:
        """
        Riceve il payload MQTT, classifica i tre segnali,
        salva su MongoDB e restituisce l'annotazione e
        un flag che indica se è anomala.

        Args:
            payload: {
                "paziente_id": str,
                "timestamp": str,
                "ecg_raw": [...],
                "acc_x": float,
                "acc_y": float,
                "acc_z": float,
                "temperatura": float
            }

        Returns:
            (annotation, is_anomalia)
        """
        # Estrai intervalli R-R dal segnale ECG raw
        ecg_raw = payload.get("ecg_raw", [])
        rr_intervals = self._estrai_rr_da_raw(ecg_raw)

        # Classificazione ECG
        ecg_result = self.ecg.predict({
            "rr_intervals": rr_intervals
        })

        # Classificazione postura
        postura_result = self.postura.predict({
            "acc_x": payload.get("acc_x", 0.0),
            "acc_y": payload.get("acc_y", 0.0),
            "acc_z": payload.get("acc_z", 0.0)
        })

        # Classificazione temperatura
        temp_value = payload.get("temperatura", 0.0)
        temperatura_result = self.temperatura.predict({
            "temperatura": temp_value
        })

        # Costruisci il documento annotazione
        annotation = Annotation(
            paziente_id=payload.get("paziente_id"),
            timestamp=datetime.utcnow(),
            ecg_label=ecg_result["label"],
            ecg_score=ecg_result["score"],
            postura_label=postura_result["label"],
            postura_score=postura_result["score"],
            temperatura_label=temperatura_result["label"],
            temperatura_valore=temp_value,
            tipo_annotazione=TipoAnnotazione.AUTOMATICA
        )

        # Salva su MongoDB
        self.repo.save(annotation)

        # È anomalia se ECG lo dice
        is_anomalia = ecg_result["label"] == "anomalo"

        return annotation, is_anomalia

    def valida_anomalia(
        self,
        annotation_id: str,
        esito: EsitoMedico,
        note: str = None
    ) -> bool:
        """
        Aggiorna un'annotazione esistente con la validazione del medico.
        """
        return self.repo.update_esito_medico(annotation_id, esito, note)

    def get_anomalie_non_validate(self) -> list[dict]:
        """
        Restituisce le anomalie in attesa di validazione medica.
        """
        return self.repo.find_anomalie_non_validate()

    def get_storico_paziente(
        self,
        paziente_id: str,
        limit: int = 50
    ) -> list[dict]:
        """
        Restituisce lo storico delle annotazioni di un paziente.
        """
        return self.repo.find_by_patient(paziente_id, limit)