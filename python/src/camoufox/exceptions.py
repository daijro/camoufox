class UnsupportedVersion(Exception):
    """
    Raised when the Camoufox executable is outdated.
    """

    ...


class MissingRelease(Exception):
    """
    Raised when a required GitHub release asset is missing.
    """

    ...


class CorruptedDownload(Exception):
    """
    Raised when a downloaded asset does not match its expected sha256 digest.
    """

    ...


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


class InvalidLocale(LocaleError):
    """
    Raised when the locale input is invalid.
    """

    @classmethod
    def invalid_input(cls, locale: str) -> 'InvalidLocale':
        return cls(
            f"Invalid locale: '{locale}'. Must be either a region, language, "
            "language-region, or language-script-region."
        )


class UnknownTerritory(InvalidLocale):
    """
    Raised when the territory is unknown.
    """

    ...


class UnknownLanguage(InvalidLocale):
    """
    Raised when the language is unknown.
    """

    ...


class NotInstalledGeoIPExtra(ImportError):
    """
    Raised when the maxminddb module is not installed.
    """

    ...


class NonFirefoxFingerprint(Exception):
    """
    Raised when a passed fingerprint is not a Firefox fingerprint.
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


class GpuDisplayError(VirtualDisplayError):
    """
    Raised when the headless='virtual-gpu' display cannot be used.
    """

    ...


class NoGpuFound(GpuDisplayError):
    """
    Raised when no GPU render node with a PCI address is found.
    """

    ...


class AmbiguousGpuSelection(GpuDisplayError):
    """
    Raised when several GPUs match, or several exist and none was named.
    """

    ...


class GpuNotFound(GpuDisplayError):
    """
    Raised when the GPU selector matches no GPU.
    """

    ...


class CannotFindXorg(GpuDisplayError):
    """
    Raised when Xorg cannot be found.
    """

    ...


class CannotExecuteXorg(GpuDisplayError):
    """
    Raised when Xorg cannot be started, or exits right after starting.
    """

    ...


class GpuVtTakeover(GpuDisplayError):
    """
    Raised when the Xorg server switched the active console VT.
    """

    ...


class GpuSoftwareFallback(GpuDisplayError):
    """
    Raised when the browser on a GPU display never rendered on the GPU.
    """

    ...


class CamoufoxNotInstalled(FileNotFoundError):
    """
    Raised when camoufox is not installed.
    """

    ...


class ProfileDirectoryError(RuntimeError):
    """Raised when Camoufox's required runtime directory cannot be prepared."""

    ...


class FpgenModelError(RuntimeError):
    """Raised when fpgen's pinned model cannot be installed where fpgen reads it."""

    ...


class HumanizeEngineUnavailable(ValueError):
    """
    Raised at launch when `humanize` names an engine the browser build does not
    ship: one its humanize-engines.json does not list for that channel.
    """

    def __init__(self, channel: str, engine: str, available: list, reason: str = '') -> None:
        self.channel = channel
        self.engine = engine
        self.available = available
        super().__init__(
            f'humanize {channel}: {engine} is not available in this build'
            + (f' ({reason})' if reason else '')
            + f'; available: {available}'
        )
