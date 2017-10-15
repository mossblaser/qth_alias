import pytest

from mock import Mock

from util import AsyncMock

import qth

from qth_alias.ls import \
    Ls, \
    path_to_subdirectories, \
    listing_has_subdir, \
    get_path_listing


def test_path_to_subdirectories():
    assert list(path_to_subdirectories("")) == [""]
    assert list(path_to_subdirectories("foo")) == [""]
    assert list(path_to_subdirectories("foo/bar")) == ["", "foo/"]
    assert list(path_to_subdirectories("foo/bar/baz")) == \
        ["", "foo/", "foo/bar/"]


def test_listing_has_subdir():
    assert not listing_has_subdir({}, "foo")
    assert not listing_has_subdir(
        {"foo": [{"behaviour": "PROPERTY-N:1"}]}, "foo")
    assert listing_has_subdir({"foo": [{"behaviour": "DIRECTORY"}]}, "foo")
    assert listing_has_subdir({"foo": [
        {"behaviour": "PROPERTY-1:N"},
        {"behaviour": "DIRECTORY"},
    ]}, "foo")


def test_get_path_listing():
    assert get_path_listing({}, "qux") is None

    ls_tree = {
        "": {
            "foo": [{"behaviour": "PROPERTY-N:1"},
                    {"behaviour": "DIRECTORY"}],
            "baz": [{"behaviour": "PROPERTY-1:N"}],
        },
        "foo/": {
            "bar": [{"behaviour": "EVENT-1:N"}],
        },
        "qux/": {
            "quo": [{"behaviour": "EVENT-N:1"}],
        },
    }

    assert get_path_listing(ls_tree, "qux") is None

    assert get_path_listing(ls_tree, "baz") == [{"behaviour": "PROPERTY-1:N"}]
    assert get_path_listing(ls_tree, "foo") == [{"behaviour": "PROPERTY-N:1"},
                                                {"behaviour": "DIRECTORY"}]
    assert get_path_listing(ls_tree, "foo/bar") == [{"behaviour": "EVENT-1:N"}]

    # The 'qux/' directory is not listed in the top-level so it shouldn't be
    # returned, despite having a tree listing...
    assert get_path_listing(ls_tree, "qux/quo") is None


@pytest.mark.asyncio
async def test_watch_and_unwatch(event_loop):
    client = Mock()
    client.watch_property = AsyncMock(event_loop)
    client.unwatch_property = AsyncMock(event_loop)
    ls = Ls(client, event_loop)

    foo_bar_cb = AsyncMock(event_loop)
    await ls.watch_path("foo/bar", foo_bar_cb)

    # Should call straight away with None
    foo_bar_cb.assert_called_once_with("foo/bar", None)

    # Should have registered the callback and prepared a None 'last value'
    assert ls._callbacks == {"foo/bar": [foo_bar_cb]}
    assert ls._last_path_value == {"foo/bar": None}

    # Should have setup watches for meta/ls/ and meta/ls/foo/
    assert client.watch_property.call_count == 2
    client.watch_property.assert_any_call(
        "meta/ls/", ls._on_ls_tree_property_changed)
    client.watch_property.assert_any_call(
        "meta/ls/foo/", ls._on_ls_tree_property_changed)

    # Watching a different property should result in a minimal set of path
    # watches being added
    foo_bar_baz_cb = AsyncMock(event_loop)
    await ls.watch_path("foo/bar/baz", foo_bar_baz_cb)

    foo_bar_baz_cb.assert_called_once_with("foo/bar/baz", None)
    assert ls._callbacks == {"foo/bar": [foo_bar_cb],
                             "foo/bar/baz": [foo_bar_baz_cb]}
    assert ls._last_path_value == {"foo/bar": None,
                                   "foo/bar/baz": None}

    # Should have setup only one extra watch for meta/ls/foo/bar/
    assert client.watch_property.call_count == 3
    client.watch_property.assert_called_with(
        "meta/ls/foo/bar/", ls._on_ls_tree_property_changed)

    # Watching a property a second time should add a callback but trigger no
    # new tree watches.
    foo_bar_baz_cb2 = AsyncMock(event_loop)
    await ls.watch_path("foo/bar/baz", foo_bar_baz_cb2)

    foo_bar_baz_cb.assert_called_once_with("foo/bar/baz", None)
    foo_bar_baz_cb2.assert_called_once_with("foo/bar/baz", None)
    assert ls._callbacks == {"foo/bar": [foo_bar_cb],
                             "foo/bar/baz": [foo_bar_baz_cb, foo_bar_baz_cb2]}
    assert ls._last_path_value == {"foo/bar": None,
                                   "foo/bar/baz": None}
    assert client.watch_property.call_count == 3

    # Unwatching a doubly-watched property should result in no tree changes
    await ls.unwatch_path("foo/bar/baz", foo_bar_baz_cb)
    assert foo_bar_baz_cb.call_count == 1
    assert ls._callbacks == {"foo/bar": [foo_bar_cb],
                             "foo/bar/baz": [foo_bar_baz_cb2]}
    assert ls._last_path_value == {"foo/bar": None,
                                   "foo/bar/baz": None}
    assert client.watch_property.call_count == 3
    assert client.unwatch_property.call_count == 0

    # Unwatching a property should unwatch only the tree parts it nolonger
    # needs
    await ls.unwatch_path("foo/bar/baz", foo_bar_baz_cb2)
    assert foo_bar_baz_cb2.call_count == 1
    assert ls._callbacks == {"foo/bar": [foo_bar_cb]}
    assert ls._last_path_value == {"foo/bar": None}
    assert client.watch_property.call_count == 3
    assert client.unwatch_property.call_count == 1
    client.unwatch_property.assert_any_call(
        "meta/ls/foo/bar/", ls._on_ls_tree_property_changed)

    # Unwatching the remaining property should take us back where we started
    await ls.unwatch_path("foo/bar", foo_bar_cb)
    assert foo_bar_cb.call_count == 1
    assert ls._callbacks == {}
    assert ls._last_path_value == {}
    assert client.watch_property.call_count == 3
    assert client.unwatch_property.call_count == 3
    client.unwatch_property.assert_any_call(
        "meta/ls/", ls._on_ls_tree_property_changed)
    client.unwatch_property.assert_any_call(
        "meta/ls/foo/", ls._on_ls_tree_property_changed)


