from pymongo import MongoClient
from pymongo.database import Database
import os
from dotenv import load_dotenv

load_dotenv()

class MongoDBClient:
    """
    Singleton per la connessione a MongoDB.
    Garantisce una sola istanza della connessione
    per tutta la durata dell'applicazione.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = MongoClient(
                os.getenv("MONGO_URI")
            )
            cls._instance._db = cls._instance._client[
                os.getenv("MONGO_DB", "cardiosense")
            ]
        return cls._instance

    @property
    def db(self) -> Database:
        return self._db

    def close(self):
        self._client.close()


def get_db() -> Database:
    """
    Funzione di accesso rapido al database.
    Usata come dependency injection in FastAPI.
    """
    return MongoDBClient().db