import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--browser-version",
        default=None,
        help="Camoufox browser version specifier, e.g. official/prerelease/146.0.1-beta.25",
    )
    parser.addoption(
        "--headful",
        action="store_true",
        default=False,
        help="Run tests with a visible browser window",
    )


@pytest.fixture(scope="session")
def camoufox_version(request):
    return request.config.getoption("--browser-version")


@pytest.fixture(scope="session")
def headful(request):
    return request.config.getoption("--headful")
