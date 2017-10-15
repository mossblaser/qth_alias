import pytest
import asyncio

from mock import Mock

from util import AsyncMock

import qth

from qth_alias.alias import Alias


@pytest.fixture()
def mock_client(event_loop):
    mock_client = Mock()

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


@pytest.fixture()
def mock_ls(event_loop):
    mock_ls = Mock()

    mock_ls.watch_path = AsyncMock(event_loop)
    mock_ls.unwatch_path = AsyncMock(event_loop)

    return mock_ls


@pytest.fixture()
def mock_alias_server(mock_client, mock_ls, event_loop):
    mock_alias_server = Mock()

    mock_alias_server._loop = event_loop
    mock_alias_server._client = mock_client
    mock_alias_server._ls = mock_ls

    return mock_alias_server


@pytest.mark.asyncio
async def test_init(mock_alias_server, mock_ls):
    a = Alias(mock_alias_server, "foo/target", "foo/alias")
    await a.async_init()
    mock_ls.watch_path.assert_called_once_with(
        "foo/target", a._on_target_registration_changed)


@pytest.mark.asyncio
async def test_json(mock_alias_server, mock_ls):
    a = Alias(mock_alias_server, "foo/target", "foo/alias",
              "value / 63.0", "int(value * 63)",
              "A test alias.")
    await a.async_init()

    assert a.json == {
        "target": "foo/target",
        "alias": "foo/alias",
        "transform": "value / 63.0",
        "inverse": "int(value * 63)",
        "description": "A test alias.",
    }


@pytest.mark.asyncio
async def test_eval_transform(mock_alias_server):
    a = Alias(mock_alias_server, "foo/target", "foo/alias")

    assert a._eval_transform(None, 123) == 123
    assert a._eval_transform(None, qth.Empty) is qth.Empty
    assert mock_alias_server._error_sync.call_count == 0

    assert a._eval_transform("False", qth.Empty) is qth.Empty
    assert a._eval_transform("False", 123) is False
    assert mock_alias_server._error_sync.call_count == 0

    assert a._eval_transform("math.floor(value)", qth.Empty) is qth.Empty
    assert a._eval_transform("math.floor(value)", 1.23) == 1
    assert mock_alias_server._error_sync.call_count == 0

    assert a._eval_transform("math.floor(value)", "bad") == "bad"
    assert mock_alias_server._error_sync.call_count == 1


@pytest.mark.asyncio
async def test_transform_inverse(mock_alias_server):
    a = Alias(mock_alias_server, "foo/target", "foo/alias",
              "value / 63.0", "int(value * 63)")
    assert a._transform(0) == 0.0
    assert a._transform(63) == 1.0

    assert a._inverse(0.0) == 0
    assert a._inverse(1.0) == 63


