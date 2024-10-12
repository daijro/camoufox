import xml.etree.ElementTree as ET  # nosec
from dataclasses import dataclass
from random import choice as randchoice
from typing import Any, Dict, List, Optional, Tuple, cast

import numpy as np
from language_tags import tags

from camoufox.pkgman import LOCAL_DATA, rprint, webdl
from camoufox.warnings import LeakWarning

from .exceptions import (
    InvalidLocale,
    NotInstalledGeoIPExtra,
    UnknownIPLocation,
    UnknownLanguage,
    UnknownTerritory,
)
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
        raise InvalidLocale.invalid_input(loc)


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
        raise InvalidLocale.invalid_input(locale)

    record = parser.language.data['record']

    # Return a formatted locale object
    return Locale(
        language=record['Subtag'],
        region=parser.region.data['record']['Subtag'],
        script=record.get('Suppress-Script'),
    )


def handle_locale(locale: str) -> Locale:
    """
    Handles a locale input, normalizing it if necessary.
    """
    if len(locale) > 3:
        return normalize_locale(locale)

    try:
        return SELECTOR.from_region(locale)
    except UnknownTerritory:
        pass

    try:
        language = SELECTOR.from_language(locale)
    except UnknownLanguage:
        pass
    else:
        LeakWarning.warn('no_region')
        return language

    raise InvalidLocale.invalid_input(locale)


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
        iso_code = cast(str, resp.registered_country.iso_code).upper()
        location = resp.location

        # Check if any required attributes are missing
        if any(not getattr(location, attr) for attr in ('longitude', 'latitude', 'time_zone')):
            raise UnknownIPLocation(f"Unknown IP location: {ip}")

        # Get a statistically correct locale based on the country code
        locale = SELECTOR.from_region(iso_code)

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


def _as_float(element: ET.Element, attr: str) -> float:
    """
    Converts an attribute to a float.
    """
    return float(element.get(attr, 0))


class StatisticalLocaleSelector:
    """
    Selects a random locale based on statistical data.
    Takes either a territory code or a language code, and generates a Locale object.
    """

    def __init__(self):
        self.root = get_unicode_info()

    def _load_territory_data(self, iso_code: str) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calculates a random language based on the territory code,
        based on the probability that a person speaks the language in the territory.
        """
        territory = self.root.find(f"territory[@type='{iso_code}']")
        if territory is None:
            raise UnknownTerritory(f"Unknown territory: {iso_code}")

        lang_populations = territory.findall('languagePopulation')
        if not lang_populations:
            raise ValueError(f"No language data found for region: {iso_code}")

        languages = np.array([lang.get('type') for lang in lang_populations])
        percentages = np.array([_as_float(lang, 'populationPercent') for lang in lang_populations])

        return self.normalize_probabilities(languages, percentages)

    def _load_language_data(self, language: str) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calculates a random region for a language
        based on the total speakers of the language in that region.
        """
        territories = self.root.findall(f'.//territory/languagePopulation[@type="{language}"]/..')
        if not territories:
            raise UnknownLanguage(f"No region data found for language: {language}")

        regions = []
        percentages = []

        for terr in territories:
            region = terr.get('type')
            if region is None:
                continue  # Skip if region is not found

            lang_pop = terr.find(f'languagePopulation[@type="{language}"]')
            if lang_pop is None:
                continue  # This shouldn't happen due to our XPath, but just in case

            regions.append(region)
            percentages.append(
                _as_float(lang_pop, 'populationPercent')
                * _as_float(terr, 'literacyPercent')
                / 10_000
                * _as_float(terr, 'population')
            )

        if not regions:
            raise ValueError(f"No valid region data found for language: {language}")

        return self.normalize_probabilities(np.array(regions), np.array(percentages))

    def normalize_probabilities(
        self, languages: np.ndarray, freq: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Normalize probabilities.
        """
        total = np.sum(freq)
        return languages, freq / total

    def from_region(self, region: str) -> Locale:
        """
        Get a random locale based on the territory ISO code.
        Returns as a Locale object.
        """
        languages, probabilities = self._load_territory_data(region)
        language = np.random.choice(languages, p=probabilities).replace('_', '-')
        return normalize_locale(f"{language}-{region}")

    def from_language(self, language: str) -> Locale:
        """
        Get a random locale based on the language.
        Returns as a Locale object.
        """
        regions, probabilities = self._load_language_data(language)
        region = np.random.choice(regions, p=probabilities)
        return normalize_locale(f"{language}-{region}")


SELECTOR = StatisticalLocaleSelector()
