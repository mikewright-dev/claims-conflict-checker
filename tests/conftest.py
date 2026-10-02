import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run tests marked @pytest.mark.live (calls the real Gemini API)",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls the real Gemini API; skipped unless --live is given")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="live API test; run with --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
