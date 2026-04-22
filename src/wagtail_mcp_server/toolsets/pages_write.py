"""Page write toolset.

Off by default. Enables draft-and-publish flows under strict permission
checks. Ships six tools:

    pages.create     Create a draft child under a parent page.
    pages.update     Update field values; creates a new revision.
    pages.publish    Publish a revision (latest by default).
    pages.unpublish  Unpublish a live page.
    pages.delete     Delete a page (destructive; three-gate).
    pages.move       Move a page to a new parent.

Three gates guard every destructive write:

    1. The toolset itself must be enabled (handled at registration).
    2. ``LIMITS.ALLOW_DESTRUCTIVE`` must be ``True`` in settings.
    3. The user must hold the matching Wagtail permission
       (``add``, ``change``, ``publish``, ``delete``, ``move``).

Any of the three failing short-circuits the call; no database mutation
happens until all three pass. StreamField writes go through the strict
envelope validator in :mod:`wagtail_mcp_server.serializers.streamfield`,
so agents that send an unknown block type or miss a required struct
child get a structured error back instead of a 500.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from mcp_server.djangomcp import MCPToolset

from ..serializers.streamfield import (
    DeserializeOptions,
    deserialize_streamfield,
)
from ..settings import get_config

# Move positions Wagtail's ``page.move()`` accepts. Exposed so the schema
# generator and docs pick up a single source of truth.
MOVE_POSITIONS = ("first-child", "last-child", "left", "right")


class PageWriteToolset(MCPToolset):
    """django-mcp-server toolset for page writes.

    The caller is resolved from ``self.request.user`` on every call.
    """

    name = "pages_write"
    version = "0.4.0"

    # ------------------------------------------------------------------ pages.create

    def pages_create(
        self,
        *,
        type: str,
        parent_id: int,
        fields: dict[str, Any] | None = None,
        publish: bool = False,
    ) -> dict[str, Any]:
        """Create a new page as a draft child of ``parent_id``.

        ``type`` is the ``"app_label.ClassName"`` of the Page subclass to
        instantiate. ``fields`` carries the model field values; StreamField
        values must be envelope-shaped and are validated strictly before
        anything touches the database.

        ``publish=True`` publishes the newly created revision immediately;
        this is a separate permission (``publish_page``) from the create
        permission (``add_page``).
        """
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        parent = self._get_page_or_404(parent_id)
        model = _resolve_page_model_or_404(type)
        if not _can_add_subpage(user, parent, model):
            raise PermissionDenied(
                f"User lacks add permission for '{type}' under parent {parent_id}."
            )

        native_fields = _prepare_fields(model, fields or {})
        instance = model(**native_fields)
        # Wagtail's Page.live defaults to True; for a draft-create flow we
        # want the page to land unpublished until pages.publish (or publish=True)
        # says otherwise. The admin "Save draft" path does the same thing.
        if not publish:
            instance.live = False
            instance.has_unpublished_changes = True
        parent.add_child(instance=instance)

        revision = instance.save_revision(user=user)
        result = _page_write_result(instance, revision)
        if publish:
            if not _can_publish(user, instance):
                raise PermissionDenied(
                    f"User lacks publish permission for page {instance.pk}."
                )
            revision.publish(user=user)
            instance.refresh_from_db()
            result["live"] = bool(instance.live)
        return result

    # ------------------------------------------------------------------ pages.update

    def pages_update(
        self,
        *,
        id: int,
        fields: dict[str, Any] | None = None,
        publish: bool = False,
    ) -> dict[str, Any]:
        """Update a page's field values and save a new revision."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        page = self._get_page_or_404(id).specific
        if not _can_edit(user, page):
            raise PermissionDenied(f"User lacks edit permission for page {id}.")

        native_fields = _prepare_fields(type(page), fields or {})
        for name, value in native_fields.items():
            setattr(page, name, value)

        revision = page.save_revision(user=user)
        result = _page_write_result(page, revision)
        if publish:
            if not _can_publish(user, page):
                raise PermissionDenied(
                    f"User lacks publish permission for page {page.pk}."
                )
            revision.publish(user=user)
            page.refresh_from_db()
            result["live"] = bool(page.live)
        return result

    # ----------------------------------------------------------------- pages.publish

    def pages_publish(
        self,
        *,
        id: int,
        revision_id: int | None = None,
    ) -> dict[str, Any]:
        """Publish a revision. Defaults to the latest revision."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        page = self._get_page_or_404(id).specific
        if not _can_publish(user, page):
            raise PermissionDenied(f"User lacks publish permission for page {id}.")

        revision = (
            page.revisions.get(pk=revision_id) if revision_id else page.latest_revision
        )
        if revision is None:
            raise ValueError(f"Page {id} has no revision to publish.")
        revision.publish(user=user)
        page.refresh_from_db()
        return {
            "id": page.pk,
            "revision_id": revision.pk,
            "live": bool(page.live),
        }

    # --------------------------------------------------------------- pages.unpublish

    def pages_unpublish(
        self,
        *,
        id: int,
    ) -> dict[str, Any]:
        """Unpublish a live page."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        page = self._get_page_or_404(id).specific
        if not _can_unpublish(user, page):
            raise PermissionDenied(f"User lacks unpublish permission for page {id}.")

        page.unpublish(user=user)
        page.refresh_from_db()
        return {"id": page.pk, "live": bool(page.live)}

    # ----------------------------------------------------------------- pages.delete

    def pages_delete(
        self,
        *,
        id: int,
    ) -> dict[str, Any]:
        """Delete a page. Three-gate: destructive + permission + toolset flag."""
        user = getattr(self.request, "user", None)
        _require_authenticated(user)
        _require_destructive_gate("pages.delete")

        page = self._get_page_or_404(id).specific
        if not _can_delete(user, page):
            raise PermissionDenied(f"User lacks delete permission for page {id}.")

        pk = page.pk
        page.delete(user=user)
        return {"id": pk, "deleted": True}

    # ------------------------------------------------------------------- pages.move

    def pages_move(
        self,
        *,
        id: int,
        parent_id: int,
        position: str = "last-child",
    ) -> dict[str, Any]:
        """Move a page to a new parent.

        ``position`` is one of :data:`MOVE_POSITIONS` and is passed through
        to Treebeard's ``move()`` unchanged.
        """
        user = getattr(self.request, "user", None)
        _require_authenticated(user)

        if position not in MOVE_POSITIONS:
            raise ValueError(
                f"position must be one of {list(MOVE_POSITIONS)}; got {position!r}."
            )

        page = self._get_page_or_404(id).specific
        if not _can_move(user, page):
            raise PermissionDenied(f"User lacks move permission for page {id}.")

        new_parent = self._get_page_or_404(parent_id)
        page.move(new_parent, pos=position, user=user)
        page.refresh_from_db()
        return {
            "id": page.pk,
            "parent_id": new_parent.pk,
            "url_path": page.url_path,
            "position": position,
        }

    # ---------------------------------------------------------------- internal

    def _get_page_or_404(self, page_id: int) -> Any:
        from wagtail.models import Page

        try:
            return Page.objects.get(pk=page_id)
        except Page.DoesNotExist as exc:
            raise ValueError(f"Page id={page_id} does not exist.") from exc


