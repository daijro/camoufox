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
