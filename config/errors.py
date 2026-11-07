from rest_framework import status


class ApplicationError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        super().__init__(message)


class PermissionDeniedError(ApplicationError):
    status_code = status.HTTP_403_FORBIDDEN


class NotFoundError(ApplicationError):
    status_code = status.HTTP_404_NOT_FOUND
