"""SQLAlchemy models. File ACL and admin capability stay in separate tables.

Admin is the Keycloak realm role `admin` (mirrored in `roles` like any other role).
`file_acl` is resource-scoped. Identity tables are a complete Keycloak projection.
"""

from app.models.acl_job import AclSyncJob
from app.models.connector import Connector, ConnectorSync
from app.models.file import File, FileAcl
from app.models.identity import Group, Role, User, UserGroup, UserRole
from app.models.ingest_job import IngestJob
from app.models.search_metrics import SearchQueryMetric
from app.models.upload_session import UploadSession

__all__ = [
    "AclSyncJob",
    "Connector",
    "ConnectorSync",
    "File",
    "FileAcl",
    "Group",
    "IngestJob",
    "Role",
    "SearchQueryMetric",
    "UploadSession",
    "User",
    "UserGroup",
    "UserRole",
]
