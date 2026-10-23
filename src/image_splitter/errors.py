class SplitError(Exception):
    """Base class of all errors in this package."""


class ConfigError(SplitError):
    """A setting is missing or a value is invalid."""


class LimitError(SplitError):
    """A limit was exceeded."""


class UnsupportedFileError(SplitError):
    """The file type is not supported or the file cannot be read."""


class ModelError(SplitError):
    """The model server did not answer, or the answer was unusable."""
