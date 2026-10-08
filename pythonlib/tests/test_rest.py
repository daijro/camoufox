"""
Tests for camoufox.rest, the REST API around a shared browser.

The browser is a fake, so these exercise the HTTP layer, input validation and
the cleanup paths without downloading or launching Camoufox.

Run with:
    cd pythonlib && python -m pytest tests/test_rest.py -v
"""

import asyncio
import base64
import json
import time
import urllib.error
import urllib.request

import pytest

from camoufox import rest

PUBLIC_URL = "http://93.184.215.14/"


class FakeRequest:
    def __init__(self, url, redirected_from=None):
        self.url = url
        self.redirected_from = redirected_from


class FakeRoute:
    def __init__(self, url):
        self.request = FakeRequest(url)
        self.outcome = None

    async def abort(self, error_code):
        self.outcome = error_code

    async def continue_(self):
        self.outcome = "continued"


class FakeElement:
    def __init__(self, selector, state):
        self.selector = selector
        self.state = state

    async def evaluate(self, expression):
        assert expression == "e => e.outerHTML"
        return "<div>element</div>"

    async def screenshot(self):
        return b"\x89PNG element"


class FakePage:
    def __init__(self, context):
        self.context = context
        self.url = "about:blank"
        self.default_timeout = 30000
        self.wait_until = None
        self.element = None
        self.full_page = None

    def set_default_timeout(self, timeout):
        self.default_timeout = timeout

    async def goto(self, url, wait_until):
        self.wait_until = wait_until
        await self.context.browser.on_goto(self.context, url)
        self.url = url

    async def wait_for_selector(self, selector, state):
        self.element = FakeElement(selector, state)
        return self.element

    async def title(self):
        return "Example"

    async def content(self):
        return "<html>example</html>"

    async def screenshot(self, full_page):
        self.full_page = full_page
        return b"\x89PNG"


class FakeContext:
    def __init__(self, browser):
        self.browser = browser
        self.closed = False
        self.route_handler = None
        self.listeners = {}

    async def route(self, _pattern, handler):
        self.route_handler = handler

    def on(self, event, listener):
        self.listeners[event] = listener

    async def new_page(self):
        self.page = FakePage(self)
        return self.page

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, on_goto=None):
        self.contexts = []
        self.on_goto = on_goto or self._noop

    @staticmethod
    async def _noop(_context, _url):
        pass

    async def new_context(self):
        context = FakeContext(self)
        self.contexts.append(context)
        return context


class FakeLauncher:
    def __init__(self, browser, fail=False):
        self.browser = browser
        self.fail = fail
        self.closed = False

    async def __aenter__(self):
        if self.fail:
            raise RuntimeError("launch failed")
        return self.browser

    async def __aexit__(self, *_exc):
        self.closed = True


def request(service, method, path, body=None, token=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(service.url + path, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def wait_finished(service, job_id, token=None):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        _, job = request(service, "GET", f"/jobs/{job_id}", token=token)
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish")


def make_service(browser=None, **options):
    launcher = FakeLauncher(browser or FakeBrowser())
    options.setdefault("port", 0)
    return rest.RestService(lambda: launcher, **options), launcher


def test_content_job_returns_the_page_and_closes_its_context():
    service, launcher = make_service()
    with service:
        status, job = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"})
        assert status == 202
        assert job["status"] in ("queued", "running")
        assert wait_finished(service, job["id"])["status"] == "succeeded"
        status, result = request(service, "GET", f"/jobs/{job['id']}/result")
    assert status == 200
    assert result == {"url": PUBLIC_URL, "title": "Example", "html": "<html>example</html>"}
    assert [context.closed for context in launcher.browser.contexts] == [True]
    assert launcher.closed


def test_screenshot_job_returns_base64_png():
    service, _ = make_service()
    with service:
        _, job = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "screenshot"})
        wait_finished(service, job["id"])
        _, result = request(service, "GET", f"/jobs/{job['id']}/result")
    assert base64.b64decode(result["screenshot"]) == b"\x89PNG"


