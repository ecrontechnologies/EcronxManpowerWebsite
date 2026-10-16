"""Custom DRF exception handler returning the ``{"error": "..."}`` shape the frontend expects."""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.views import exception_handler as drf_exception_handler


def api_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        message = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        from rest_framework.response import Response
        from rest_framework import status

        return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    if isinstance(detail, dict):
        if "detail" in detail:
            message = detail["detail"]
        else:
            # Flatten the first field error into a readable sentence.
            first_key = next(iter(detail))
            value = detail[first_key]
            if isinstance(value, (list, tuple)) and value:
                message = f"{first_key}: {value[0]}"
            else:
                message = f"{first_key}: {value}"
    else:
        message = detail

    response.data = {"error": str(message)}
    return response