@pytest.mark.asyncio
async def test_tree_changes(event_loop):
    client = Mock()
    client.watch_property = AsyncMock(event_loop)
    client.unwatch_property = AsyncMock(event_loop)
    ls = Ls(client, event_loop)

    # Test that values make it through
    foo_bar_cb = AsyncMock(event_loop)
    await ls.watch_path("foo/bar", foo_bar_cb)

    # Initially None
    foo_bar_cb.assert_called_once_with("foo/bar", None)

    # When a listing arrives, nothing should happen if we don't have the whole
    # tree of paths
    await ls._on_ls_tree_property_changed("meta/ls/foo/", {
        "bar": [{"behaviour": "EVENT-1:N"}],
    })
    assert foo_bar_cb.call_count == 1

    # When the final missing part of the tree arrives, a callback should come
    # through
    await ls._on_ls_tree_property_changed("meta/ls/", {
        "foo": [{"behaviour": "DIRECTORY"}],
    })
    assert foo_bar_cb.call_count == 2
    foo_bar_cb.assert_called_with("foo/bar", [{"behaviour": "EVENT-1:N"}])

    # A second registration should immediately get the value
    foo_bar_cb2 = AsyncMock(event_loop)
    await ls.watch_path("foo/bar", foo_bar_cb2)
    foo_bar_cb2.assert_called_once_with(
        "foo/bar", [{"behaviour": "EVENT-1:N"}])

    # A tree update which doesn't change the value should not result in a call
    await ls._on_ls_tree_property_changed("meta/ls/", {
        "foo": [{"behaviour": "DIRECTORY"}],
        "irrelevant": [{"behaviour": "EVENT-1:N"}],
    })
    assert foo_bar_cb.call_count == 2
    assert foo_bar_cb2.call_count == 1

    # If any part of the path is removed, should be None again
    await ls._on_ls_tree_property_changed("meta/ls/", {
        "irrelevant": [{"behaviour": "EVENT-1:N"}],
    })
    assert foo_bar_cb.call_count == 3
    foo_bar_cb.assert_called_with("foo/bar", None)
    assert foo_bar_cb2.call_count == 2
    foo_bar_cb2.assert_called_with("foo/bar", None)

    # Put it back again...
    await ls._on_ls_tree_property_changed("meta/ls/", {
        "foo": [{"behaviour": "DIRECTORY"}],
    })
    assert foo_bar_cb.call_count == 4
    foo_bar_cb.assert_called_with("foo/bar", [{"behaviour": "EVENT-1:N"}])
    assert foo_bar_cb2.call_count == 3
    foo_bar_cb2.assert_called_with("foo/bar", [{"behaviour": "EVENT-1:N"}])

    # If the listing property is deleted, everything should also disappear.
    await ls._on_ls_tree_property_changed("meta/ls/foo/", qth.Empty)
    assert foo_bar_cb.call_count == 5
    foo_bar_cb.assert_called_with("foo/bar", None)
    assert foo_bar_cb2.call_count == 4
    foo_bar_cb2.assert_called_with("foo/bar", None)
