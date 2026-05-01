"""
Verify public context helpers forward fingerprint_seed to fingerprint generation.

Run directly:
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib python3 tests/patches/context-api-seed.py

Or with pytest:
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib python3 -m pytest --confcutdir=tests/patches tests/patches/context-api-seed.py
"""

import asyncio

from camoufox import async_api, sync_api


class SyncContext:
    def __init__(self):
        self.init_scripts = []

    def add_init_script(self, script):
        self.init_scripts.append(script)


class SyncBrowser:
    def __init__(self):
        self.context_options = None
        self.context = SyncContext()

    def new_context(self, **options):
        self.context_options = options
        return self.context


class AsyncContext:
    def __init__(self):
        self.init_scripts = []

    async def add_init_script(self, script):
        self.init_scripts.append(script)


class AsyncBrowser:
    def __init__(self):
        self.context_options = None
        self.context = AsyncContext()

    async def new_context(self, **options):
        self.context_options = options
        return self.context


def _fingerprint_result(**kwargs):
    return {
        "context_options": {"user_agent": "generated-agent"},
        "init_script": "generated-init-script",
        "config": {},
        "preset": {},
    }


def test_sync_new_context_forwards_fingerprint_seed():
    calls = []
    original = sync_api.generate_context_fingerprint

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return _fingerprint_result(**kwargs)

    sync_api.generate_context_fingerprint = fake_generate
    try:
        browser = SyncBrowser()
        context = sync_api.NewContext(
            browser,
            fingerprint_seed="profile-a",
            user_agent="caller-agent",
        )
    finally:
        sync_api.generate_context_fingerprint = original

    assert calls[0]["fingerprint_seed"] == "profile-a"
    assert "fingerprint_seed" not in browser.context_options
    assert browser.context_options["user_agent"] == "caller-agent"
    assert context.init_scripts == ["generated-init-script"]


async def _test_async_new_context_forwards_fingerprint_seed():
    calls = []
    original = async_api.generate_context_fingerprint

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return _fingerprint_result(**kwargs)

    async_api.generate_context_fingerprint = fake_generate
    try:
        browser = AsyncBrowser()
        context = await async_api.AsyncNewContext(
            browser,
            fingerprint_seed="profile-a",
            user_agent="caller-agent",
        )
    finally:
        async_api.generate_context_fingerprint = original

    assert calls[0]["fingerprint_seed"] == "profile-a"
    assert "fingerprint_seed" not in browser.context_options
    assert browser.context_options["user_agent"] == "caller-agent"
    assert context.init_scripts == ["generated-init-script"]


def test_async_new_context_forwards_fingerprint_seed():
    asyncio.run(_test_async_new_context_forwards_fingerprint_seed())


def main():
    test_sync_new_context_forwards_fingerprint_seed()
    test_async_new_context_forwards_fingerprint_seed()
    print("context API seed checks passed")


if __name__ == "__main__":
    main()
