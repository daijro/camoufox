"""
A small REST API that runs page jobs on one shared Camoufox browser.

Clients submit a job (a URL and an operation), poll its status and fetch its
result. Every job runs in its own browser context, so jobs share no cookies or
storage, and that context is closed whether the job succeeds, fails, times out
or is cancelled by shutdown. Launch options and page scripts are deliberately
not reachable over HTTP.
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
from typing import Any, AsyncContextManager, Callable, Dict, Optional, Tuple
from urllib.parse import urlsplit

from playwright.async_api import Browser, BrowserContext, Request, Route

from .async_api import AsyncCamoufox

OPERATIONS = ('content', 'screenshot')
TOKEN_ENV_VAR = 'CAMOUFOX_REST_TOKEN'
MAX_BODY_BYTES = 16 * 1024
MAX_URL_LENGTH = 2048


class InvalidJob(ValueError):
    """The submitted job is malformed or not allowed."""


class BlockedURL(InvalidJob):
    """The URL is not http(s), or points at a non-public address."""


class JobStoreFull(RuntimeError):
    """Every job slot holds a job that has not finished yet."""


async def check_url(url: str, allow_private_networks: bool) -> None:
    """Raise BlockedURL unless `url` is http(s) and, by default, resolves only to public addresses."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError as error:
        raise BlockedURL(f"{url!r} is not a valid URL: {error}") from error
    if parts.scheme not in ('http', 'https') or not host:
        raise BlockedURL(f"{url!r} is not an http(s) URL")
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


@dataclass
class Job:
    id: str
    url: str
    operation: str
    status: str = 'queued'  # queued -> running -> succeeded | failed
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    task: Optional['asyncio.Task[None]'] = None

    @property
    def finished(self) -> bool:
        return self.status in ('succeeded', 'failed')

    def describe(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'url': self.url,
            'operation': self.operation,
            'status': self.status,
            'error': self.error,
        }


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

    async def submit(self, url: Any, operation: Any) -> Dict[str, Any]:
        if operation not in OPERATIONS:
            raise InvalidJob(f"operation must be one of {', '.join(OPERATIONS)}")
        if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
            raise InvalidJob(f"url must be a string of at most {MAX_URL_LENGTH} characters")
        await check_url(url, self._allow_private_networks)

        if len(self._jobs) >= self._max_jobs:
            oldest_finished = next((job for job in self._jobs.values() if job.finished), None)
            if oldest_finished is None:
                raise JobStoreFull(f"all {self._max_jobs} job slots are in use; retry later")
            del self._jobs[oldest_finished.id]

        job = Job(id=uuid.uuid4().hex, url=url, operation=operation)
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
            job.status, job.error = 'failed', f"timed out after {self._timeout:g}s"
        except Exception as error:
            job.status, job.error = 'failed', f"{type(error).__name__}: {error}"

    async def _execute(self, job: Job) -> Dict[str, Any]:
        # The context is created outside the timeout so a timeout can never
        # orphan a context that was still being created.
        context = await self._browser.new_context()
        try:
            return await asyncio.wait_for(self._operate(context, job), self._timeout)
        finally:
            await context.close()

    async def _operate(self, context: BrowserContext, job: Job) -> Dict[str, Any]:
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
        await page.goto(job.url)
        result: Dict[str, Any] = {'url': page.url, 'title': await page.title()}
        if job.operation == 'content':
            result['html'] = await page.content()
        else:
            result['screenshot'] = base64.b64encode(await page.screenshot()).decode()

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
        if not isinstance(body, dict) or set(body) - {'url', 'operation'}:
            return self._send(400, {'error': 'body must be a JSON object with only "url" and "operation"'})

        service = self.server.service
        assert service.jobs is not None
        try:
            job = service.call(service.jobs.submit(body.get('url'), body.get('operation')))
        except InvalidJob as error:
            return self._send(400, {'error': str(error)})
        except JobStoreFull as error:
            return self._send(503, {'error': str(error)})
        self._send(202, job)

    def do_GET(self) -> None:
        if not self._authorized():
            return
        parts = urlsplit(self.path).path.strip('/').split('/')
        service = self.server.service
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


def serve(
    host: str = '127.0.0.1',
    port: int = 8000,
    *,
    concurrency: int = 2,
    max_jobs: int = 100,
    timeout: float = 30.0,
    allow_private_networks: bool = False,
) -> None:
    """Run the REST API on a headless Camoufox until interrupted or terminated."""
    # SIGTERM (e.g. `docker stop`) unwinds like Ctrl-C, so the browser is closed.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with RestService(
        lambda: AsyncCamoufox(headless=True),
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