# --------------------------------------------------------------------- helpers
#
# Pulled out as module-level helpers so the unit tests can exercise the
# permission and gate logic without constructing the whole toolset.


def _require_authenticated(user: Any) -> None:
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Anonymous users cannot call write tools.")


def _require_destructive_gate(tool_name: str) -> None:
    cfg = get_config()
    if not cfg.get("LIMITS", {}).get("ALLOW_DESTRUCTIVE", False):
        raise PermissionDenied(
            f"{tool_name} requires WAGTAIL_MCP_SERVER.LIMITS.ALLOW_DESTRUCTIVE=True."
        )


def _prepare_fields(model: Any, fields: dict[str, Any]) -> dict[str, Any]:
    """Coerce an agent-supplied fields dict into Wagtail-native values.

    Dispatches per field kind:

    - ``StreamField`` values run through the strict envelope validator.
    - ``ForeignKey`` values accept ``int``, ``{"_raw_id": int}``, or an
      already-resolved instance, and are handed to Django as the related
      instance.
    - Unknown fields are dropped with no error. The caller is expected to
      have already validated the field list via ``pages.types.schema`` if
      strict shape enforcement is desired.
    """
    from django.db import models as dj_models
    from wagtail.fields import StreamField

    options = DeserializeOptions(validation=get_config()["WRITE_VALIDATION"])
    out: dict[str, Any] = {}
    for name, value in fields.items():
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            continue  # unknown field: drop silently.

        if isinstance(field, StreamField):
            out[name] = deserialize_streamfield(
                field.stream_block, value, options=options
            )
        elif isinstance(field, dj_models.ForeignKey):
            out[name] = _resolve_fk(field, value)
        else:
            out[name] = value
    return out


