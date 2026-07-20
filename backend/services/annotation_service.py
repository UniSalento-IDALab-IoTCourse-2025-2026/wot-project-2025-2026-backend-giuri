import time
from datetime import datetime, timezone
from typing import Optional
import numpy as np
from repositories.annotation_repository import AnnotationRepository
from classifiers.ecg_classifier import ECGClassifier
from classifiers.postura_classifier import PosturaClassifier
from classifiers.temperatura_classifier import TemperaturaClassifier
from models.annotation import Annotation, TipoAnnotazione, EsitoMedico
from services.ecg_buffer_manager import ECGBufferManager


class AnnotationService:
    """
    Orchestra la classificazione dei dati in arrivo, il salvataggio delle
    annotazioni su MongoDB e — quando disponibile un ECGBufferManager —
    la costruzione asincrona della finestra ECG estesa intorno alle
    anomalie (≥30s, prima e dopo l'evento).
    """

    ECG_SAMPLE_RATE = 250

    def __init__(
        self,
        annotation_repo: AnnotationRepository,
        ecg_classifier: ECGClassifier,
        postura_classifier: PosturaClassifier,
        temperatura_classifier: TemperaturaClassifier,
        ecg_buffer: Optional[ECGBufferManager] = None
    ):
        self.repo = annotation_repo
        self.ecg = ecg_classifier
        self.postura = postura_classifier
        self.temperatura = temperatura_classifier

        # Il buffer è opzionale: serve solo nel processo che elabora il
        # flusso live (mqtt_subscriber.py). Le istanze create al volo da
        # fastapi_server.py per leggere/validare storico non ne hanno bisogno.
        self.ecg_buffer = ecg_buffer

        # paziente_id -> lista di (annotation_id, indice_anomalia, marcata_at)
        # anomalie già salvate ma per cui la finestra estesa non è ancora pronta
        self._estrazioni_in_attesa: dict[str, list] = {}

    def _estrai_rr_da_raw(self, ecg_raw: list) -> list:
        if len(ecg_raw) < 3:
            return []

        signal = np.array(ecg_raw, dtype=float)

        picchi = []
        for i in range(1, len(signal) - 1):
            if signal[i] > signal[i - 1] and signal[i] > signal[i + 1]:
                picchi.append(i)

        if len(picchi) < 2:
            return []

        return [
            (picchi[i + 1] - picchi[i]) / self.ECG_SAMPLE_RATE
            for i in range(len(picchi) - 1)
        ]

    def _normalizza(self, campioni: list) -> list:
        """Normalizzazione lineare in [-1, 1] per rendering SVG coerente."""
        if not campioni:
            return []
        arr = np.array(campioni, dtype=float)
        vmin, vmax = arr.min(), arr.max()
        rng = (vmax - vmin) if (vmax - vmin) > 0 else 1.0
        normalizzato = (2.0 * (arr - vmin) / rng - 1.0)
        return [round(float(v), 4) for v in normalizzato]

    def processa_lettura(self, payload: dict) -> tuple[Annotation, bool]:
        paziente_id = payload.get("paziente_id")

        rr_intervals = payload.get("rr_intervals")
        ecg_raw = payload.get("ecg_raw", [])

        if not rr_intervals:
            rr_intervals = self._estrai_rr_da_raw(ecg_raw)

        ecg_raw_snapshot = None
        if ecg_raw and len(ecg_raw) >= 10:
            ecg_raw_snapshot = self._normalizza(ecg_raw)

        ecg_result = self.ecg.predict({"rr_intervals": rr_intervals})

        # Finestra IMU completa (~1s di campioni a 104Hz), non il singolo
        # ultimo valore: PosturaClassifier.predict_batch() accoda tutti i
        # campioni in un colpo solo al buffer interno DEL PAZIENTE
        # corrente, così le feature statistiche (media, std, SMA...)
        # vengono calcolate su un segnale continuo coerente col training
        # MHEALTH invece che su punti isolati presi uno al secondo (vedi
        # Bug #1), e senza mescolare campioni di pazienti diversi nella
        # stessa finestra dato che l'istanza di PosturaClassifier è
        # condivisa globalmente da mqtt_subscriber.py per tutti i
        # pazienti connessi (vedi Bug #4 — buffer ora keyed per
        # paziente_id dentro PosturaClassifier stesso).
        #
        # Fallback: se il payload non contiene ancora "imu_window" (es.
        # bridge non aggiornato, payload di test legacy), si ricostruisce
        # una finestra di un solo campione dagli scalari piatti acc_x..
        # gyro_z, mantenendo il sistema funzionante anche se con feature
        # meno informative fino all'aggiornamento del mittente.
        imu_window = payload.get("imu_window") or [{
            "acc_x": payload.get("acc_x", 0.0),
            "acc_y": payload.get("acc_y", 0.0),
            "acc_z": payload.get("acc_z", 1.0),
            "gyro_x": payload.get("gyro_x", 0.0),
            "gyro_y": payload.get("gyro_y", 0.0),
            "gyro_z": payload.get("gyro_z", 0.0),
        }]
        postura_result = self.postura.predict_batch(imu_window, paziente_id=paziente_id)
        postura_label = postura_result["label"] \
            if postura_result["label"] != "in_accumulo" else None
        postura_score = postura_result["score"] \
            if postura_label is not None else None

        temp_value = payload.get("temperatura", 0.0)
        temperatura_result = self.temperatura.predict({"temperatura": temp_value})

        annotation = Annotation(
            paziente_id=paziente_id,
            timestamp=datetime.now(timezone.utc),
            ecg_label=ecg_result["label"],
            ecg_score=ecg_result["score"],
            rr_intervals=rr_intervals,
            ecg_raw_snapshot=ecg_raw_snapshot,
            postura_label=postura_label,
            postura_score=postura_score,
            temperatura_label=temperatura_result["label"],
            temperatura_valore=temp_value,
            tipo_annotazione=TipoAnnotazione.AUTOMATICA
        )

        annotation_id = self.repo.save(annotation)
        is_anomalia = ecg_result["label"] == "anomalo"

        # --- Gestione finestra ECG estesa (≥30s, prima e dopo l'anomalia) ---
        if self.ecg_buffer is not None:
            indice_corrente = self.ecg_buffer.aggiungi_campioni(paziente_id, ecg_raw)

            if is_anomalia:
                self._estrazioni_in_attesa.setdefault(paziente_id, []).append(
                    (annotation_id, indice_corrente, time.time())
                )

            self._processa_estrazioni_pendenti(paziente_id)

        return annotation, is_anomalia

    def _processa_estrazioni_pendenti(self, paziente_id: str) -> None:
        """
        Ad ogni messaggio del paziente, controlla se per qualche anomalia
        precedente sono già arrivati abbastanza campioni "dopo" per
        estrarre la finestra completa e aggiornare il documento.
        """
        pendenti = self._estrazioni_in_attesa.get(paziente_id)
        if not pendenti:
            return

        rimaste = []
        for annotation_id, indice_anomalia, marcata_at in pendenti:
            if self.ecg_buffer.pronta(paziente_id, indice_anomalia, marcata_at):
                finestra, indice_relativo = self.ecg_buffer.estrai_finestra(
                    paziente_id, indice_anomalia
                )
                self.repo.update_ecg_window(
                    annotation_id,
                    self._normalizza(finestra),
                    indice_relativo,
                    sample_rate=self.ecg_buffer.SAMPLE_RATE
                )
            else:
                rimaste.append((annotation_id, indice_anomalia, marcata_at))

        if rimaste:
            self._estrazioni_in_attesa[paziente_id] = rimaste
        else:
            self._estrazioni_in_attesa.pop(paziente_id, None)

    def valida_anomalia(self, annotation_id: str, esito: EsitoMedico, note: str = None) -> bool:
        return self.repo.update_esito_medico(annotation_id, esito, note)

    def valida_episodio(
        self,
        annotation_ids: list[str],
        esito: EsitoMedico,
        note: str = None
    ) -> int:
        """
        Applica un solo esito medico a un intero episodio clinico (più
        letture anomale consecutive raggruppate da
        get_episodi_anomalia_non_validati). Restituisce il numero di
        documenti aggiornati.
        """
        return self.repo.update_esito_medico_multiplo(annotation_ids, esito, note)

    def get_anomalie_non_validate(self) -> list[dict]:
        return self.repo.find_anomalie_non_validate()

    def get_episodi_anomalia_non_validati(self) -> list[dict]:
        """
        Restituisce le anomalie non validate raggruppate per episodio
        clinico (letture consecutive dello stesso paziente con gap
        temporale ridotto) invece che come righe singole — pensato per
        la vista medico, dove un episodio di 30 letture consecutive deve
        comparire come una sola riga da validare.
        """
        return self.repo.find_episodi_anomalia_non_validati()

    def get_episodi_per_paziente(self, paziente_id: str) -> list[dict]:
        """
        Restituisce TUTTI gli episodi anomali (validati + in attesa) di
        un singolo paziente, raggruppati esattamente come per la vista
        medico (stessa soglia di gap temporale). Usato dall'app paziente
        per il popup "Anomalie": mostra solo eventi anomali — non lo
        storico completo con le letture normali — e include l'esito del
        medico quando già presente.
        """
        return self.repo.find_episodi_per_paziente(paziente_id)

    def get_storico_paziente(self, paziente_id: str, limit: int = 50) -> list[dict]:
        return self.repo.find_by_patient(paziente_id, limit)