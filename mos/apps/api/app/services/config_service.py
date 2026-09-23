"""Configuration service with multi-level caching.

Supports platform/tenant/user scope hierarchy with automatic fallback.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_config import ConfigFlag


class ConfigService:
    """Configuration service with scope hierarchy and caching.

    Scope resolution order: user → tenant → platform → default
    """

    _cache: dict[str, Any] = {}

    @classmethod
    def get(
        cls,
        db: Session,
        key: str,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        default: Any = None,
    ) -> Any:
        """Get configuration value with scope fallback.

        Args:
            db: Database session
            key: Configuration flag key
            tenant_id: Optional tenant UUID
            user_id: Optional user UUID
            default: Default value if not found

        Returns:
            Configuration value (parsed according to value_type)
        """
        # Try user scope first
        if user_id:
            val = cls._get_flag(db, key, scope="user", user_id=user_id)
            if val is not None:
                return cls._parse_value(val)

        # Try tenant scope
        if tenant_id:
            val = cls._get_flag(db, key, scope="tenant", tenant_id=tenant_id)
            if val is not None:
                return cls._parse_value(val)

        # Try platform scope
        val = cls._get_flag(db, key, scope="platform")
        if val is not None:
            return cls._parse_value(val)

        return default

    @classmethod
    def set(
        cls,
        db: Session,
        key: str,
        value: Any,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        category: str = "general",
        description: str | None = None,
        updated_by: UUID | None = None,
    ) -> ConfigFlag:
        """Set configuration value at appropriate scope.

        Args:
            db: Database session
            key: Configuration flag key
            value: Value to set
            tenant_id: Optional tenant UUID (if None, platform scope)
            user_id: Optional user UUID (if None, tenant or platform scope)
            category: Configuration category
            description: Optional description
            updated_by: User who updated

        Returns:
            Updated ConfigFlag
        """
        # Determine scope
        if user_id:
            scope = "user"
            scope_key = str(user_id)
        elif tenant_id:
            scope = "tenant"
            scope_key = str(tenant_id)
        else:
            scope = "platform"
            scope_key = "platform"

        # Determine value type
        value_type = cls._infer_type(value)
        value_str = cls._serialize_value(value, value_type)

        # Check if flag exists
        flag = db.scalar(
            select(ConfigFlag).where(
                ConfigFlag.scope_key == scope_key,
                ConfigFlag.flag_key == key,
            )
        )

        if flag:
            flag.flag_value = value_str
            flag.value_type = value_type
            flag.updated_by = updated_by
        else:
            flag = ConfigFlag(
                tenant_id=tenant_id,
                user_id=user_id,
                scope_key=scope_key,
                flag_key=key,
                flag_value=value_str,
                value_type=value_type,
                category=category,
                description=description,
                updated_by=updated_by,
            )
            db.add(flag)

        db.commit()
        db.refresh(flag)

        # Clear cache
        cls._cache.clear()

        return flag

    @classmethod
    def get_bool(
        cls,
        db: Session,
        key: str,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        default: bool = False,
    ) -> bool:
        """Get boolean configuration value."""
        val = cls.get(db, key, tenant_id, user_id, default)
        return bool(val)

    @classmethod
    def get_number(
        cls,
        db: Session,
        key: str,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        default: float = 0.0,
    ) -> float:
        """Get numeric configuration value."""
        val = cls.get(db, key, tenant_id, user_id, default)
        return float(val)

    @classmethod
    def get_string(
        cls,
        db: Session,
        key: str,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        default: str = "",
    ) -> str:
        """Get string configuration value."""
        val = cls.get(db, key, tenant_id, user_id, default)
        return str(val)

    @classmethod
    def list_flags(
        cls,
        db: Session,
        tenant_id: UUID | None = None,
        category: str | None = None,
    ) -> list[ConfigFlag]:
        """List configuration flags.

        Args:
            db: Database session
            tenant_id: Optional tenant filter
            category: Optional category filter

        Returns:
            List of ConfigFlag
        """
        stmt = select(ConfigFlag)
        if tenant_id:
            stmt = stmt.where(
                (ConfigFlag.tenant_id == tenant_id)
                | (ConfigFlag.scope_key == "platform")
            )
        if category:
            stmt = stmt.where(ConfigFlag.category == category)
        return list(db.scalars(stmt.order_by(ConfigFlag.category, ConfigFlag.flag_key)).all())

    @classmethod
    def _get_flag(
        cls,
        db: Session,
        key: str,
        scope: str,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> ConfigFlag | None:
        """Get flag at specific scope."""
        if scope == "user" and user_id:
            scope_key = str(user_id)
        elif scope == "tenant" and tenant_id:
            scope_key = str(tenant_id)
        elif scope == "platform":
            scope_key = "platform"
        else:
            return None

        return db.scalar(
            select(ConfigFlag).where(
                ConfigFlag.scope_key == scope_key,
                ConfigFlag.flag_key == key,
            )
        )

    @classmethod
    def _parse_value(cls, flag: ConfigFlag) -> Any:
        """Parse flag value according to value_type."""
        val = flag.flag_value
        vtype = flag.value_type

        if vtype == "bool":
            return val.lower() in ("true", "1", "yes", "on")
        elif vtype == "number":
            return float(val)
        elif vtype == "json":
            return json.loads(val)
        else:  # string
            return val

    @classmethod
    def _infer_type(cls, value: Any) -> str:
        """Infer value type from Python type."""
        if isinstance(value, bool):
            return "bool"
        elif isinstance(value, (int, float)):
            return "number"
        elif isinstance(value, (dict, list)):
            return "json"
        else:
            return "string"

    @classmethod
    def _serialize_value(cls, value: Any, value_type: str) -> str:
        """Serialize value to string for storage."""
        if value_type == "bool":
            return "true" if value else "false"
        elif value_type == "number":
            return str(value)
        elif value_type == "json":
            return json.dumps(value)
        else:
            return str(value)
