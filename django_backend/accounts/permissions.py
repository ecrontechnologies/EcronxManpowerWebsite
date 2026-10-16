"""Reusable DRF permissions enforcing role-based access control."""

from __future__ import annotations

from rest_framework import permissions


class IsAdministrator(permissions.BasePermission):
    """Only authenticated administrators may proceed."""

    message = "You are not authorized to access administrator data."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_administrator)


class IsEmployee(permissions.BasePermission):
    """Only authenticated (non-admin) employees may proceed."""

    message = "You are not authorized to access this attendance data."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == "employee")
