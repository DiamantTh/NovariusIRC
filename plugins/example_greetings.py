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
        print(f"[{self.name}] Loaded!")

    async def on_join(self, ctx: CommandContext) -> None:
        """Greet user when they join the channel."""
        # Example: Send greeting
        # await ctx.irc.send_message(ctx.channel, f"Welcome {ctx.nick}!")
        pass

    @command(role="user")
    async def cmd_hello(self, ctx: CommandContext) -> None:
        """Say hello to the user.

        Usage: !hello
        """
        # Example: Reply to command
        # await ctx.irc.send_message(ctx.channel, f"Hello {ctx.nick}!")
        pass

    @command(role="admin", aliases=["greet"])
    async def cmd_welcome(self, ctx: CommandContext) -> None:
        """Welcome everyone in the channel.

        Usage: !welcome or !greet
        """
        # Example: Admin-only command
        # await ctx.irc.send_message(ctx.channel, "Welcome everyone!")
        pass
