"""Exception classes for jsonvv"""


class JvvException(Exception):
    pass


class JvvRuntimeException(JvvException):
    pass


class JvvSyntaxError(JvvException):
    pass


class UnknownProperty(JvvRuntimeException, ValueError):
    pass


class InvalidPropertyType(JvvRuntimeException, TypeError):
    pass


class MissingRequiredKey(InvalidPropertyType):
    pass


class MissingGroupKey(MissingRequiredKey):
    pass


class PropertySyntaxError(JvvSyntaxError):
    pass
