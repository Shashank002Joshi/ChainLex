import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from chainlex.api.app import create_app
from chainlex.config import Settings


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        analyst_token=SecretStr("analyst-test-token"),
        officer_token=SecretStr("officer-test-token"),
        simulator_token=SecretStr("simulator-test-token"),
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client
