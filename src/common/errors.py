"""Custom exception definitions."""


class AgentOrchestratorError(Exception):
    """Base exception for all platform errors."""
    pass


class AgentNotFoundError(AgentOrchestratorError):
    def __init__(self, agent_id: str):
        super().__init__(f"Agent not found: {agent_id}")


class AgentTimeoutError(AgentOrchestratorError):
    def __init__(self, agent_id: str, timeout: int):
        super().__init__(f"Agent {agent_id} timed out after {timeout}s")


class TaskExecutionError(AgentOrchestratorError):
    def __init__(self, task_id: str, reason: str):
        super().__init__(f"Task {task_id} failed: {reason}")


class ConfigurationError(AgentOrchestratorError):
    def __init__(self, message: str):
        super().__init__(f"Configuration error: {message}")


class AuthenticationError(AgentOrchestratorError):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message)


class RateLimitError(AgentOrchestratorError):
    def __init__(self, retry_after: int = 60):
        super().__init__(f"Rate limit exceeded. Retry after {retry_after}s")
        self.retry_after = retry_after


class ResourceExhaustedError(AgentOrchestratorError):
    def __init__(self, resource: str):
        super().__init__(f"Resource exhausted: {resource}")


class CSRFValidationError(AgentOrchestratorError):
    def __init__(self, message: str = "CSRF validation failed"):
        super().__init__(message)


class MissingCSRFTokenError(CSRFValidationError):
    def __init__(self):
        super().__init__("Missing CSRF token")


class InvalidCSRFTokenError(CSRFValidationError):
    def __init__(self):
        super().__init__("Invalid or expired CSRF token")


class OrganizationMismatchError(CSRFValidationError):
    def __init__(self, expected: str, actual: str):
        super().__init__(f"CSRF token bound to organization {expected}, but request targets {actual}")