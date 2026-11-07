import logging

from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.response import Response
from rest_framework import status

from config.errors import ApplicationError

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    if isinstance(exc, ApplicationError):
        return Response({"detail": exc.message}, status=exc.status_code)

    response = drf_exception_handler(exc, context)

    if response is not None:
        if isinstance(response.data, dict) and "detail" not in response.data:
            response.data = {"detail": response.data}
        return response

    logger.exception("Unhandled exception in %s", context.get("view"))
    return Response(
        {"detail": "Internal server error."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
