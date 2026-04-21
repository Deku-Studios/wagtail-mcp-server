"""``manage.py mcp_introspect``: list enabled toolsets and their tools.

Prints one block per enabled toolset with the toolset name, version, and
(eventually, once tool registration lands) the JSON schema for each tool.

Useful for verifying config changes take effect and for producing a
human-readable artifact to attach to PR reviews.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "List enabled toolsets, their tools, and JSON schemas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit a single JSON blob instead of the human-readable listing.",
        )

    def handle(self, *args, **options):
        from wagtail_mcp_server.registry import TOOLSET_MAP  # noqa: PLC0415
        from wagtail_mcp_server.settings import get_config  # noqa: PLC0415

        cfg = get_config()
        toolsets = cfg["TOOLSETS"]
        report: list[dict] = []
        for name, toolset_cfg in toolsets.items():
            enabled = bool(toolset_cfg.get("enabled", False))
            module_path, class_name = TOOLSET_MAP[name]
            report.append(
                {
                    "name": name,
                    "enabled": enabled,
                    "class": f"{module_path}.{class_name}",
                    "tools": [],  # populated in v0.2 once tool registration lands
                }
            )

        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2))
            return

        for entry in report:
            flag = "ON " if entry["enabled"] else "off"
            self.stdout.write(f"[{flag}] {entry['name']}")
            self.stdout.write(f"    class: {entry['class']}")
            if entry["enabled"] and not entry["tools"]:
                self.stdout.write(
                    "    tools: (registered in v0.2; scaffold is empty)"
                )
            self.stdout.write("")
