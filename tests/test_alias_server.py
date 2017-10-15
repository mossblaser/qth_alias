import pytest
import json

from mock import Mock
from util import AsyncMock

import qth

import qth_alias
from qth_alias import has_cycle, AliasServer


@pytest.fixture()
def mock_client(event_loop, monkeypatch):
    mock_client = Mock()

    monkeypatch.setattr(qth, "Client", Mock(return_value=mock_client))

    mock_client.register = AsyncMock(event_loop)
    mock_client.unregister = AsyncMock(event_loop)

    mock_client.set_property = AsyncMock(event_loop)
    mock_client.watch_property = AsyncMock(event_loop)
    mock_client.unwatch_property = AsyncMock(event_loop)
    mock_client.delete_property = AsyncMock(event_loop)

    mock_client.send_event = AsyncMock(event_loop)
    mock_client.watch_event = AsyncMock(event_loop)
    mock_client.unwatch_event = AsyncMock(event_loop)

    return mock_client


def test_has_cycle():
    assert has_cycle({}) is None
    assert has_cycle({"a": "b"}) is None
    assert has_cycle({"a": "a"}) == ["a", "a"]
    assert has_cycle({"a": "b", "b": "c"}) is None
    assert has_cycle({"a": "b", "b": "a"}) in (["a", "b", "a"],
                                               ["b", "a", "b"])
    assert has_cycle({"a": "b", "b": "b"}) in (["a", "b", "b"], ["b", "b"])


@pytest.mark.asyncio
async def test_async_init(mock_client, event_loop):
    s = AliasServer(loop=event_loop)
    await s.async_init()

    # Check registrations
    assert {call[1][0]: call[1][1]
            for call in mock_client.register.mock_calls} == {
        "meta/alias/add": "EVENT-N:1",
        "meta/alias/remove": "EVENT-N:1",
        "meta/alias/aliases": "PROPERTY-1:N",
        "meta/alias/error": "EVENT-1:N",
    }

    # Check watches
    assert mock_client.watch_event.call_count == 2
    mock_client.watch_event.assert_any_call("meta/alias/add", s._on_add)
    mock_client.watch_event.assert_any_call("meta/alias/remove", s._on_remove)
    mock_client.watch_property.assert_called_once_with(
        "meta/alias/aliases", s._on_change)


@pytest.mark.asyncio
@pytest.mark.parametrize("arg", [
    # Wrong type entirely
    None,
    123,
    "Fail",
    # Invalid short-form
    [],
    ["nope"],
    ["nopety", "nope", "nope"],
    # Missing target/alias in long form
    {},
    {"target": "foo"},
    {"alias": "bar"},
    # Unexpected value in long form
    {"target": "foo", "alias": "bar", "what?": "nope"},
])
async def test_on_add_invalid_forms(mock_client, event_loop, arg):
    s = AliasServer(loop=event_loop)
    await s.async_init()

    await s._on_add("meta/alias/add", arg)

    assert s._aliases == {}

    assert mock_client.send_event.call_count == 1
    assert mock_client.send_event.mock_calls[0][1][0] == "meta/alias/error"


@pytest.mark.asyncio
@pytest.mark.parametrize("value,expected", [
    # Shortform
    (["foo/target", "foo/alias"], {
        "target": "foo/target",
        "alias": "foo/alias",
        "transform": None,
        "inverse": None,
        "description": "Alias of foo/target.",
    }),
    # Longform: subset of values specified
    ({
        "target": "foo/target",
        "alias": "foo/alias",
    }, {
        "target": "foo/target",
        "alias": "foo/alias",
        "transform": None,
        "inverse": None,
        "description": "Alias of foo/target.",
    }),
    # Longform: fully specified
    ({
        "target": "foo/target",
        "alias": "foo/alias",
        "transform": "value / 63.0",
        "inverse": "int(value * 63)",
        "description": "A custom alias.",
    }, {
        "target": "foo/target",
        "alias": "foo/alias",
        "transform": "value / 63.0",
        "inverse": "int(value * 63)",
        "description": "A custom alias.",
    }),
])
async def test_on_add_long_form(mock_client, event_loop, value, expected):
    s = AliasServer(loop=event_loop)
    await s.async_init()

    s._update_aliases = AsyncMock(event_loop)

    # Check defaults
    await s._on_add("meta/alias/add", value)

    s._update_aliases.assert_called_once_with({"foo/alias": expected})