@pytest.mark.asyncio
async def test_on_target_registration_changed(mock_alias_server, mock_client):
    a = Alias(mock_alias_server, "foo/target", "foo/alias",
              "value / 63.0", "int(value * 63)",
              "Alias description.")
    await a.async_init()

    # Initially should have no registrations
    assert not a._watching_property
    assert not a._watching_event
    assert a._target_registration is None
    assert a._alias_registration is None
    assert mock_client.watch_property.call_count == 0
    assert mock_client.watch_event.call_count == 0
    assert mock_client.unwatch_property.call_count == 0
    assert mock_client.unwatch_event.call_count == 0
    assert mock_client.register.call_count == 0
    assert mock_client.unregister.call_count == 0

    # Repeat of no-registration should do nothing
    await a._on_target_registration_changed("foo/target", None)
    assert not a._watching_property
    assert not a._watching_event
    assert a._target_registration is None
    assert a._alias_registration is None
    assert mock_client.watch_property.call_count == 0
    assert mock_client.watch_event.call_count == 0
    assert mock_client.unwatch_property.call_count == 0
    assert mock_client.unwatch_event.call_count == 0
    assert mock_client.register.call_count == 0
    assert mock_client.unregister.call_count == 0

    # Test singular registration with on_unregister requiring conversion.
    await a._on_target_registration_changed("foo/target", [{
        "behaviour": "EVENT-1:N",
        "description": "Underlying description",
        "on_unregister": 63,
    }])

    assert not a._watching_property
    assert a._watching_event

    assert a._target_registration == {
        "behaviour": "EVENT-1:N",
        "description": "Underlying description",
        "on_unregister": 63,
    }
    assert a._alias_registration == {
        "behaviour": "EVENT-1:N",
        "description": "Alias description.",
        "on_unregister": 1.0,
    }

    assert mock_client.watch_property.call_count == 0
    assert mock_client.watch_event.call_count == 2
    assert mock_client.unwatch_property.call_count == 0
    assert mock_client.unwatch_event.call_count == 0
    mock_client.watch_event.assert_any_call("foo/target", a._on_target_sent)
    mock_client.watch_event.assert_any_call("foo/alias", a._on_alias_sent)

    mock_client.register.assert_called_once_with(
        "foo/alias", behaviour="EVENT-1:N", description="Alias description.",
        on_unregister=1.0)
    assert mock_client.unregister.call_count == 0

    # Test repeated registration: no change
    await a._on_target_registration_changed("foo/target", [{
        "behaviour": "EVENT-1:N",
        "description": "Underlying description",
        "on_unregister": 63,
    }])

    assert not a._watching_property
    assert a._watching_event

    assert a._target_registration == {
        "behaviour": "EVENT-1:N",
        "description": "Underlying description",
        "on_unregister": 63,
    }
    assert a._alias_registration == {
        "behaviour": "EVENT-1:N",
        "description": "Alias description.",
        "on_unregister": 1.0,
    }

    assert mock_client.watch_property.call_count == 0
    assert mock_client.watch_event.call_count == 2
    assert mock_client.unwatch_property.call_count == 0
    assert mock_client.unwatch_event.call_count == 0

    assert mock_client.register.call_count == 1
    assert mock_client.unregister.call_count == 0

    # Test same type registration: only changes registration
    await a._on_target_registration_changed("foo/target", [{
        "behaviour": "EVENT-N:1",
        "description": "Underlying description changed.",
        "on_unregister": 0,
    }])

    assert not a._watching_property
    assert a._watching_event

    assert a._target_registration == {
        "behaviour": "EVENT-N:1",
        "description": "Underlying description changed.",
        "on_unregister": 0,
    }
    assert a._alias_registration == {
        "behaviour": "EVENT-N:1",
        "description": "Alias description.",
        "on_unregister": 0.0,
    }

    assert mock_client.watch_property.call_count == 0
    assert mock_client.watch_event.call_count == 2
    assert mock_client.unwatch_property.call_count == 0
    assert mock_client.unwatch_event.call_count == 0

    assert mock_client.register.call_count == 2
    mock_client.register.assert_called_with(
        "foo/alias", behaviour="EVENT-N:1", description="Alias description.",
        on_unregister=0.0)
    assert mock_client.unregister.call_count == 0

    # Change type should result in registration changes
    await a._on_target_registration_changed("foo/target", [{
        "behaviour": "PROPERTY-N:1",
        "description": "Underlying description changed.",
        "delete_on_unregister": True,
    }])

    assert a._watching_property
    assert not a._watching_event

    assert a._target_registration == {
        "behaviour": "PROPERTY-N:1",
        "description": "Underlying description changed.",
        "delete_on_unregister": True,
    }
    assert a._alias_registration == {
        "behaviour": "PROPERTY-N:1",
        "description": "Alias description.",
        "delete_on_unregister": True,
    }

    assert mock_client.watch_property.call_count == 2
    assert mock_client.watch_event.call_count == 2
    assert mock_client.unwatch_property.call_count == 0
    assert mock_client.unwatch_event.call_count == 2
    mock_client.watch_property.assert_any_call("foo/alias", a._on_alias_set)
    mock_client.watch_property.assert_any_call("foo/target", a._on_target_set)
    mock_client.unwatch_event.assert_any_call("foo/alias", a._on_alias_sent)
    mock_client.unwatch_event.assert_any_call("foo/target", a._on_target_sent)

    assert mock_client.register.call_count == 3
    mock_client.register.assert_called_with(
        "foo/alias",
        behaviour="PROPERTY-N:1",
        description="Alias description.",
        delete_on_unregister=True)
    assert mock_client.unregister.call_count == 0

    # ...and back
    await a._on_target_registration_changed("foo/target", [{
        "behaviour": "EVENT-N:1",
        "description": "Underlying description changed.",
    }])

    assert not a._watching_property
    assert a._watching_event

    assert a._target_registration == {
        "behaviour": "EVENT-N:1",
        "description": "Underlying description changed.",
    }
    assert a._alias_registration == {
        "behaviour": "EVENT-N:1",
        "description": "Alias description.",
    }

    assert mock_client.watch_property.call_count == 2
    assert mock_client.watch_event.call_count == 4
    assert mock_client.unwatch_property.call_count == 2
    assert mock_client.unwatch_event.call_count == 2
    mock_client.watch_event.assert_any_call("foo/alias", a._on_alias_sent)
    mock_client.watch_event.assert_any_call("foo/target", a._on_target_sent)
    mock_client.unwatch_property.assert_any_call("foo/alias", a._on_alias_set)
    mock_client.unwatch_property.assert_any_call(
        "foo/target", a._on_target_set)

    assert mock_client.register.call_count == 4
    mock_client.register.assert_called_with(
        "foo/alias", behaviour="EVENT-N:1", description="Alias description.")
    assert mock_client.unregister.call_count == 0

    # Removal should completely unregister but retain the most recent watch
    await a._on_target_registration_changed("foo/target", None)

    assert not a._watching_property
    assert a._watching_event

    assert a._target_registration is None
    assert a._alias_registration is None

    assert mock_client.watch_property.call_count == 2
    assert mock_client.watch_event.call_count == 4
    assert mock_client.unwatch_property.call_count == 2
    assert mock_client.unwatch_event.call_count == 2

    assert mock_client.register.call_count == 4
    mock_client.unregister.assert_called_once_with("foo/alias")


