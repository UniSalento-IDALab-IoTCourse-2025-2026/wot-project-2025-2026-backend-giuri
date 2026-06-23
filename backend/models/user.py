from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from db.mysql_client import Base


class Medico(Base):
    """
    Tabella dei medici registrati nel sistema.
    """
    __tablename__ = "medico"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(100), nullable=False)
    cognome = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Un medico ha molti pazienti
    pazienti = relationship("Paziente", back_populates="medico")

    def __repr__(self):
        return f"<Medico {self.nome} {self.cognome}>"


class Paziente(Base):
    """
    Tabella dei pazienti registrati nel sistema.
    """
    __tablename__ = "paziente"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(100), nullable=False)
    cognome = Column(String(100), nullable=False)
    codice_accesso = Column(String(20), nullable=False, unique=True)
    medico_id = Column(Integer, ForeignKey("medico.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Ogni paziente appartiene a un medico
    medico = relationship("Medico", back_populates="pazienti")

    def __repr__(self):
        return f"<Paziente {self.nome} {self.cognome}>"