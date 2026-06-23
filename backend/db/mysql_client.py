from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import os
from dotenv import load_dotenv

load_dotenv()

# URL di connessione costruita dalle variabili di ambiente
MYSQL_URL = (
    f"mysql+mysqlconnector://"
    f"{os.getenv('MYSQL_USER')}:{os.getenv('MYSQL_PASSWORD')}"
    f"@{os.getenv('MYSQL_HOST')}:{os.getenv('MYSQL_PORT')}"
    f"/{os.getenv('MYSQL_DATABASE')}"
)

# Engine SQLAlchemy
engine = create_engine(MYSQL_URL, echo=False)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base per i modelli ORM
class Base(DeclarativeBase):
    pass


def get_session():
    """
    Dependency injection per FastAPI.
    Apre una sessione e la chiude dopo ogni richiesta.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db():
    """
    Crea tutte le tabelle definite nei modelli ORM
    se non esistono già.
    """
    Base.metadata.create_all(bind=engine)