@pytest.mark.asyncio
async def test_multiple_registration_changes(mock_alias_server, mock_client,
                                             event_loop):
    a = Alias(mock_alias_server, "foo/target", "foo/alias",
              "value / 63.0", "int(value * 63)",
              "Alias description.")
    await a.async_init()

    # If many registration changes occur, this should only turn into a minimum
    # number of calls which should finally end with a consistent state.

    # Make the 'watch_property' call block to simulate calls taking time
    watch_property_event = asyncio.Event(loop=event_loop)

    async def watch_property_side_effect(*_, **__):
        await watch_property_event.wait()
    mock_client.watch_property = Mock(side_effect=watch_property_side_effect)

    # Send a series of conflicting registrations
    todo = []
    for _ in range(10):
        for behaviour in ["PROPERTY-1:N", "EVENT-N:1"]:
            todo.append(a._on_target_registration_changed(
                "foo/target", [{
                    "behaviour": behaviour,
                    "description": "Target description",
                }]))

    # Make sure they all get started...
    await asyncio.sleep(0.1, loop=event_loop)

    # let them all proceed
    watch_property_event.set()
    await asyncio.wait(todo, loop=event_loop)

    # Make sure the final registration settles on one value
    assert a._watching_property != a._watching_event

    # Make sure not every call resulted in a change
    assert mock_client.register.call_count < 20
    assert mock_client.unregister.call_count == 0

    # And that the watches we're left with are consistent
    if a._watching_property:
        assert mock_client.watch_property.call_count > \
            mock_client.unwatch_property.call_count
        assert mock_client.watch_event.call_count == \
            mock_client.unwatch_event.call_count
    else:
        assert mock_client.watch_event.call_count > \
            mock_client.unwatch_event.call_count
        assert mock_client.watch_property.call_count == \
            mock_client.unwatch_property.call_count


@pytest.mark.asyncio
async def test_ambiguous_registration(mock_alias_server, mock_client):
    a = Alias(mock_alias_server, "foo/target", "foo/alias",
              "value / 63.0", "int(value * 63)",
              "Alias description.")
    await a.async_init()

    # Check to see if when sent an ambiguous registration (e.g. a path which is
    # both a directory and a non-directory) we choose the first non-directory.
    await a._on_target_registration_changed("foo/target", [
        {"behaviour": "DIRECTORY"},
        {
            "behaviour": "PROPERTY-N:1",
            "description": "A property, really.",
        },
        {
            "behaviour": "EVENT-N:1",
            "description": "An event.",
        },
    ])

    assert a._target_registration == {
        "behaviour": "PROPERTY-N:1",
        "description": "A property, really.",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("is_property,on_unregister,delete_on_unregister", [
    (True, None, None),
    (True, 123, None),
    (True, None, True),
    (True, None, False),
    (False, None, None),
    (False, 123, None),
])
async def test_delete(mock_alias_server, mock_client,
                      is_property, on_unregister, delete_on_unregister):
    a = Alias(mock_alias_server, "foo/target", "foo/alias")
    await a.async_init()

    reg = {
        "behaviour": "PROPERTY-N:1" if is_property else "EVENT-N:1",
        "description": "A property.",
    }
    if on_unregister is not None:
        reg["on_unregister"] = on_unregister
    if delete_on_unregister is not None:
        reg["delete_on_unregister"] = delete_on_unregister
    await a._on_target_registration_changed("foo/target", [reg])

    await a.delete()

    # Unregistered
    mock_client.unregister.assert_called_with("foo/alias")

    # Unwatched
    if is_property:
        mock_client.unwatch_property.assert_any_call(
            "foo/target", a._on_target_set)
        mock_client.unwatch_property.assert_any_call(
            "foo/alias", a._on_alias_set)
    else:
        mock_client.unwatch_event.assert_any_call(
            "foo/target", a._on_target_sent)
        mock_client.unwatch_event.assert_any_call(
            "foo/alias", a._on_alias_sent)

    # on_unregister sent
    if on_unregister is not None:
        if is_property:
            mock_client.set_property.assert_called_once_with(
                "foo/alias", 123)
            assert mock_client.send_event.call_count == 0
        else:
            mock_client.send_event.assert_called_once_with(
                "foo/alias", 123)
            assert mock_client.set_property.call_count == 0
    else:
        assert mock_client.set_property.call_count == 0
        assert mock_client.send_event.call_count == 0

    # delete_on_unregister
    if delete_on_unregister is True:
        mock_client.delete_property.assert_called_once_with(
            "foo/alias")
    else:
        assert mock_client.delete_property.call_count == 0
