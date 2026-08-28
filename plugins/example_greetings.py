"""Example greeting plugin for NovariusIRC.

Demonstrates plugin functionality:
- Hook for on_join events
- Custom command with @command decorator
"""

from novariusirc.core.plugins import BasePlugin, CommandContext, command


class GreetingPlugin(BasePlugin):
    """Simple greeting plugin."""

    name = "greetings"
    version = "1.0"
    description = "Greets users when they join"

    async def on_load(self) -> None:
        """Called when plugin loads."""
        self.logger.info("Example greeting plugin loaded")

    async def on_join(self, ctx: CommandContext) -> None:
        """Greet user when they join the channel."""
        if ctx.channel:
            await ctx.reply(f"Welcome {ctx.nick}!")

    @command(role="user")
    async def cmd_hello(self, ctx: CommandContext, args: list[str]) -> None:
        """Say hello to the user.

        Usage: !hello
        """
        await ctx.reply(f"Hello {ctx.nick}!")

    @command(role="admin", aliases=["greet"])
    async def cmd_welcome(self, ctx: CommandContext, args: list[str]) -> None:
        """Welcome everyone in the channel.

        Usage: !welcome or !greet
        """
        await ctx.reply("Welcome everyone!")
