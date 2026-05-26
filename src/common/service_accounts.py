"""Service account provisioning with unique external ID enforcement."""

import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ServiceAccountStatus(Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    PENDING = "pending"


@dataclass
class ServiceAccount:
    account_id: str
    name: str
    external_id: str
    organization_id: str
    status: ServiceAccountStatus = ServiceAccountStatus.ACTIVE
    metadata: Dict = field(default_factory=dict)


class ServiceAccountRegistry:
    """Manages service accounts with unique external ID enforcement per organization."""

    def __init__(self):
        self._accounts: Dict[str, ServiceAccount] = {}
        # Index: (organization_id, external_id) -> account_id for active accounts
        self._active_external_ids: Dict[str, Set[str]] = {}
        # Index: (organization_id, external_id) -> set of account_ids for disabled accounts
        self._disabled_external_ids: Dict[str, Set[str]] = {}

    def _make_key(self, org_id: str, external_id: str) -> str:
        return f"{org_id}:{external_id}"

    def _check_unique_external_id(self, org_id: str, external_id: str, exclude_account_id: str = None) -> None:
        """Check that external_id is unique among active accounts in the organization."""
        key = self._make_key(org_id, external_id)
        active_ids = self._active_external_ids.get(key, set())

        if exclude_account_id:
            active_ids = active_ids - {exclude_account_id}

        if active_ids:
            raise ValueError(
                f"External ID '{external_id}' is already in use by active service account(s) "
                f"in organization '{org_id}': {active_ids}"
            )

    def create(self, name: str, external_id: str, organization_id: str, metadata: Dict = None) -> ServiceAccount:
        """Create a new service account with unique external ID validation."""
        if not external_id:
            raise ValueError("External ID is required")
        if not organization_id:
            raise ValueError("Organization ID is required")

        self._check_unique_external_id(organization_id, external_id)

        account_id = f"sa-{len(self._accounts) + 1:06d}"
        account = ServiceAccount(
            account_id=account_id,
            name=name,
            external_id=external_id,
            organization_id=organization_id,
            status=ServiceAccountStatus.ACTIVE,
            metadata=metadata or {},
        )

        self._accounts[account_id] = account
        key = self._make_key(organization_id, external_id)
        self._active_external_ids.setdefault(key, set()).add(account_id)

        logger.info(f"Created service account {account_id} with external ID '{external_id}' in org '{organization_id}'")
        return account

    def update(self, account_id: str, name: str = None, external_id: str = None, metadata: Dict = None) -> ServiceAccount:
        """Update a service account. If external_id changes, validate uniqueness."""
        account = self._accounts.get(account_id)
        if not account:
            raise ValueError(f"Service account not found: {account_id}")

        if name is not None:
            account.name = name

        if external_id is not None and external_id != account.external_id:
            if not external_id:
                raise ValueError("External ID cannot be empty")

            # Remove old index entry
            old_key = self._make_key(account.organization_id, account.external_id)
            if account.status == ServiceAccountStatus.ACTIVE:
                self._active_external_ids.get(old_key, set()).discard(account_id)
            else:
                self._disabled_external_ids.get(old_key, set()).discard(account_id)

            # Check uniqueness for new external_id
            self._check_unique_external_id(account.organization_id, external_id)

            # Update index
            account.external_id = external_id
            new_key = self._make_key(account.organization_id, external_id)
            if account.status == ServiceAccountStatus.ACTIVE:
                self._active_external_ids.setdefault(new_key, set()).add(account_id)
            else:
                self._disabled_external_ids.setdefault(new_key, set()).add(account_id)

        if metadata is not None:
            account.metadata.update(metadata)

        return account

    def disable(self, account_id: str) -> ServiceAccount:
        """Disable a service account. External ID becomes available for reuse."""
        account = self._accounts.get(account_id)
        if not account:
            raise ValueError(f"Service account not found: {account_id}")

        if account.status == ServiceAccountStatus.DISABLED:
            return account

        # Move from active to disabled index
        key = self._make_key(account.organization_id, account.external_id)
        self._active_external_ids.get(key, set()).discard(account_id)
        self._disabled_external_ids.setdefault(key, set()).add(account_id)

        account.status = ServiceAccountStatus.DISABLED
        logger.info(f"Disabled service account {account_id}")
        return account

    def restore(self, account_id: str) -> ServiceAccount:
        """Restore a disabled service account. External ID must be unique among active accounts."""
        account = self._accounts.get(account_id)
        if not account:
            raise ValueError(f"Service account not found: {account_id}")

        if account.status != ServiceAccountStatus.DISABLED:
            return account

        # Check uniqueness before restoring
        self._check_unique_external_id(account.organization_id, account.external_id)

        # Move from disabled to active index
        key = self._make_key(account.organization_id, account.external_id)
        self._disabled_external_ids.get(key, set()).discard(account_id)
        self._active_external_ids.setdefault(key, set()).add(account_id)

        account.status = ServiceAccountStatus.ACTIVE
        logger.info(f"Restored service account {account_id}")
        return account

    def get(self, account_id: str) -> Optional[ServiceAccount]:
        return self._accounts.get(account_id)

    def list_by_org(self, organization_id: str, status: ServiceAccountStatus = None) -> List[ServiceAccount]:
        result = [
            a for a in self._accounts.values()
            if a.organization_id == organization_id
        ]
        if status:
            result = [a for a in result if a.status == status]
        return result

    def find_by_external_id(self, organization_id: str, external_id: str) -> Optional[ServiceAccount]:
        key = self._make_key(organization_id, external_id)
        active_ids = self._active_external_ids.get(key, set())
        if active_ids:
            return self._accounts.get(next(iter(active_ids)))
        return None

    def get_existing_duplicates(self, organization_id: str) -> List[Dict]:
        """Find existing duplicate external IDs for migration purposes."""
        seen: Dict[str, List[str]] = {}
        for account in self._accounts.values():
            if account.organization_id == organization_id and account.status == ServiceAccountStatus.ACTIVE:
                seen.setdefault(account.external_id, []).append(account.account_id)

        return [
            {"external_id": ext_id, "account_ids": ids}
            for ext_id, ids in seen.items()
            if len(ids) > 1
        ]


# Global registry instance
service_account_registry = ServiceAccountRegistry()
