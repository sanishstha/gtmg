import os

os.environ["DATABASE_URL"] = "postgresql+psycopg://desk:desk@localhost:5432/desk_test"
os.environ["OPENAI_API_KEY"] = ""

import psycopg
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.orm import Base

TEST_URL = os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
def engine():
    with psycopg.connect("postgresql://desk:desk@localhost:5432/desk", autocommit=True) as connection:
        exists = connection.execute("SELECT 1 FROM pg_database WHERE datname = 'desk_test'").fetchone()
        if exists is None:
            connection.execute("CREATE DATABASE desk_test")
    test_engine = create_engine(TEST_URL)
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    db = factory()
    yield db
    db.close()
    transaction.rollback()
    connection.close()
