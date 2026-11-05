"""Custom exceptions for Orca."""

class OrcaError(Exception):
    """Base exception for Orca errors."""
    pass


class OrcaValidationError(OrcaError):
    """Raised when validation fails — e.g., missing required column in batch mode."""
    def __init__(self, message: str, column: str = None, file: str = None, sheet: str = None, available_columns: list = None):
        self.column = column
        self.file = file
        self.sheet = sheet
        self.available_columns = available_columns or []
        super().__init__(message)