import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Default to local SQLite database so backend works out-of-the-box on Windows without Docker
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "parking.db")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
