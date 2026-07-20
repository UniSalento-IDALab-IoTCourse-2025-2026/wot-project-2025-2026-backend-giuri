# backend/services/ecg_buffer_manager.py
import time
from collections import deque
from threading import Lock


class ECGBufferManager:
    """
    Mantiene, per ciascun paziente, un buffer scorrevole dei campioni ECG
    raw ricevuti via MQTT. Serve per costruire — quando viene rilevata
    un'anomalia — un'istantanea estesa del segnale che include sia i
    secondi PRECEDENTI l'anomalia (già presenti nel buffer) sia quelli
    SUCCESSIVI (che arrivano nei messaggi seguenti).

    Gli indici sono assoluti (basati sul conteggio totale di campioni
    ricevuti per quel paziente, non sulla posizione corrente nel deque):
    così l'estrazione resta corretta anche se il deque ha già scartato
    i campioni più vecchi per via del maxlen.
    """

    SAMPLE_RATE = 250  # Hz, coerente con simulate_stream.py / annotation_service.py

    def __init__(
        self,
        pre_seconds: float = 15.0,
        post_seconds: float = 15.0,
        margine_seconds: float = 5.0,
        attesa_massima_secondi: float = 40.0
    ):
        self.pre_samples = int(pre_seconds * self.SAMPLE_RATE)
        self.post_samples = int(post_seconds * self.SAMPLE_RATE)
        self.attesa_massima_secondi = attesa_massima_secondi

        # Margine extra per assorbire jitter nella cadenza dei messaggi
        self._maxlen = self.pre_samples + self.post_samples + int(margine_seconds * self.SAMPLE_RATE)

        self._buffers: dict[str, deque] = {}
        self._totali: dict[str, int] = {}
        self._lock = Lock()

    def _buffer(self, paziente_id: str) -> deque:
        if paziente_id not in self._buffers:
            self._buffers[paziente_id] = deque(maxlen=self._maxlen)
            self._totali[paziente_id] = 0
        return self._buffers[paziente_id]

    def aggiungi_campioni(self, paziente_id: str, campioni: list) -> int:
        """
        Accoda i nuovi campioni ECG raw al buffer del paziente.
        Restituisce il conteggio totale assoluto dopo l'inserimento
        (corrisponde all'indice dell'ultimo campione appena ricevuto + 1).
        """
        if not campioni:
            return self._totali.get(paziente_id, 0)

        with self._lock:
            buf = self._buffer(paziente_id)
            buf.extend(campioni)
            self._totali[paziente_id] += len(campioni)
            return self._totali[paziente_id]

    def posizione_attuale(self, paziente_id: str) -> int:
        """Indice assoluto subito dopo l'ultimo campione ricevuto finora."""
        with self._lock:
            return self._totali.get(paziente_id, 0)

    def pronta(self, paziente_id: str, indice_anomalia: int, marcata_at: float) -> bool:
        """
        True se sono già arrivati abbastanza campioni successivi
        all'anomalia per estrarre la finestra completa, oppure se è
        scaduto il tempo massimo di attesa (in tal caso si estrae
        comunque quel che è disponibile, anche se incompleto).
        """
        totale = self.posizione_attuale(paziente_id)
        if totale - indice_anomalia >= self.post_samples:
            return True
        return (time.time() - marcata_at) >= self.attesa_massima_secondi

    def estrai_finestra(self, paziente_id: str, indice_anomalia: int) -> tuple[list, int]:
        """
        Estrae dal buffer la porzione di segnale intorno all'anomalia
        (pre_samples prima, post_samples dopo, quando disponibile).
        Restituisce (campioni_finestra, indice_anomalia_relativo_alla_finestra).
        """
        with self._lock:
            buf = list(self._buffer(paziente_id))
            totale = self._totali.get(paziente_id, 0)

        # Indice assoluto del primo campione ancora presente nel deque
        inizio_buffer_abs = totale - len(buf)

        inizio_assoluto = max(inizio_buffer_abs, indice_anomalia - self.pre_samples)
        fine_assoluto = min(totale, indice_anomalia + self.post_samples)

        inizio_relativo = inizio_assoluto - inizio_buffer_abs
        fine_relativo = fine_assoluto - inizio_buffer_abs

        finestra = buf[inizio_relativo:fine_relativo]
        indice_relativo = indice_anomalia - inizio_assoluto

        return finestra, max(0, indice_relativo)