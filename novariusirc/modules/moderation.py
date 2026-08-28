"""Compatibility shim for configurations that still list the old module.

Moderation is a core service and is configured through ``[moderation]``. Loading
this module no longer installs a second, conflicting moderation implementation.
"""

from __future__ import annotations

from novariusirc.core.plugins import Plugin as BuiltinPlugin


class Plugin(BuiltinPlugin):
    name = "moderation"

    async def start(self) -> None:
        self.logger.warning(
            "The moderation built-in is obsolete; remove 'moderation' from "
            "[modules].enabled and configure the core [moderation] service instead"
        )