@pytest.mark.parametrize(
    "body, raw",
    [
        ({"url": PUBLIC_URL, "operation": "evaluate"}, None),
        ({"url": "file:///etc/passwd", "operation": "content"}, None),
        ({"url": "http://127.0.0.1:8080/", "operation": "content"}, None),
        ({"url": "http://[::ffff:10.0.0.1]/", "operation": "content"}, None),
        ({"url": "http://169.254.169.254/latest/meta-data/", "operation": "content"}, None),
        ({"url": PUBLIC_URL, "operation": "content", "script": "1"}, None),
        ({"operation": "content"}, None),
        ({"url": PUBLIC_URL, "operation": "content", "wait_until": "never"}, None),
        ({"url": PUBLIC_URL, "operation": "content", "timeout": 0}, None),
        ({"url": PUBLIC_URL, "operation": "content", "timeout": 31}, None),
        ({"url": PUBLIC_URL, "operation": "content", "timeout": True}, None),
        ({"url": PUBLIC_URL, "operation": "content", "selector": ""}, None),
        ({"url": PUBLIC_URL, "operation": "content", "full_page": True}, None),
        ({"url": PUBLIC_URL, "operation": "screenshot", "full_page": "yes"}, None),
        ({"url": PUBLIC_URL, "operation": "screenshot", "full_page": True, "selector": "h1"}, None),
        ({"url": "http://" + "a" * rest.MAX_URL_LENGTH, "operation": "content"}, None),
        (None, b"not json"),
        (None, b"[]"),
    ],
)
def test_invalid_or_unsafe_jobs_are_rejected(body, raw):
    service, launcher = make_service()
    with service:
        status, response = request(service, "POST", "/jobs", body, raw=raw)
    assert status == 400, response
    assert launcher.browser.contexts == []


def test_job_parameters_default_and_reach_the_page():
    service, launcher = make_service(timeout=30)
    with service:
        _, job = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"})
        _, other = request(
            service, "POST", "/jobs",
            {"url": PUBLIC_URL, "operation": "screenshot", "wait_until": "domcontentloaded", "full_page": True,
             "timeout": 5},
        )
        wait_finished(service, job["id"])
        wait_finished(service, other["id"])
    assert {key: job[key] for key in ("wait_until", "selector", "full_page", "timeout")} == {
        "wait_until": "load", "selector": None, "full_page": False, "timeout": 30,
    }
    assert other["wait_until"] == "domcontentloaded" and other["timeout"] == 5
    pages = [context.page for context in launcher.browser.contexts]
    assert [(page.wait_until, page.full_page) for page in pages] == [("load", None), ("domcontentloaded", True)]
    # Playwright's own 30s default would cut a longer job short.
    assert [page.default_timeout for page in pages] == [0, 0]


@pytest.mark.parametrize(
    "operation, state, field, expected",
    [
        ("content", "attached", "html", "<div>element</div>"),
        ("screenshot", "visible", "screenshot", base64.b64encode(b"\x89PNG element").decode()),
    ],
)
def test_a_selector_waits_for_and_returns_only_that_element(operation, state, field, expected):
    service, launcher = make_service()
    with service:
        _, job = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": operation, "selector": "#main"})
        wait_finished(service, job["id"])
        _, result = request(service, "GET", f"/jobs/{job['id']}/result")
    assert result[field] == expected
    element = launcher.browser.contexts[0].page.element
    assert (element.selector, element.state) == ("#main", state)


def test_a_job_timeout_shorter_than_the_service_limit_applies():
    async def hang(_context, _url):
        await asyncio.sleep(60)

    service, launcher = make_service(FakeBrowser(on_goto=hang), timeout=60)
    with service:
        _, job = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content", "timeout": 0.2})
        finished = wait_finished(service, job["id"])
    assert finished["error"] == "timed out after 0.2s (wait_until load)"
    assert launcher.browser.contexts[0].closed


def test_private_networks_can_be_allowed_explicitly():
    service, _ = make_service(allow_private_networks=True)
    with service:
        status, job = request(service, "POST", "/jobs", {"url": "http://127.0.0.1/", "operation": "content"})
        assert status == 202
        assert wait_finished(service, job["id"])["status"] == "succeeded"


def test_oversized_body_is_rejected():
    service, _ = make_service()
    with service:
        status, _ = request(service, "POST", "/jobs", raw=b" " * (rest.MAX_BODY_BYTES + 1))
    assert status == 413


def test_a_slow_job_times_out_and_its_context_is_closed():
    async def hang(_context, _url):
        await asyncio.sleep(60)

    service, launcher = make_service(FakeBrowser(on_goto=hang), timeout=0.2)
    with service:
        _, job = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"})
        finished = wait_finished(service, job["id"])
        status, response = request(service, "GET", f"/jobs/{job['id']}/result")
    assert finished["status"] == "failed"
    assert "timed out" in finished["error"]
    assert status == 409 and "timed out" in response["error"]
    assert launcher.browser.contexts[0].closed


def test_a_failing_job_reports_the_error_and_its_context_is_closed():
    async def fail(_context, _url):
        raise RuntimeError("net::ERR_NAME_NOT_RESOLVED")

    service, launcher = make_service(FakeBrowser(on_goto=fail))
    with service:
        _, job = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"})
        finished = wait_finished(service, job["id"])
    assert finished["error"] == "RuntimeError: net::ERR_NAME_NOT_RESOLVED"
    assert launcher.browser.contexts[0].closed


