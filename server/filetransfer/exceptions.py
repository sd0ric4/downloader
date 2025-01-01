class ProtocolError(Exception):
    pass


class SecurityError(ProtocolError):
    pass


class ChecksumError(SecurityError):
    pass
