# IRC and IRCv3 protocol support

The protocol, neutral incoming-message metadata, capability-state,
connection-state, bounded line reading, outbound flow-control, and safe
wire-construction primitives live in
`novariusirc.irc`. They
are intentionally independent of commands, operator roles, modules, feeds,
and moderation. `novariusirc.core.client` remains the adapter that connects
those IRC events to the bot.

This matrix describes implemented behavior, not every extension an IRC server
may advertise. Optional capabilities are requested only when both configured
and offered by the server.

Work-in-progress capabilities are kept separate in
`network.ircv3_draft_capabilities`. They must use the `draft/` namespace and
remain disabled unless the operator names them explicitly. Advertising and
negotiating a draft does not by itself imply that its higher-level semantics
are implemented by the bot.

## IRCv3

| Feature | Status | Behavior |
| --- | --- | --- |
| CAP 302 / cap-notify | Implemented | Multiline `CAP LS`, `ACK`, `NAK`, `NEW`, and `DEL`; requests are split below the IRC line limit. |
| Message tags | Implemented | Escaping, valueless tags, tag/body size limits, and propagation to commands/plugins. |
| `batch` | Implemented | Bounded lifecycle and nesting tracking; malformed, duplicate, orphaned, and excessive batches are rejected without unbounded state. |
| `server-time` | Implemented | UTC parsing including leap seconds; exposed as `ctx.server_time`. |
| `account-tag` | Implemented | Updates message sender identity and exposes `ctx.account`. |
| `account-notify` | Implemented | Tracks `ACCOUNT`, including logout, and exposes `on_account`. |
| `away-notify` | Implemented | Tracks presence and away text and exposes `on_away`. |
| `chghost` | Implemented | Updates username/hostname and exposes old/new hostmasks. |
| `extended-join` | Implemented | Tracks account and real name from `JOIN`. |
| `invite-notify` | Implemented | Exposes inviter, target, and channel through `on_invite`. |
| `multi-prefix` | Implemented | Parses all advertised membership prefixes in `NAMES`. |
| `userhost-in-names` | Implemented | Parses username and hostname from `NAMES`. |
| `message-tags` / `TAGMSG` | Implemented | Exposes tag-only messages through `on_tagmsg`. |
| SASL PLAIN | Implemented | 400-byte chunking, mechanism discovery, success/failure numerics, secret-safe logging. |
| SASL EXTERNAL | Implemented | TLS client certificate loading and EXTERNAL authentication. |
| Standard replies | Implemented | `FAIL`, `WARN`, and `NOTE` are parsed structurally and logged without assuming a closed reply-code registry. |
| WHOX | Implemented | Uses the `WHOX` ISUPPORT token to initialize account, host, real-name, and away state after joining. |
| `labeled-response`, `echo-message`, multiline | Not implemented | Not requested by default and no semantic processing is provided yet. |
| SCRAM/OAUTH SASL mechanisms | Not implemented | Only PLAIN and EXTERNAL are accepted by configuration. |

## IRC base protocol and ISUPPORT

The core parses the 512-byte IRC message body limit, IRCv3's extended tag
budget, prefixes, all legal final-parameter forms, and UTF-8 without splitting
outgoing code points. `PING`/`PONG` and registration traffic bypass the
rate-limited output queue. Direct CTCP `PING` requests are echoed through a
size-limited `NOTICE`; CTCP `ACTION` is exposed to plugins as an action event.
Direct CTCP `VERSION` and `CLIENTINFO` are supported. The minimal VERSION text
always contains the native NovariusIRC package version. `[bot]`
`ctcp_version_extra` may append plain text but cannot disable or replace the
native identity. The separately maintained internal IRC-core version is not
part of CTCP. Installed release and container artifacts can also carry their
immutable short Git commit and UTC build time. Python and operating-system
details are not exposed.

Connection loss, idle reads, and malformed oversized input trigger a clean
reconnect. The configured retry delay grows to its final value without wrapping
back to the shortest delay, and resets after a connection was established.

`RPL_ISUPPORT` currently drives `CASEMAPPING`, `CHANTYPES`, `PREFIX`,
`CHANMODES`, `STATUSMSG`, `NETWORK`, common length limits, `TARGMAX`, and
`WHOX`. User, channel, membership, topic, channel-mode, account, away, and
hostmask state is updated from JOIN/PART/QUIT/NICK/KICK/MODE/TOPIC, NAMES,
WHO, WHOX, and their relevant numerics. `NAMES` resynchronization removes stale
members while preserving concurrent joins and nick changes.

Unknown commands, numerics, capabilities, tags, and ISUPPORT tokens remain
forward-compatible: they are parsed or retained where useful and otherwise
ignored rather than treated as fatal protocol errors.