def _resolve_fk(field: Any, value: Any) -> Any:
    """Resolve an FK input into a model instance or ``None``.

    Accepts: ``None``, an ``int`` pk, ``{"_raw_id": int, ...}``, or an
    already-resolved instance (returned as-is).
    """
    if value is None or hasattr(value, "pk"):
        return value
    if isinstance(value, dict):
        value = value.get("_raw_id")
    if value is None:
        return None
    try:
        return field.related_model.objects.get(pk=value)
    except field.related_model.DoesNotExist:
        return None


def _page_write_result(page: Any, revision: Any) -> dict[str, Any]:
    return {
        "id": page.pk,
        "slug": getattr(page, "slug", ""),
        "url_path": getattr(page, "url_path", ""),
        "revision_id": revision.pk,
        "live": bool(getattr(page, "live", False)),
    }


def _resolve_page_model_or_404(type_name: str) -> Any:
    from django.apps import apps

    try:
        app_label, model_name = type_name.split(".", 1)
    except ValueError as exc:
        raise ValueError(
            f"type must be 'app_label.ClassName'; got {type_name!r}."
        ) from exc
    try:
        return apps.get_model(app_label, model_name)
    except LookupError as exc:
        raise ValueError(f"Unknown page type {type_name!r}.") from exc


# ------------------------------------------------------------ permission helpers
#
# Wagtail's page permission API varies subtly across versions; these
# helpers centralize the ``permissions_for_user(user).can_*()`` calls so a
# future API change touches one place.


def _perms(user: Any, page: Any) -> Any:
    return page.permissions_for_user(user)


def _can_edit(user: Any, page: Any) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return bool(_perms(user, page).can_edit())


def _can_publish(user: Any, page: Any) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return bool(_perms(user, page).can_publish())


def _can_unpublish(user: Any, page: Any) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return bool(_perms(user, page).can_unpublish())


def _can_delete(user: Any, page: Any) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return bool(_perms(user, page).can_delete())


def _can_move(user: Any, page: Any) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    perms = _perms(user, page)
    can_move = getattr(perms, "can_move", None)
    if callable(can_move):
        return bool(can_move())
    # Older Wagtail: move permission is implied by edit + delete.
    return bool(perms.can_edit()) and bool(perms.can_delete())


def _can_add_subpage(user: Any, parent: Any, model: Any) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    perms = _perms(user, parent)
    # Wagtail exposes ``can_add_subpage()`` on the parent's permission
    # object; the model class gets implicitly checked against the parent's
    # ``subpage_types`` whitelist via the save() path.
    can_add = getattr(perms, "can_add_subpage", None)
    if callable(can_add):
        return bool(can_add())
    return False
