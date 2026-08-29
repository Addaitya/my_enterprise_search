"""SQLAlchemy models. File ACL and admin capability stay in separate tables.

Admin is the Keycloak realm role `admin` (mirrored in `roles` like any other role).
`file_acl` is resource-scoped. Identity tables are a complete Keycloak projection.
"""

from app.models.file import File, FileAcl
from app.models.identity import Group, Role, User, UserGroup, UserRole

__all__ = [
    "File",
    "FileAcl",
    "Group",
    "Role",
    "User",
    "UserGroup",
    "UserRole",
]
