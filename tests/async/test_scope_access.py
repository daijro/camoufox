import json
import os
from typing import Awaitable, Callable
from urllib.parse import quote

from playwright.async_api import Browser, Page
from tests.server import Server


async def new_page_with_config(
    browser_factory: Callable[..., Awaitable[Browser]], config: dict
) -> Page:
    env = dict(os.environ)
    env["CAMOU_CONFIG_1"] = json.dumps(config)
    browser = await browser_factory(env=env)
    return await browser.new_page()


async def test_force_scope_access_reaches_closed_shadow_roots(
    browser_factory: Callable[..., Awaitable[Browser]],
) -> None:
    page = await new_page_with_config(
        browser_factory,
        {"forceScopeAccess": True},
    )
    await page.set_content(
        """
        <div id="host"></div>
        <script>
          const host = document.querySelector('#host');
          const root = host.attachShadow({mode: 'closed'});
          root.innerHTML = '<span id="secret">inside</span>';
          document.documentElement.dataset.pageShadowRootUnlType =
            typeof host.shadowRootUnl;
          document.documentElement.dataset.hostileGetterCalls = '0';
          Object.defineProperty(host, 'shadowRootUnl', {
            get() {
              document.documentElement.dataset.hostileGetterCalls = '1';
              return null;
            }
          });
        </script>
        """
    )

    assert (
        await page.evaluate(
            "document.querySelector('#host').shadowRootUnl.querySelector('#secret').textContent"
        )
        == "inside"
    )
    assert (
        await page.get_attribute("html", "data-page-shadow-root-unl-type")
        == "undefined"
    )
    assert await page.get_attribute("html", "data-hostile-getter-calls") == "0"


async def test_force_scope_access_preserves_evaluation_handles(
    browser_factory: Callable[..., Awaitable[Browser]],
) -> None:
    page = await new_page_with_config(
        browser_factory,
        {"forceScopeAccess": True},
    )
    await page.set_content(
        """
        <main id="target">content</main>
        <script>
          window.pageSecret = 41;
          Element.prototype.pageMarker = 'page-owned';
          document.documentElement.dataset.chromeUtilsType = typeof ChromeUtils;
        </script>
        """
    )

    handle = await page.evaluate_handle("() => ({value: 42})")
    assert await handle.evaluate("object => object.value") == 42
    assert await handle.json_value() == {"value": 42}
    await handle.dispose()

    element = await page.query_selector("#target")
    assert element
    assert await element.get_attribute("id") == "target"

    # The page-scoped automation sandbox stays in its own compartment: page
    # expandos are hidden from automation and the page cannot see the accessor.
    assert await page.evaluate("window.pageSecret") is None
    assert await page.evaluate("document.querySelector('#target').pageMarker") is None
    assert (
        await page.get_attribute("html", "data-chrome-utils-type") == "undefined"
    )


async def test_force_scope_access_remains_page_scoped(
    browser_factory: Callable[..., Awaitable[Browser]],
    server: Server,
) -> None:
    page = await new_page_with_config(browser_factory, {"forceScopeAccess": True})
    await page.goto(server.EMPTY_PAGE)

    privileged_names = [
        "ChromeUtils",
        "Cc",
        "Ci",
        "Cu",
        "Services",
        "InspectorUtils",
        "IOUtils",
        "PathUtils",
        "__camoufoxGetClosedShadowRoot",
    ]
    assert await page.evaluate(
        "names => names.map(name => typeof globalThis[name])", privileged_names
    ) == ["undefined"] * len(privileged_names)
    component_expression = """() => [
      typeof Components.classes,
      typeof Components.interfaces,
      typeof Components.utils,
      typeof Components.manager,
      typeof Components.results,
      typeof Components.ID,
      typeof Components.Exception,
      typeof Components.Constructor,
      typeof Components.isSuccessCode,
    ]"""
    component_types = await page.evaluate(component_expression)
    default_page = await new_page_with_config(browser_factory, {})
    await default_page.goto(server.EMPTY_PAGE)
    assert component_types == await default_page.evaluate(component_expression)
    assert component_types == [
        "undefined",
        "object",
        "undefined",
        "undefined",
        "undefined",
        "undefined",
        "undefined",
        "undefined",
        "undefined",
    ]

    accessor = await page.evaluate(
        """() => {
          const getter = Object.getOwnPropertyDescriptor(
            Element.prototype,
            'shadowRootUnl'
          ).get;
          let constructorScope = 'blocked';
          try {
            constructorScope = getter.constructor(
              'return typeof ChromeUtils'
            )();
          } catch (error) {}
          return [
            typeof getter,
            typeof globalThis.__camoufoxGetClosedShadowRoot,
            constructorScope,
          ];
        }"""
    )
    assert accessor == ["function", "undefined", "undefined"]

    assert (
        await page.evaluate(
            "url => fetch(url).then(response => response.status)", server.EMPTY_PAGE
        )
        == 200
    )
    cross_origin_url = server.CROSS_PROCESS_PREFIX + "/empty.html"
    assert (
        await page.evaluate(
            """url => fetch(url).then(
              response => `allowed:${response.status}`,
              () => 'blocked'
            )""",
            cross_origin_url,
        )
        == "blocked"
    )
    assert (
        await page.evaluate(
            """url => new Promise(resolve => {
              const request = new XMLHttpRequest();
              request.onload = () => resolve(`allowed:${request.status}`);
              request.onerror = () => resolve('blocked');
              request.open('GET', url);
              request.send();
            })""",
            cross_origin_url,
        )
        == "blocked"
    )
    assert (
        await page.evaluate(
            """() => fetch('file:///etc/hosts').then(
              response => `allowed:${response.status}`,
              () => 'blocked'
            )"""
        )
        == "blocked"
    )


async def test_force_scope_access_survives_navigation_and_child_frames(
    browser_factory: Callable[..., Awaitable[Browser]],
) -> None:
    page = await new_page_with_config(browser_factory, {"forceScopeAccess": True})

    for value in ("first", "second"):
        html = f"""
        <div id="host"></div>
        <script>
          const root = document.querySelector('#host').attachShadow({{mode: 'closed'}});
          root.innerHTML = '<span id="secret">{value}</span>';
        </script>
        """
        await page.goto("data:text/html," + quote(html))
        assert (
            await page.evaluate(
                "document.querySelector('#host').shadowRootUnl.querySelector('#secret').textContent"
            )
            == value
        )

    child_html = """
    <div id="host"></div>
    <script>
      const root = document.querySelector('#host').attachShadow({mode: 'closed'});
      root.innerHTML = '<span id="secret">frame</span>';
    </script>
    """
    await page.set_content(f'<iframe src="data:text/html,{quote(child_html)}"></iframe>')
    await page.wait_for_selector("iframe")
    child = page.frames[-1]
    await child.wait_for_selector("#host")
    assert (
        await child.evaluate(
            "document.querySelector('#host').shadowRootUnl.querySelector('#secret').textContent"
        )
        == "frame"
    )


async def test_default_scope_does_not_expose_closed_shadow_roots(
    browser_factory: Callable[..., Awaitable[Browser]],
) -> None:
    page = await new_page_with_config(browser_factory, {})
    await page.set_content(
        """
        <div id="host"></div>
        <script>
          document.querySelector('#host').attachShadow({mode: 'closed'});
        </script>
        """
    )

    assert (
        await page.evaluate(
            "typeof document.querySelector('#host').shadowRootUnl"
        )
        == "undefined"
    )
