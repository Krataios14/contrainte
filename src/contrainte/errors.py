class ContrainteError(Exception):
    """Base exception for expected Contrainte failures."""


class InputError(ContrainteError):
    """Raised when an input cannot become a valid engineering artifact."""


class CanonicalizationError(ContrainteError):
    """Raised when a value cannot be represented canonically."""


class IntegrityError(ContrainteError):
    """Raised when content does not match its declared digest."""


class DimensionalityError(ContrainteError):
    """Raised when quantities with incompatible dimensions are combined."""


class ExecutionError(ContrainteError):
    """Raised when an external engineering or model process fails."""
