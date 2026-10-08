"""
A small REST API that runs page jobs on one shared Camoufox browser.

Clients submit a job (a URL and an operation), poll its status and fetch its
result. Every job runs in its own browser context, so jobs share no cookies or
storage, and that context is closed whether the job succeeds, fails, times out
or is cancelled by shutdown. Launch options and page scripts are deliberately
not reachable over HTTP. `GET /` serves a small web page for the same API,
`GET /openapi.json` describes it and `GET /docs` renders that description.
"""

import asyncio
import base64
import hmac
import ipaddress
import json
import os
import signal
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, AsyncContextManager, Callable, Dict, Optional, Tuple
from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, Request, Route

from .async_api import AsyncCamoufox, AsyncNewContext

OPERATIONS = ('content', 'screenshot')
WAIT_UNTIL = ('commit', 'domcontentloaded', 'load', 'networkidle')
TOKEN_ENV_VAR = 'CAMOUFOX_REST_TOKEN'
MAX_BODY_BYTES = 16 * 1024
MAX_URL_LENGTH = 2048
MAX_SELECTOR_LENGTH = 1024
PROXY_SCHEMES = ('http', 'https', 'socks5')
PAGE = (Path(__file__).parent / 'rest.html').read_bytes()
# The page renders job results, so it may reach only this service and show only inline images.
PAGE_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data:; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
)
# Swagger UI, pinned and checked by Subresource Integrity, so the CDN can serve nothing else.
SWAGGER_UI = 'https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.1'
DOCS_PAGE = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Camoufox REST API</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="{SWAGGER_UI}/swagger-ui.css"
  integrity="sha384-Ov4/wv3j2bmct8cDc5X4ngJZohVPzEmc6uDPH8WeljUxO5vtoykvMEfbu9Vh6RaW" crossorigin="anonymous">
</head>
<body>
<div id="docs"></div>
<script src="{SWAGGER_UI}/swagger-ui-bundle.js"
  integrity="sha384-ZPehFMQommnnuaZ4rpxgkgTT2DKFVp4hZC/7pLit+9Lek9T1YGSo23eHFbvNkXkw" crossorigin="anonymous"></script>
<script>
  // The web page keeps the token in this tab's sessionStorage; carry it into Authorize.
  const ui = SwaggerUIBundle({{
    url: '/openapi.json',
    dom_id: '#docs',
    onComplete: () => sessionStorage.getItem('token') && ui.preauthorizeApiKey('token', sessionStorage.getItem('token')),
  }});
