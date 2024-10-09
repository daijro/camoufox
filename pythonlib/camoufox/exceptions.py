class UnsupportedArchitecture(Exception):
    """
    Raised when the architecture is not supported.
    """

    ...


class UnsupportedOS(Exception):
    """
    Raised when the OS is not supported.
    """

    ...


class UnknownProperty(Exception):
    """
    Raised when the property is unknown.
    """

    ...


class InvalidPropertyType(Exception):
    """
    Raised when the property type is invalid.
    """

    ...


class InvalidAddonPath(FileNotFoundError):
    """
    Raised when the addon path is invalid.
    """

    ...


class InvalidDebugPort(ValueError):
    """
    Raised when the debug port is invalid.
    """

    ...


class MissingDebugPort(ValueError):
    """
    Raised when the debug port is missing.
    """

    ...


class LocaleError(Exception):
    """
    Raised when the locale is invalid.
    """

    ...


class InvalidIP(Exception):
    """
    Raised when an IP address is invalid.
    """

    ...


class InvalidProxy(Exception):
    """
    Raised when a proxy is invalid.
    """

    ...


class UnknownIPLocation(LocaleError):
    """
    Raised when the location of an IP is unknown.
    """

    ...


class UnknownTerritory(LocaleError):
    """
    Raised when the territory is unknown.
    """

    ...


class NotInstalledGeoIPExtra(ImportError):
    """
    Raised when the geoip2 module is not installed.
    """

    ...


class NonFirefoxFingerprint(Exception):
    """
    Raised when a passed Browserforge fingerprint is invalid.
    """

    ...


class InvalidOS(ValueError):
    """
    Raised when the target OS is invalid.
    """

    ...


class VirtualDisplayError(Exception):
    """
    Raised when there is an error with the virtual display.
    """

    ...


class CannotFindXvfb(VirtualDisplayError):
    """
    Raised when Xvfb cannot be found.
    """

    ...
    pass


class CannotExecuteXvfb(VirtualDisplayError):
    """
    Raised when Xvfb cannot be executed.
    """

    ...


class VirtualDisplayNotSupported(VirtualDisplayError):
    """
    Raised when the user tried to use a virtual display on a non-Linux OS.
    """

    ...
