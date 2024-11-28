import re
from typing import List


class StringValidator:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.patterns = self._split_patterns(pattern)

    def _split_patterns(self, p: str) -> List[str]:
        patterns = []
        current = []
        in_regex = False
        i = 0

        while i < len(p):
            if p[i] == '/' and (i == 0 or p[i - 1] != '!'):
                in_regex = not in_regex
                current.append(p[i])
            elif p[i] == ',' and not in_regex:
                # Check if comma is escaped
                if i > 0 and p[i - 1] == '!':
                    current.append(',')
                else:
                    # End of pattern
                    patterns.append(''.join(current))
                    current = []
            else:
                current.append(p[i])
            i += 1

        if current:
            patterns.append(''.join(current))

        result = [p.strip() for p in patterns if p.strip()]
        return result

    def _is_regex_pattern(self, p: str) -> bool:
        is_regex = p.startswith('/') and p.endswith('/') and not p.endswith('!/')
        return is_regex

    def _clean_literal_pattern(self, p: str) -> str:
        return re.sub(r'!(.)', r'\1', p)

    def validate(self, value: str) -> bool:
        for p in self.patterns:
            p = self._clean_literal_pattern(p)
            if self._is_regex_pattern(p):
                regex = p[1:-1]
                match = bool(re.match(regex, value))
                if match:
                    return True
            else:
                match = value == p
                if match:
                    return True

        return False


def string_validator(value: str, pattern: str) -> bool:
    validator = StringValidator(pattern)
    result = validator.validate(value)
    return result
