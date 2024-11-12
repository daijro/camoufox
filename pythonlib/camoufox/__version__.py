"""
Camoufox version constants.
"""


class CONSTRAINTS:
    """
    The minimum and maximum supported versions of the Camoufox browser.
    """

    MIN_VERSION = 'beta.15'
    MAX_VERSION = '1'

    @staticmethod
    def as_range() -> str:
        """
        Returns the version range as a string.
        """
        return f">={CONSTRAINTS.MIN_VERSION}, <{CONSTRAINTS.MAX_VERSION}"
