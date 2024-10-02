import xml.etree.ElementTree as ET  # nosec
from dataclasses import dataclass
from random import choice as randchoice
from typing import Any, Dict, List, Optional, Tuple, cast

import numpy as np
from language_tags import tags

from camoufox.pkgman import LOCAL_DATA, rprint, webdl

from .exceptions import NotInstalledGeoIPExtra, UnknownIPLocation, UnknownTerritory
from .ip import validate_ip

try:
    import geoip2.database  # type: ignore
except ImportError:
    ALLOW_GEOIP = False
else:
    ALLOW_GEOIP = True


"""
Data structures for locale and geolocation info
"""


@dataclass
class Locale:
    """
    Stores locale, region, and script information.
    """

    language: str
    region: str
    script: Optional[str] = None

    @property
    def as_string(self) -> str:
        return f"{self.language}-{self.region}"

    def as_config(self) -> Dict[str, str]:
        """
        Converts the locale to a config dictionary.
        """
        data = {
            'locale:region': self.region,
            'locale:language': self.language,
        }
        if self.script:
            data['locale:script'] = self.script
        return data


@dataclass
class Geolocation:
    """
    Stores geolocation information.
    """

    locale: Locale
    longitude: float
    latitude: float
    timezone: str
    accuracy: Optional[float] = None

    def as_config(self) -> Dict[str, Any]:
        """
        Converts the geolocation to a config dictionary.
        """
        data = {
            'geolocation:longitude': self.longitude,
            'geolocation:latitude': self.latitude,
            'timezone': self.timezone,
            **self.locale.as_config(),
        }
        if self.accuracy:
            data['geolocation:accuracy'] = self.accuracy
        return data


"""
Helpers to validate and normalize locales
"""


def verify_locales(locales: List[str]) -> None:
    """
    Verifies that all locales are valid.
    """
    for loc in locales:
        if tags.check(loc):
            continue
        raise ValueError(
            f"Invalid locale: '{loc}'. All locales must be in the format of language[-script][-region]"
        )


def normalize_locale(locale: str) -> Locale:
    """
    Normalizes and validates a locale code.
    """
    locales = locale.split(',')
    verify_locales(locales)
    if len(locales) > 1:
        locale = randchoice(locales)  # nosec

    # Parse the locale
    parser = tags.tag(locale)
    if not parser.region:
        raise ValueError(f"Invalid locale: {locale}. Region is required.")

    record = parser.language.data['record']

    # Return a formatted locale object
    return Locale(
        language=record['Subtag'],
        region=parser.region.data['record']['Subtag'],
        script=record.get('Suppress-Script'),
    )


"""
Helpers to fetch geolocation, timezone, and locale data given an IP.
"""

MMDB_FILE = LOCAL_DATA / 'GeoLite2-City.mmdb'
MMDB_URL = 'https://github.com/P3TERX/GeoLite.mmdb/releases/latest/download/GeoLite2-City.mmdb'


def geoip_allowed() -> None:
    """
    Checks if the geoip2 module is available.
    """
    if not ALLOW_GEOIP:
        raise NotInstalledGeoIPExtra(
            'Please install the geoip extra to use this feature: pip install camoufox[geoip]'
        )


def download_mmdb() -> None:
    """
    Downloads the MaxMind GeoIP2 database.
    """
    geoip_allowed()

    with open(MMDB_FILE, 'wb') as f:
        webdl(
            MMDB_URL,
            desc='Downloading GeoIP database',
            buffer=f,
        )


def remove_mmdb() -> None:
    """
    Removes the MaxMind GeoIP2 database.
    """
    if not MMDB_FILE.exists():
        rprint("GeoIP database not found.")
        return

    MMDB_FILE.unlink()
    rprint("GeoIP database removed.")


def get_geolocation(ip: str) -> Geolocation:
    """
    Gets the geolocation for an IP address.
    """
    # Check if the database is downloaded
    if not MMDB_FILE.exists():
        download_mmdb()

    # Validate the IP address
    validate_ip(ip)

    with geoip2.database.Reader(str(MMDB_FILE)) as reader:
        resp = reader.city(ip)
        iso_code = cast(str, resp.registered_country.iso_code)
        location = resp.location

        # Check if any required attributes are missing
        if any(not getattr(location, attr) for attr in ('longitude', 'latitude', 'time_zone')):
            raise UnknownIPLocation(f"Unknown IP location: {ip}")

        # Get a statistically correct locale based on the country code
        locale_finder = GetLocaleFromTerritory(iso_code)
        locale = locale_finder.get_locale()

        return Geolocation(
            locale=locale,
            longitude=cast(float, resp.location.longitude),
            latitude=cast(float, resp.location.latitude),
            timezone=cast(str, resp.location.time_zone),
        )


"""
Gets a random language based on the territory code.
"""


def get_unicode_info() -> ET.Element:
    """
    Fetches supplemental data from the territoryInfo.xml file.
    Source: https://raw.githubusercontent.com/unicode-org/cldr/master/common/supplemental/supplementalData.xml
    """
    with open(LOCAL_DATA / 'territoryInfo.xml', 'rb') as f:
        data = ET.XML(f.read())
    assert data is not None, 'Failed to load territoryInfo.xml'
    return data


class GetLocaleFromTerritory:
    """
    Calculates a random language based on the territory code,
    based on the probability that a person speaks the language in the territory.
    """

    def __init__(self, iso_code: str):
        self.iso_code = iso_code.upper()
        self.root = get_unicode_info()
        self.languages, self.probabilities = self._load_territory_data()

    def _load_territory_data(self) -> Tuple[np.ndarray, np.ndarray]:
        territory = self.root.find(f"territory[@type='{self.iso_code}']")

        if territory is None:
            raise UnknownTerritory(f"Unknown territory: {self.iso_code}")

        lang_population = territory.findall('languagePopulation')

        if not lang_population:
            raise ValueError(f"No language data found for territory: {self.iso_code}")

        # Use list comprehension for faster data extraction
        languages = np.array([lang.get('type') for lang in lang_population])
        percentages = np.array(
            [float(lang.get('populationPercent', '0')) for lang in lang_population]
        )

        # Normalize probabilities
        total = np.sum(percentages)
        probabilities = percentages / total

        return languages, probabilities

    def get_random_language(self) -> str:
        """
        Get a random language based on the territory ISO code.
        """
        return np.random.choice(self.languages, p=self.probabilities)

    def get_locale(self) -> Locale:
        """
        Get a random locale based on the territory ISO code.
        Returns as a Locale object.
        """
        language = self.get_random_language()
        return normalize_locale(f"{language}-{self.iso_code}")


if __name__ == "__main__":
    # Extra tests...
    from timeit import timeit

    print('LanguageSelector:', timeit(lambda: GetLocaleFromTerritory('ES'), number=100))

    ts = GetLocaleFromTerritory('ES')
    print('get_random_language:', timeit(lambda: ts.get_random_language(), number=10000))
