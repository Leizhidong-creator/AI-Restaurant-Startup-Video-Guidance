class DomainError(Exception):
    """Stable application error exposed by the HTTP boundary."""

    def __init__(self, message: str, *, code: str = "domain_error", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class NotFoundError(DomainError):
    def __init__(self, resource: str):
        super().__init__(
            f"{resource}不存在",
            code="not_found",
            status_code=404,
        )


class ExternalServiceError(DomainError):
    def __init__(self, service: str, message: str, *, retryable: bool = True):
        status_code = 503 if retryable else 502
        super().__init__(
            f"{service}调用失败：{message}",
            code="external_service_error",
            status_code=status_code,
        )
        self.service = service
        self.retryable = retryable