@pytest.mark.asyncio
async def test_update_aliases(mock_client, event_loop, monkeypatch):
    # Mock out the Alias objects for ease
    alias_objects = []

    def _Alias(alias_server, **description):
        alias = Mock()
        alias.async_init = AsyncMock(event_loop)
        alias.delete = AsyncMock(event_loop)
        alias.json = description

        alias_objects.append(alias)
        return alias
    Alias = Mock(side_effect=_Alias)
    monkeypatch.setattr(qth_alias, "Alias", Alias)

    s = AliasServer(loop=event_loop)
    await s.async_init()

    # Staying empty should result in no change
    assert s._aliases == {}
    await s._update_aliases({})
    assert s._aliases == {}
    assert Alias.call_count == 0
    assert mock_client.set_property.call_count == 1

    # Adding an alias should result in a change
    await s._update_aliases({
        "foo/alias": {
            "target": "foo/target",
            "alias": "foo/alias",
            "transform": None,
            "inverse": None,
            "description": "A test alias.",
        },
    })
    assert Alias.call_count == 1
    alias_foo_alias = alias_objects[0]
    assert s._aliases == {"foo/alias": alias_foo_alias}
    alias_foo_alias.async_init.assert_called_once_with()
    assert mock_client.set_property.call_count == 2
    mock_client.set_property.assert_called_with("meta/alias/aliases", {
        "foo/alias": {
            "target": "foo/target",
            "alias": "foo/alias",
            "transform": None,
            "inverse": None,
            "description": "A test alias.",
        },
    })

    # Doing it again should do nothing...
    await s._update_aliases({
        "foo/alias": {
            "target": "foo/target",
            "alias": "foo/alias",
            "transform": None,
            "inverse": None,
            "description": "A test alias.",
        },
    })
    assert Alias.call_count == 1
    assert mock_client.set_property.call_count == 2

    # Adding a second alias should result in a change again...
    await s._update_aliases({
        "foo/alias": {
            "target": "foo/target",
            "alias": "foo/alias",
            "transform": None,
            "inverse": None,
            "description": "A test alias.",
        },
        "foo/alias2": {
            "target": "foo/target",
            "alias": "foo/alias2",
            "transform": None,
            "inverse": None,
            "description": "A test alias.",
        },
    })
    assert Alias.call_count == 2
    alias_foo_alias2 = alias_objects[1]
    assert s._aliases == {"foo/alias": alias_foo_alias,
                          "foo/alias2": alias_foo_alias2}
    alias_foo_alias2.async_init.assert_called_once_with()
    assert mock_client.set_property.call_count == 3
    mock_client.set_property.assert_called_with("meta/alias/aliases", {
        "foo/alias": {
            "target": "foo/target",
            "alias": "foo/alias",
            "transform": None,
            "inverse": None,
            "description": "A test alias.",
        },
        "foo/alias2": {
            "target": "foo/target",
            "alias": "foo/alias2",
            "transform": None,
            "inverse": None,
            "description": "A test alias.",
        },
    })

    # Removing an alias should result in a change...
    await s._update_aliases({
        "foo/alias2": {
            "target": "foo/target",
            "alias": "foo/alias2",
            "transform": None,
            "inverse": None,
            "description": "A test alias.",
        },
    })
    assert Alias.call_count == 2
    alias_foo_alias.delete.assert_called_once_with()
    assert s._aliases == {"foo/alias2": alias_foo_alias2}
    assert mock_client.set_property.call_count == 4
    mock_client.set_property.assert_called_with("meta/alias/aliases", {
        "foo/alias2": {
            "target": "foo/target",
            "alias": "foo/alias2",
            "transform": None,
            "inverse": None,
            "description": "A test alias.",
        },
    })

    # Changing an alias should result in a change...
    await s._update_aliases({
        "foo/alias2": {
            "target": "foo/target",
            "alias": "foo/alias2",
            "transform": "value / 63.0",
            "inverse": "int(value * 63)",
            "description": "A test alias.",
        },
    })
    assert Alias.call_count == 3
    alias_foo_alias2.delete.assert_called_once_with()
    alias_foo_alias2_v2 = alias_objects[2]
    alias_foo_alias2_v2.async_init.assert_called_once_with()
    assert s._aliases == {"foo/alias2": alias_foo_alias2_v2}
    assert mock_client.set_property.call_count == 5
    mock_client.set_property.assert_called_with("meta/alias/aliases", {
        "foo/alias2": {
            "target": "foo/target",
            "alias": "foo/alias2",
            "transform": "value / 63.0",
            "inverse": "int(value * 63)",
            "description": "A test alias.",
        },
    })

    # Inserting a cycle should result in an error and no change...
    await s._update_aliases({
        "foo/target": {
            "target": "foo/alias2",
            "alias": "foo/target",
            "transform": None,
            "inverse": None,
            "description": "A test alias.",
        },
        "foo/alias2": {
            "target": "foo/target",
            "alias": "foo/alias2",
            "transform": "value / 63.0",
            "inverse": "int(value * 63)",
            "description": "A test alias.",
        },
    })
    assert mock_client.send_event.call_count == 1
    assert mock_client.send_event.mock_calls[0][1][0] == "meta/alias/error"
    assert Alias.call_count == 3
    assert s._aliases == {"foo/alias2": alias_foo_alias2_v2}
    assert mock_client.set_property.call_count == 6
    mock_client.set_property.assert_called_with("meta/alias/aliases", {
        "foo/alias2": {
            "target": "foo/target",
            "alias": "foo/alias2",
            "transform": "value / 63.0",
            "inverse": "int(value * 63)",
            "description": "A test alias.",
        },
    })


