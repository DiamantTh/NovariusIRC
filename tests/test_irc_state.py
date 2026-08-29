from __future__ import annotations

from novariusirc.core.protocol import IRCFeatures
from novariusirc.core.state import IRCState


def test_isupport_prefix_chanmodes_statusmsg_and_limits() -> None:
    features = IRCFeatures()
    features.update(
        [
            "Bot",
            "PREFIX=(qaohv)~&@%+",
            "CHANMODES=beI,kfL,lj,psmntirRcOAQKVCuzNSMTGZ",
            "STATUSMSG=@+",
            "NICKLEN=30",
            "TARGMAX=PRIVMSG:4,WHOIS:",
        ]
    )

    assert features.mode_for_prefix("~") == "q"
    assert features.prefix_for_mode("h") == "%"
    assert features.mode_takes_parameter("b", adding=False)
    assert features.mode_takes_parameter("l", adding=True)
    assert not features.mode_takes_parameter("l", adding=False)
    assert features.channel_from_target("@+#channel") == "#channel"
    assert features.limits["NICKLEN"] == 30
    assert features.target_limits == {"PRIVMSG": 4, "WHOIS": None}

    features.update(["Bot", "-TARGMAX"])
    assert features.target_limits == {}


def test_membership_state_tracks_names_modes_and_identity_changes() -> None:
    features = IRCFeatures()
    features.update(["Bot", "PREFIX=(qaohv)~&@%+", "CASEMAPPING=rfc1459"])
    state = IRCState(features)

    state.join(
        "Nick[!user@old.host",
        "#Room",
        account="Alice",
        realname="Alice Example",
    )
    state.add_names("#Room", "@+Nick{!user@old.host Other!other@example.test")
    state.finish_names("#Room")

    channel = state.get_channel("#room")
    assert channel is not None
    membership = channel.members[features.casefold("nick[")]
    assert membership.modes == {"o", "v"}
    assert membership.user.account == "Alice"
    assert channel.names_complete

    state.set_membership_mode("#ROOM", "NICK{", "v", False)
    state.set_account("Nick[!user@old.host", "Bob")
    state.set_away("Nick[!user@old.host", "gone")
    user = state.change_host("Nick[!user@old.host", "newuser", "new.host")
    state.rename("Nick[", "Renamed", user.hostmask)

    renamed = state.get_user("renamed")
    assert renamed is not None
    assert renamed.hostmask == "Renamed!newuser@new.host"
    assert renamed.account == "Bob"
    assert renamed.away == "gone"
    assert renamed.is_away is True
    assert state.channels_for("RENAMED") == ["#Room"]
    assert channel.members[features.casefold("renamed")].modes == {"o"}

    state.set_away_status("Renamed", False)
    assert renamed.away is None
    assert renamed.is_away is False


def test_state_reindexes_when_server_changes_casemapping() -> None:
    features = IRCFeatures(casemapping="ascii")
    state = IRCState(features)
    state.join("Nick[!u@h", "#Test")
    assert state.get_user("nick{") is None

    features.casemapping = "rfc1459"
    state.reindex()
    assert state.get_user("nick{") is not None


def test_names_resync_removes_stale_members_without_losing_concurrent_join() -> None:
    features = IRCFeatures()
    state = IRCState(features)
    state.add_names("#test", "Old Current")
    state.finish_names("#test")

    state.add_names("#test", "Current")
    state.join("New!user@host", "#test")
    state.rename("New", "Renamed", "New!user@host")
    state.finish_names("#test")

    channel = state.get_channel("#test")
    assert channel is not None
    assert set(channel.members) == {
        features.casefold("Current"),
        features.casefold("Renamed"),
    }
    assert state.get_user("Old") is None
    assert channel.names_complete
    assert not channel.names_in_progress


def test_names_snapshot_ignores_stale_entries_after_part_quit_and_nick() -> None:
    features = IRCFeatures()
    state = IRCState(features)
    state.add_names("#test", "Old Quitter Rename")
    state.finish_names("#test")

    state.add_names("#test", "Old Quitter Rename")
    state.part("Old", "#test")
    state.quit("Quitter")
    state.rename("Rename", "Renamed")
    state.join("Fresh!user@host", "#test")
    # These entries belong to an older NAMES view and arrive after the events.
    state.add_names("#test", "Old Quitter Rename")
    state.finish_names("#test")

    channel = state.get_channel("#test")
    assert channel is not None
    assert set(channel.members) == {
        features.casefold("Renamed"),
        features.casefold("Fresh"),
    }
    assert not channel.names_removed


def test_empty_names_snapshot_removes_all_stale_members() -> None:
    features = IRCFeatures()
    state = IRCState(features)
    state.add_names("#test", "One Two")
    state.finish_names("#test")
    state.add_names("#test", "")
    state.finish_names("#test")

    channel = state.get_channel("#test")
    assert channel is not None
    assert not channel.members
    assert not state.users


def test_feature_changes_prune_membership_modes_and_clear_channel_modes() -> None:
    features = IRCFeatures()
    features.update(["Bot", "PREFIX=(qaohv)~&@%+"])
    state = IRCState(features)
    membership = state.join("Nick!user@host", "#test")
    membership.modes.update({"q", "o", "v"})
    channel = state.get_channel("#test")
    assert channel is not None
    channel.list_modes["b"] = {"*!*@bad.host"}
    channel.parameter_modes["k"] = "secret"
    channel.flag_modes.add("n")

    features.update(["Bot", "PREFIX=(ov)@+"])
    state.prune_membership_modes()
    state.clear_channel_modes()

    assert membership.modes == {"o", "v"}
    assert not channel.list_modes
    assert not channel.parameter_modes
    assert not channel.flag_modes


def test_casemapping_reindexes_names_tombstones_during_snapshot() -> None:
    features = IRCFeatures(casemapping="ascii")
    state = IRCState(features)
    state.add_names("#test", "Nick[")
    state.finish_names("#test")
    state.add_names("#test", "Nick[")
    state.part("Nick[", "#test")

    features.casemapping = "rfc1459"
    state.reindex()
    state.add_names("#test", "Nick{")
    state.finish_names("#test")

    channel = state.get_channel("#test")
    assert channel is not None
    assert not channel.members