def test_a_redirect_to_a_private_address_fails_the_job():
    async def redirect(context, url):
        context.listeners["request"](FakeRequest("http://10.0.0.1/admin", redirected_from=FakeRequest(url)))

    service, launcher = make_service(FakeBrowser(on_goto=redirect))
    with service:
        _, job = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"})
        finished = wait_finished(service, job["id"])
        status, _ = request(service, "GET", f"/jobs/{job['id']}/result")
    assert finished["status"] == "failed"
    assert "10.0.0.1" in finished["error"]
    assert status == 409
    assert launcher.browser.contexts[0].closed


def test_subresources_to_private_addresses_are_aborted():
    routes = {}

    async def load_subresources(context, _url):
        for url in ("http://127.0.0.1/secret", PUBLIC_URL + "style.css"):
            routes[url] = FakeRoute(url)
            await context.route_handler(routes[url])

    service, _ = make_service(FakeBrowser(on_goto=load_subresources))
    with service:
        _, job = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"})
        wait_finished(service, job["id"])
    assert routes["http://127.0.0.1/secret"].outcome == "blockedbyclient"
    assert routes[PUBLIC_URL + "style.css"].outcome == "continued"


def test_unknown_jobs_and_paths_are_404():
    service, _ = make_service()
    with service:
        assert request(service, "GET", "/jobs/nope")[0] == 404
        assert request(service, "GET", "/jobs/nope/result")[0] == 404
        assert request(service, "GET", "/jobs")[0] == 404
        assert request(service, "POST", "/other", {})[0] == 404


def test_a_full_job_store_rejects_new_jobs_until_one_finishes():
    release = asyncio.Event()

    async def block(_context, _url):
        await release.wait()

    service, _ = make_service(FakeBrowser(on_goto=block), max_jobs=1)
    with service:
        _, first = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"})
        status, _ = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"})
        assert status == 503
        service.call(_set(release))
        wait_finished(service, first["id"])
        status, second = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"})
        assert status == 202
        # The finished job was evicted to make room.
        assert request(service, "GET", f"/jobs/{first['id']}")[0] == 404


async def _set(event):
    event.set()


def test_shutdown_cancels_running_jobs_and_closes_everything():
    async def hang(_context, _url):
        await asyncio.sleep(60)

    service, launcher = make_service(FakeBrowser(on_goto=hang), concurrency=1, timeout=60)
    with service:
        ids = [
            request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"})[1]["id"]
            for _ in range(2)
        ]
        jobs = service.jobs
    assert [jobs._jobs[job_id].error for job_id in ids] == ["cancelled: the service is shutting down"] * 2
    assert [context.closed for context in launcher.browser.contexts] == [True]
    assert launcher.closed


def test_a_launch_failure_is_raised_and_nothing_is_left_listening():
    launcher = FakeLauncher(FakeBrowser(), fail=True)
    service = rest.RestService(lambda: launcher, port=0)
    with pytest.raises(RuntimeError, match="launch failed"):
        service.__enter__()
    with pytest.raises(OSError):
        service._httpd.socket.getsockname()


def test_token_is_required_when_configured():
    service, _ = make_service(token="s3cret")
    with service:
        assert request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"})[0] == 401
        assert request(service, "GET", "/jobs/x", token="wrong")[0] == 401
        status, _ = request(service, "POST", "/jobs", {"url": PUBLIC_URL, "operation": "content"}, token="s3cret")
        assert status == 202


def test_binding_beyond_loopback_requires_a_token():
    with pytest.raises(ValueError, match=rest.TOKEN_ENV_VAR):
        rest.RestService(lambda: FakeLauncher(FakeBrowser()), host="0.0.0.0")
    rest.RestService(lambda: FakeLauncher(FakeBrowser()), host="0.0.0.0", token="s3cret")


def test_the_web_page_loads_without_a_token_under_a_strict_policy():
    service, _ = make_service(token="s3cret")
    with service:
        with urllib.request.urlopen(service.url + "/", timeout=10) as response:
            page = response.read()
            headers = response.headers
    assert page == rest.PAGE
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "connect-src 'self'" in headers["Content-Security-Policy"]


def test_the_api_description_and_its_docs_load_without_a_token():
    service, _ = make_service(token="s3cret", timeout=45)
    with service:
        with urllib.request.urlopen(service.url + "/openapi.json", timeout=10) as response:
            spec = json.loads(response.read())
        with urllib.request.urlopen(service.url + "/docs", timeout=10) as response:
            docs = response.read()
            policy = response.headers["Content-Security-Policy"]
    body = spec["paths"]["/jobs"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert body == rest.job_schema(45)
    assert body["properties"]["timeout"]["maximum"] == 45
    assert spec["security"] == [{"token": []}]
    assert docs == rest.DOCS_PAGE and b"/openapi.json" in docs
    assert "default-src 'none'" in policy and "connect-src 'self'" in policy