@pytest.mark.asyncio
async def test_on_remove(mock_client, event_loop):
    s = AliasServer(loop=event_loop)
    await s.async_init()

    await s._on_add("meta/alias/add", ["foo/target", "foo/alias"])
    assert set(s._aliases.keys()) == set(["foo/alias"])
    await s._on_remove("meta/alias/remove", "foo/alias")
    assert s._aliases == {}


@pytest.mark.asyncio
async def test_on_change(mock_client, event_loop):
    s = AliasServer(loop=event_loop)
    await s.async_init()

    await s._on_add("meta/alias/add", ["foo/target", "foo/alias"])
    assert s._aliases != {}
    await s._on_change("meta/alias/aliases", {})
    assert s._aliases == {}


@pytest.mark.asyncio
async def test_file_cache_dev_null(mock_client, event_loop):
    s = AliasServer(cache_file="/dev/null", loop=event_loop)
    await s.async_init()
    assert s._aliases == {}


@pytest.mark.asyncio
async def test_file_cache(mock_client, event_loop, tmpdir):
    cache_file = tmpdir.join("cache.json")
    cache_file.write(json.dumps({
        "foo/alias": {
            "target": "foo/target",
            "alias": "foo/alias",
            "transform": None,
            "inverse": None,
            "description": "A test...",
        }
    }))

    s = AliasServer(cache_file=str(cache_file), loop=event_loop)
    await s.async_init()

    # Initial contents should be loaded and sent to Qth
    assert mock_client.set_property.call_count == 1
    assert mock_client.set_property.mock_calls[0][1][0] == "meta/alias/aliases"
    await s._on_change(*mock_client.set_property.mock_calls[0][1])
    assert s._aliases_json == {
        "foo/alias": {
            "target": "foo/target",
            "alias": "foo/alias",
            "transform": None,
            "inverse": None,
            "description": "A test...",
        }
    }

    # Upon adding a new entry this should be saved
    await s._on_add("meta/alias/add", ["bar/target", "bar/alias"])
    assert json.loads(cache_file.read()) == {
        "foo/alias": {
            "target": "foo/target",
            "alias": "foo/alias",
            "transform": None,
            "inverse": None,
            "description": "A test...",
        },
        "bar/alias": {
            "target": "bar/target",
            "alias": "bar/alias",
            "transform": None,
            "inverse": None,
            "description": "Alias of bar/target.",
        },
    }


@pytest.mark.asyncio
async def test_close(mock_client, event_loop):
    s = AliasServer(loop=event_loop)
    await s.async_init()
    await s._on_add("meta/alias/add", ["foo/target", "foo/alias"])
    await s._aliases["foo/alias"]._on_target_registration_changed(
        "foo/target",
        [{
            "behaviour": "PROPERTY-1:N",
            "delete_on_unregister": True,
        }])

    await s.close()

    mock_client.unregister.assert_any_call("meta/alias/add")
    mock_client.unregister.assert_any_call("meta/alias/remove")
    mock_client.unregister.assert_any_call("meta/alias/aliases")
    mock_client.unregister.assert_any_call("meta/alias/error")

    mock_client.delete_property.assert_any_call("meta/alias/aliases")

    mock_client.delete_property.assert_any_call("foo/alias")