</script>
</body>
</html>
""".encode()
DOCS_CSP = (
    f"default-src 'none'; script-src {SWAGGER_UI}/ 'unsafe-inline'; style-src {SWAGGER_UI}/ 'unsafe-inline'; "
    "img-src data:; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
)


class InvalidJob(ValueError):
    """The submitted job is malformed or not allowed."""


class BlockedURL(InvalidJob):
    """The URL is not http(s), or points at a non-public address."""


class JobStoreFull(RuntimeError):
    """Every job slot holds a job that has not finished yet."""


async def check_url(url: str, allow_private_networks: bool, schemes: Tuple[str, ...] = ('http', 'https')) -> None:
    """Raise BlockedURL unless `url` has one of `schemes` and, by default, resolves only to public addresses."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError as error:
        raise BlockedURL(f"{url!r} is not a valid URL: {error}") from error
    if parts.scheme not in schemes or not host:
        raise BlockedURL(f"{url!r} is not a {'/'.join(schemes)} URL")
    if allow_private_networks:
        return
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise BlockedURL(f"cannot resolve {host!r}: {error}") from error
    for *_, sockaddr in infos:
        address = ipaddress.ip_address(sockaddr[0].split('%', 1)[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if not address.is_global:
            raise BlockedURL(f"{host!r} resolves to the non-public address {address}")


def job_schema(max_timeout: float) -> Dict[str, Any]:
    """The JSON schema of a job submission: the one source for validation and the API docs."""
    return {
        'type': 'object',
        'required': ['url', 'operation'],
        'additionalProperties': False,
        'properties': {
            'url': {
                'type': 'string', 'minLength': 1, 'maxLength': MAX_URL_LENGTH,
                'description': 'The http(s) page to open.', 'example': 'https://example.com',
            },
            'operation': {
                'type': 'string', 'enum': list(OPERATIONS),
                'description': '`content` returns the HTML, `screenshot` a base64 PNG.',
            },
            'wait_until': {
                'type': 'string', 'enum': list(WAIT_UNTIL), 'default': 'load',
                'description': (
                    'When navigation counts as done. `domcontentloaded` does not wait for images, '
                    'frames or slow third-party resources; `networkidle` waits until no request '
                    'has run for 500 ms.'
                ),
            },
            'selector': {
                'type': 'string', 'minLength': 1, 'maxLength': MAX_SELECTOR_LENGTH,
                'description': (
                    'A Playwright selector to wait for after navigation. The result is then that '
                    'element alone: its outer HTML, or a screenshot of it, once visible.'
                ),
                'example': '#content',
            },
            'format': {
                'type': 'string', 'enum': ['html', 'text'], 'default': 'html',
                'description': (
                    'What `content` returns: `html`, the markup, or `text`, the text a reader sees '
                    '(its `innerText`), without tags, scripts or styles. Content only.'
                ),
            },
            'full_page': {
                'type': 'boolean', 'default': False,
                'description': 'Screenshot the whole scrollable page, not only the viewport. Screenshots only.',
            },
            'os': {
                'type': 'string', 'enum': ['windows', 'macos', 'linux'],
                'description': 'The OS the job\'s fingerprint claims. Every job draws its own fingerprint; '
                'by default from any OS.',
            },
            'timezone_id': {
                'type': 'string', 'minLength': 1, 'maxLength': 64,
                'description': 'An IANA timezone, e.g. `Europe/Amsterdam`. With a `proxy`, it defaults to the '
                'timezone of the proxy\'s exit IP.',
                'example': 'Europe/Amsterdam',
            },
            'geolocation': {
                'type': 'object', 'required': ['latitude', 'longitude'], 'additionalProperties': False,
                'description': 'The position the Geolocation API reports; permission to read it is granted.',
                'properties': {
                    'latitude': {'type': 'number', 'minimum': -90, 'maximum': 90},
                    'longitude': {'type': 'number', 'minimum': -180, 'maximum': 180},
                },
            },
            'proxy': {
                'type': 'object', 'required': ['server'], 'additionalProperties': False,
                'description': 'A proxy for this job only. The fingerprint\'s WebRTC IP and timezone follow its '
                'exit IP. The password is never shown in the job\'s status.',
                'properties': {
                    'server': {
                        'type': 'string', 'minLength': 1, 'maxLength': MAX_URL_LENGTH,
                        'description': f"{', '.join(PROXY_SCHEMES)} URL", 'example': 'http://proxy.example:3128',
                    },
                    'username': {'type': 'string', 'minLength': 1, 'maxLength': 256},
                    'password': {'type': 'string', 'minLength': 1, 'maxLength': 256},
                },
            },
            'timeout': {
                'type': 'number', 'exclusiveMinimum': 0, 'maximum': max_timeout, 'default': max_timeout,
                'description': 'Seconds the job may run once started, at most the service\'s `--timeout`.',
            },
        },
    }


def _check(name: str, value: Any, rule: Dict[str, Any]) -> None:
    """Validate `value` against the subset of JSON schema that `job_schema` uses."""
    if 'enum' in rule:
        if value not in rule['enum']:
            raise InvalidJob(f"{name} must be one of {', '.join(rule['enum'])}")
    elif rule['type'] == 'object':
        if not isinstance(value, dict):
            raise InvalidJob(f"{name} must be a JSON object")
        prefix = f"{name}." if name else ''
        unknown = sorted(set(value) - set(rule['properties']))
        if unknown:
            raise InvalidJob(f"unknown field(s): {', '.join(prefix + field for field in unknown)}; see /openapi.json")
        for field in rule['required']:
            if field not in value:
                raise InvalidJob(f"{prefix}{field} is required")
        for field, item in value.items():
            _check(prefix + field, item, rule['properties'][field])
    elif rule['type'] == 'string':
        if not isinstance(value, str) or not rule['minLength'] <= len(value) <= rule['maxLength']:
            raise InvalidJob(f"{name} must be a string of {rule['minLength']} to {rule['maxLength']} characters")
    elif rule['type'] == 'boolean':
        if not isinstance(value, bool):
            raise InvalidJob(f"{name} must be true or false")
    else:
        low = rule.get('minimum', rule.get('exclusiveMinimum'))
        if (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or value < low or value > rule['maximum'] or ('exclusiveMinimum' in rule and value == low)
        ):
            bound = 'above' if 'exclusiveMinimum' in rule else 'at least'
            raise InvalidJob(f"{name} must be a number {bound} {low:g} and at most {rule['maximum']:g}")


def parse_job(body: Any, max_timeout: float) -> Dict[str, Any]:
    """Validate a job submission against `job_schema` and fill in its defaults."""
    schema = job_schema(max_timeout)
    if not isinstance(body, dict):
        raise InvalidJob('body must be a JSON object')
    _check('', body, schema)
    if body.get('format') == 'text' and body['operation'] != 'content':
        raise InvalidJob('format applies only to content')
    if body.get('full_page') and (body['operation'] != 'screenshot' or 'selector' in body):
        raise InvalidJob('full_page applies only to a screenshot without a selector')
    defaults = {name: rule['default'] for name, rule in schema['properties'].items() if 'default' in rule}
    return {**defaults, 'selector': None, 'os': None, 'timezone_id': None, 'geolocation': None, 'proxy': None, **body}


def openapi(max_timeout: float, token_required: bool) -> Dict[str, Any]:
    """The OpenAPI description of this service, served at /openapi.json."""
    error = {'type': 'object', 'properties': {'error': {'type': 'string'}}}
    job = {
        'type': 'object',
        'properties': {
            'id': {'type': 'string'},
            'status': {'type': 'string', 'enum': ['queued', 'running', 'succeeded', 'failed']},
            'error': {'type': ['string', 'null']},
            **{name: {'type': rule['type']} for name, rule in job_schema(max_timeout)['properties'].items()},
        },
    }
    result = {
        'type': 'object',
        'properties': {
            'url': {'type': 'string', 'description': 'The final URL, after redirects.'},
            'title': {'type': 'string'},
            'html': {'type': 'string', 'description': '`content` with `format` html.'},
            'text': {'type': 'string', 'description': '`content` with `format` text.'},
            'screenshot': {'type': 'string', 'contentEncoding': 'base64', 'description': '`screenshot` only: a PNG.'},
        },
    }

    def responses(codes: Dict[str, Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
        described: Dict[str, Any] = {
            code: {'description': text, 'content': {'application/json': {'schema': schema}}}
            for code, (text, schema) in codes.items()
        }
        if token_required:
            described['401'] = {'description': 'Missing or wrong bearer token.'}
        return described

    job_id = [{'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}]
    spec: Dict[str, Any] = {
        'openapi': '3.1.0',
        'info': {
            'title': 'Camoufox REST API',
            'version': '1',
            'description': 'Submit a page job, poll its status, then fetch its result.',
        },
        'paths': {
            '/jobs': {'post': {
                'summary': 'Submit a job',
                'requestBody': {'required': True, 'content': {'application/json': {'schema': job_schema(max_timeout)}}},
                'responses': responses({
                    '202': ('The job, queued.', job),
                    '400': ('The body is invalid, or the URL is blocked.', error),
                    '503': ('Every job slot holds an unfinished job; retry later.', error),
                }),
            }},
            '/jobs/{id}': {'get': {
                'summary': "A job's status",
                'parameters': job_id,
                'responses': responses({'200': ('The job.', job), '404': ('No such job.', error)}),
            }},
            '/jobs/{id}/result': {'get': {
                'summary': "A job's result",
                'parameters': job_id,
                'responses': responses({
                    '200': ('The result.', result),
                    '404': ('No such job.', error),
                    '409': ('The job has not succeeded; its status and error.', job),
                }),
            }},
        },
    }
    if token_required:
        spec['components'] = {'securitySchemes': {'token': {'type': 'http', 'scheme': 'bearer'}}}
        spec['security'] = [{'token': []}]
    return spec


@dataclass
class Job:
    id: str
    params: Dict[str, Any]
    status: str = 'queued'  # queued -> running -> succeeded | failed
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    task: Optional['asyncio.Task[None]'] = None

    @property
    def finished(self) -> bool:
        return self.status in ('succeeded', 'failed')

    def describe(self) -> Dict[str, Any]:
        params = dict(self.params)
        if params['proxy']:
            params['proxy'] = {key: value for key, value in params['proxy'].items() if key != 'password'}
        return {'id': self.id, **params, 'status': self.status, 'error': self.error}


class JobRunner:
    """Owns the job records and runs them on `browser`. Lives on one event loop."""

    def __init__(
        self,
        browser: Browser,
        *,
        concurrency: int,
        max_jobs: int,
        timeout: float,
        allow_private_networks: bool,
    ) -> None:
        self._browser = browser
        self._slots = asyncio.Semaphore(concurrency)
        self._max_jobs = max_jobs
        self._timeout = timeout
        self._allow_private_networks = allow_private_networks
        self._jobs: Dict[str, Job] = {}

    async def submit(self, body: Any) -> Dict[str, Any]:
        params = parse_job(body, self._timeout)
        await check_url(params['url'], self._allow_private_networks)
        if params['proxy']:
            await check_url(params['proxy']['server'], self._allow_private_networks, PROXY_SCHEMES)

        if len(self._jobs) >= self._max_jobs:
            oldest_finished = next((job for job in self._jobs.values() if job.finished), None)
            if oldest_finished is None:
                raise JobStoreFull(f"all {self._max_jobs} job slots are in use; retry later")
            del self._jobs[oldest_finished.id]

        job = Job(id=uuid.uuid4().hex, params=params)
        self._jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job))
        return job.describe()

    async def describe(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self._jobs.get(job_id)
        return job.describe() if job else None

    async def result(self, job_id: str) -> Optional[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
        job = self._jobs.get(job_id)
        return (job.describe(), job.result) if job else None

    async def close(self) -> None:
        """Cancel every unfinished job and wait for its context to close."""
        tasks = [job.task for job in self._jobs.values() if job.task and not job.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, job: Job) -> None:
        try:
            async with self._slots:
                job.status = 'running'
                job.result = await self._execute(job)
                job.status = 'succeeded'
        except asyncio.CancelledError:
            job.status, job.error = 'failed', 'cancelled: the service is shutting down'
            raise
        except asyncio.TimeoutError:
            waited = f"wait_until {job.params['wait_until']}"
            if job.params['selector']:
                waited += f" and selector {job.params['selector']!r}"
            job.status, job.error = 'failed', f"timed out after {job.params['timeout']:g}s ({waited})"
        except Exception as error:
            job.status, job.error = 'failed', f"{type(error).__name__}: {error}"

    async def _execute(self, job: Job) -> Dict[str, Any]:
        # The context is created outside the timeout so a timeout can never
        # orphan a context that was still being created.
        options = {name: job.params[name] for name in ('os', 'timezone_id', 'geolocation', 'proxy')}
        context = await AsyncNewContext(self._browser, **{name: value for name, value in options.items() if value})
        try:
            return await asyncio.wait_for(self._operate(context, job.params), job.params['timeout'])
        finally:
            await context.close()

    async def _operate(self, context: BrowserContext, params: Dict[str, Any]) -> Dict[str, Any]:
        redirects = []

        def record_redirect(request: Request) -> None:
            if request.redirected_from:
                redirects.append(request.url)

        if not self._allow_private_networks:
            await context.route('**/*', self._guard)
            # Playwright does not route redirect hops, so check them afterwards
            # and refuse to return anything a redirect fetched.
            context.on('request', record_redirect)

        page = await context.new_page()
        # The job's own timeout bounds every step, rather than Playwright's 30s default.
        page.set_default_timeout(0)
        await page.goto(params['url'], wait_until=params['wait_until'])
        screenshot = params['operation'] == 'screenshot'
        element = None
        if params['selector']:
            element = await page.wait_for_selector(
                params['selector'], state='visible' if screenshot else 'attached'
            )
        result: Dict[str, Any] = {'url': page.url, 'title': await page.title()}
        if params['format'] == 'text':
            result['text'] = await (element.inner_text() if element else page.inner_text('body'))
        elif not screenshot:
            result['html'] = await (element.evaluate('e => e.outerHTML') if element else page.content())
        else:
            image = await (element.screenshot() if element else page.screenshot(full_page=params['full_page']))
            result['screenshot'] = base64.b64encode(image).decode()

        for url in redirects:
            await check_url(url, allow_private_networks=False)
        return result

    async def _guard(self, route: Route) -> None:
        try:
            await check_url(route.request.url, allow_private_networks=False)
        except BlockedURL:
            await route.abort('blockedbyclient')
            return
        await route.continue_()


def _is_loopback(host: str) -> bool:
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class RestService:
    """
    The REST API: an HTTP server plus the event loop that owns the browser.

    Use as a context manager. Entering binds the port and launches the browser;
    exiting stops accepting requests, cancels unfinished jobs and closes the
    browser.
    """

    def __init__(
        self,
        launcher: Callable[[], AsyncContextManager[Browser]],
        *,
        host: str = '127.0.0.1',
        port: int = 8000,
        token: Optional[str] = None,
        concurrency: int = 2,
        max_jobs: int = 100,
        timeout: float = 30.0,
        allow_private_networks: bool = False,
    ) -> None:
        if not token and not _is_loopback(host):
            raise ValueError(
                f"Refusing to serve on {host!r} without a token. Set {TOKEN_ENV_VAR}, "
                "or bind to 127.0.0.1."
            )
        if concurrency < 1 or max_jobs < 1 or timeout <= 0:
            raise ValueError("concurrency, max_jobs and timeout must all be positive")
        self._launcher = launcher
        self._address = (host, port)
        self._token = token
        self.openapi = openapi(timeout, token_required=bool(token))
        self._runner_options = dict(
            concurrency=concurrency,
            max_jobs=max_jobs,
            timeout=timeout,
            allow_private_networks=allow_private_networks,
        )
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._browser_cm: Optional[AsyncContextManager[Browser]] = None
        self._httpd: Optional['_HTTPServer'] = None
        self._http_thread: Optional[threading.Thread] = None
        self.jobs: Optional[JobRunner] = None

    @property
    def url(self) -> str:
        assert self._httpd is not None
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def authorizes(self, authorization: str) -> bool:
        """Whether an Authorization header value grants access."""
        if not self._token:
            return True
        return hmac.compare_digest(authorization.encode(), ('Bearer ' + self._token).encode())

    def call(self, coro: Any) -> Any:
        """Run `coro` on the service's event loop and return its result."""
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def __enter__(self) -> 'RestService':
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._loop_thread.start()
        try:
            self._httpd = _HTTPServer(self._address, self)
            self.jobs = self.call(self._open())
            self._http_thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
            self._http_thread.start()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_exc: Any) -> None:
        try:
            if self._httpd is not None:
                if self._http_thread is not None:
                    self._httpd.shutdown()
                # Waits for in-flight requests, which still need the loop.
                self._httpd.server_close()
            self.call(self._close())
        finally:
            assert self._loop is not None and self._loop_thread is not None
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop_thread.join()
            self._loop.close()

    async def _open(self) -> JobRunner:
        self._browser_cm = self._launcher()
        browser = await self._browser_cm.__aenter__()
        return JobRunner(browser, **self._runner_options)

    async def _close(self) -> None:
        try:
            if self.jobs is not None:
                await self.jobs.close()
        finally:
            if self._browser_cm is not None:
                await self._browser_cm.__aexit__(None, None, None)


class _HTTPServer(ThreadingHTTPServer):
    # Join request threads on close, so none outlives the event loop it calls into.
    daemon_threads = False

    def __init__(self, address: Any, service: RestService) -> None:
        self.service = service
        super().__init__(address, _Handler)


class _Handler(BaseHTTPRequestHandler):
    server: _HTTPServer

    def do_POST(self) -> None:
        if not self._authorized():
            return
        if urlsplit(self.path).path != '/jobs':
            return self._send(404, {'error': 'not found'})
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            return self._send(411, {'error': 'Content-Length is required'})
        if not 0 <= length <= MAX_BODY_BYTES:
            return self._send(413, {'error': f"body must be at most {MAX_BODY_BYTES} bytes"})
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            return self._send(400, {'error': 'body is not valid JSON'})

        service = self.server.service
        assert service.jobs is not None
        try:
            job = service.call(service.jobs.submit(body))
        except InvalidJob as error:
            return self._send(400, {'error': str(error)})
        except JobStoreFull as error:
            return self._send(503, {'error': str(error)})
        self._send(202, job)

    def do_GET(self) -> None:
        # These pages hold no data, so they load without a token; the API calls they make send one.
        path = urlsplit(self.path).path
        service = self.server.service
        if path == '/':
            return self._send_page(PAGE, PAGE_CSP)
        if path == '/docs':
            return self._send_page(DOCS_PAGE, DOCS_CSP)
        if path == '/openapi.json':
            return self._send(200, service.openapi)
        if not self._authorized():
            return
        parts = path.strip('/').split('/')
        assert service.jobs is not None
        if len(parts) == 2 and parts[0] == 'jobs':
            job = service.call(service.jobs.describe(parts[1]))
            if job is None:
                return self._send(404, {'error': 'no such job'})
            return self._send(200, job)
        if len(parts) == 3 and parts[0] == 'jobs' and parts[2] == 'result':
            found = service.call(service.jobs.result(parts[1]))
            if found is None:
                return self._send(404, {'error': 'no such job'})
            job, result = found
            if job['status'] != 'succeeded':
                return self._send(409, {**job, 'error': job['error'] or f"job is {job['status']}"})
            return self._send(200, result)
        self._send(404, {'error': 'not found'})

    def _authorized(self) -> bool:
        if self.server.service.authorizes(self.headers.get('Authorization', '')):
            return True
        self._send(401, {'error': 'missing or wrong bearer token'})
        return False

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_page(self, page: bytes, policy: str) -> None:
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(page)))
        self.send_header('Content-Security-Policy', policy)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(page)


def serve(
    host: str = '127.0.0.1',
    port: int = 8000,
    *,
    concurrency: int = 2,
    max_jobs: int = 100,
    timeout: float = 30.0,
    allow_private_networks: bool = False,
    launch_options: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Run the REST API on a headless Camoufox until interrupted or terminated.

    `launch_options` go to AsyncCamoufox, so every SDK launch option can be set
    for the service; clients can never set them.
    """
    # SIGTERM (e.g. `docker stop`) unwinds like Ctrl-C, so the browser is closed.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with RestService(
        lambda: AsyncCamoufox(**{'headless': True, **(launch_options or {})}),
        host=host,
        port=port,
        token=os.environ.get(TOKEN_ENV_VAR) or None,
        concurrency=concurrency,
        max_jobs=max_jobs,
        timeout=timeout,
        allow_private_networks=allow_private_networks,
    ) as service:
        print(f"Camoufox REST API listening on {service.url}", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
