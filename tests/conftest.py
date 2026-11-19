import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.config import Settings
from app.db import Base, get_db
from app.keitaro import KeitaroClient, get_keitaro
from app.main import app
from app.services import offers as offers_svc
from tools.fake_keitaro import FakeKeitaro, create_app

API_KEY = "test-key"


@pytest.fixture
def fake():
    return FakeKeitaro(api_key=API_KEY)


@pytest.fixture
def kt(fake):
    http = TestClient(create_app(fake=fake))
    settings = Settings(
        _env_file=None,
        keitaro_url="http://testserver",
        keitaro_api_key=API_KEY,
        database_url="sqlite://",
        keitaro_default_domain_id=1,
        keitaro_default_group_id=1,
        keitaro_default_traffic_source_id=1,
    )
    offers_svc.reset_cache()
    return KeitaroClient(settings, http=http)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session, kt):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_keitaro] = lambda: kt
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def campaign_id(fake: FakeKeitaro, name: str = "campaign 2") -> int:
    return next(c["id"] for c in fake.campaigns.values() if c["name"] == name)


def offers_stream(state: dict) -> dict:
    return next(s for s in state["streams"] if s["has_offers"])


def shares(stream: dict) -> dict[int, int]:
    return {o["offer_id"]: o["share"] for o in stream["offers"]}


def kt_shares(fake: FakeKeitaro, keitaro_stream_id: int) -> dict[int, int]:
    return {o["offer_id"]: o["share"] for o in fake.streams[keitaro_stream_id]["offers"]}
