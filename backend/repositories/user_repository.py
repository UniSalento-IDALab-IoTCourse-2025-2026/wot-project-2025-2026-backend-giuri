from sqlalchemy.orm import Session
from models.user import Medico, Paziente
import secrets
import string


def genera_codice_accesso(lunghezza: int = 8) -> str:
    """
    Genera un codice univoco alfanumerico maiuscolo
    per l'accesso del paziente all'app.
    Es: "A3KX9BPQ"
    """
    caratteri = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(caratteri) for _ in range(lunghezza))


class UserRepository:
    """
    Gestisce tutte le operazioni CRUD su medici e pazienti su MySQL.
    """

    def __init__(self, session: Session):
        self.session = session

    # --------------------------------------------------------
    # MEDICO
    # --------------------------------------------------------

    def save_medico(self, medico: Medico) -> Medico:
        self.session.add(medico)
        self.session.commit()
        self.session.refresh(medico)
        return medico

    def find_medico_by_email(self, email: str) -> Medico | None:
        return self.session.query(Medico).filter(
            Medico.email == email
        ).first()

    def find_medico_by_id(self, medico_id: int) -> Medico | None:
        return self.session.query(Medico).filter(
            Medico.id == medico_id
        ).first()

    # --------------------------------------------------------
    # PAZIENTE
    # --------------------------------------------------------

    def save_paziente(
        self,
        nome: str,
        cognome: str,
        medico_id: int
    ) -> Paziente:
        """
        Crea un nuovo paziente con codice di accesso univoco.
        """
        # Genera un codice univoco non già presente nel DB
        while True:
            codice = genera_codice_accesso()
            esistente = self.find_paziente_by_codice(codice)
            if not esistente:
                break

        paziente = Paziente(
            nome=nome,
            cognome=cognome,
            codice_accesso=codice,
            medico_id=medico_id
        )
        self.session.add(paziente)
        self.session.commit()
        self.session.refresh(paziente)
        return paziente

    def find_paziente_by_codice(self, codice: str) -> Paziente | None:
        return self.session.query(Paziente).filter(
            Paziente.codice_accesso == codice
        ).first()

    def find_paziente_by_id(self, paziente_id: int) -> Paziente | None:
        return self.session.query(Paziente).filter(
            Paziente.id == paziente_id
        ).first()

    def find_pazienti_by_medico(self, medico_id: int) -> list[Paziente]:
        return self.session.query(Paziente).filter(
            Paziente.medico_id == medico_id
        ).all()