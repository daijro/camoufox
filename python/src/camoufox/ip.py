import ipaddress
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Optional, Tuple
from urllib.parse import quote

import requests

from .exceptions import InvalidIP, InvalidProxy

"""
Helpers to find the user's public IP address for geolocation.
"""


@dataclass
class Proxy:
    """
    Stores proxy information.
    """

    server: str
    username: Optional[str] = None
    password: Optional[str] = None
    bypass: Optional[str] = None

    @staticmethod
    def parse_server(server: str) -> Tuple[str, str, Optional[str]]:
        """
        Parses the proxy server string.
        """
        proxy_match = re.match(r'^(?:(?P<schema>\w+)://)?(?P<url>.*?)(?:\:(?P<port>\d+))?$', server)
        if not proxy_match:
            raise InvalidProxy(f"Invalid proxy server: {server}")
        return proxy_match['schema'], proxy_match['url'], proxy_match['port']

    def as_string(self) -> str:
        schema, url, port = self.parse_server(self.server)
        if not schema:
            schema = 'http'
        result = f"{schema}://"
        # Percent-encode the credentials: a raw `#`, `/`, `?` or `@` breaks the
        # URL, and a raw `%XX` is decoded into a different password.
        if self.username:
            result += quote(self.username, safe='')
            if self.password:
                result += f":{quote(self.password, safe='')}"
            result += "@"

        result += url
        if port:
            result += f":{port}"
        return result

    @staticmethod
    def as_requests_proxy(proxy_string: str) -> Dict[str, str]:
        """
        Converts the proxy to a requests proxy dictionary.
        """
        return {
            'http': proxy_string,
            'https': proxy_string,
        }


@lru_cache(128, typed=True)
def valid_ipv4(ip: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(ip), ipaddress.IPv4Address)
    except ValueError:
        return False


@lru_cache(128, typed=True)
def valid_ipv6(ip: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(ip), ipaddress.IPv6Address)
    except ValueError:
        return False


def validate_ip(ip: str) -> None:
    if not valid_ipv4(ip) and not valid_ipv6(ip):
        raise InvalidIP(f"Invalid IP address: {ip}")


# Probing the exit IP through a proxy adds a hop and a TLS handshake behind it; 5 s
# is not enough for a proxy that routes the long way round, and every URL timing out
# fails the whole launch. Direct probes keep 5 s.
DIRECT_IP_TIMEOUT = 5
PROXIED_IP_TIMEOUT = 15


def proxy_exit_geo(proxy: str) -> Tuple[str, str]:
    """
    The exit IP of `proxy` and that IP's timezone, looked up through the proxy.
    Raises InvalidIP when the lookup fails: a context that silently kept the
    host's WebRTC IP and timezone behind a proxy would be a leak.
    """
    try:
        resp = requests.get(
            "http://ip-api.com/json?fields=status,message,query,timezone",
            proxies=Proxy.as_requests_proxy(proxy),
            timeout=PROXIED_IP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exception:
        raise InvalidIP(f"{PROXY_LOOKUP_FAILED}: {exception}") from exception
    if data.get("status") != "success" or not data.get("timezone"):
        raise InvalidIP(f"{PROXY_LOOKUP_FAILED}: {data.get('message') or data}")
    validate_ip(data["query"])
    return data["query"], data["timezone"]


PROXY_LOOKUP_FAILED = (
    "Could not look up the proxy's exit IP and timezone. Pass webrtc_ip and "
    "timezone_id explicitly to skip the lookup"
)


@lru_cache(maxsize=None)
def public_ipv6() -> Optional[str]:
    """
    This host's public IPv6 address, or None when it has none it can reach the
    internet from. The hosts have AAAA records only, so an answer proves the route.
    """
    for url in ("https://api6.ipify.org", "https://v6.ident.me"):
        try:
            resp = requests.get(url, timeout=DIRECT_IP_TIMEOUT, verify=True)
            resp.raise_for_status()
        except requests.RequestException:
            continue
        ip = resp.text.strip()
        if valid_ipv6(ip):
            return ip
    return None


@lru_cache(maxsize=None)
def public_ip(proxy: Optional[str] = None) -> str:
    """
    Sends a request to a public IP api
    """
    URLS = [
        # Prefers IPv4
        "https://api.ipify.org",
        "https://checkip.amazonaws.com",
        "https://ipinfo.io/ip",
        # IPv4 & IPv6
        "https://icanhazip.com",
        "https://ifconfig.co/ip",
        "https://ipecho.net/plain",
    ]

    end_exception = None
    for url in URLS:
        try:
            resp = requests.get(
                url,
                proxies=Proxy.as_requests_proxy(proxy) if proxy else None,
                timeout=PROXIED_IP_TIMEOUT if proxy else DIRECT_IP_TIMEOUT,
                verify=True,
            )
            resp.raise_for_status()
            ip = resp.text.strip()
            validate_ip(ip)
            return ip
        except (requests.exceptions.ProxyError, requests.RequestException, InvalidIP) as exception:
            end_exception = exception
    raise InvalidIP(f"Failed to get IP address: {end_exception}")
