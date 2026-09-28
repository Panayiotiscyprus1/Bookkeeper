"""Run with:  python -m pytest -q   (from the bookkeeper folder)"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app          # noqa: E402
from models import db                # noqa: E402
from seed import seed                # noqa: E402


@pytest.fixture
def app():
    app = create_app("sqlite://")
    app.config["TESTING"] = True
    with app.app_context():
        seed("fresh")
        yield app
        db.session.remove()


@pytest.fixture
def turnin_app():
    app = create_app("sqlite://")
    app.config["TESTING"] = True
    with app.app_context():
        seed("turnin")
        yield app
        db.session.remove()
