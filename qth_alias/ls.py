import asyncio

from itertools import chain

import qth


def path_to_subdirectories(path):
    """Given a path, generate every subdirectory that path resides within.

    For example given "foo/bar/baz" generates "", "foo/" and "foo/bar/".
    """
    # Always within the root
    yield ""
    parts = path.split("/")
    for depth in range(len(parts) - 1):
        yield "/".join(parts[:depth+1]) + "/"


def listing_has_subdir(directory_listing, subdir):
    """Given a directory listing, check if it has a given subdir."""
    return any(listing["behaviour"] == qth.DIRECTORY
               for listing in directory_listing.get(subdir, []))


def get_path_listing(ls_tree, path):
    """Given an ls_tree, attempt to find the entry for the supplied path.
    Returns None if any part of the path is not registered.
    """
    listing = None
    for subdir, child in zip(path_to_subdirectories(path), path.split("/")):
        tree_entry = ls_tree.get(subdir) or {}
        listing = tree_entry.get(child, [])
        if not listing:
            return None

    return listing


class Ls(object):
    """
    Utility for getting listing information about Qth paths from the registrar
    (i.e. meta/ls/).
    """

    def __init__(self, client, loop=None):
        self._client = client
        self._loop = loop or asyncio.get_event_loop()

        # The latest copy of the subtree of the `meta/ls/` tree which is
        # relevent to the paths being aliased. Paths for which no property
        # value has been received (but to which we've subscribed) are listed as
        # None.
        self._ls_tree = {}

        # For each path being monitored the last known value received
        self._last_path_value = {}

        # For each path being monitored, the list of callbacks registered for
        # change events.
        self._callbacks = {}

    async def watch_path(self, path, callback):
        """Call callback with the path and directory listing entry for the
        specified path. The callback will also be called when the listing
        changes. If the path is not registered the callback will be called with
        None.
        """
        new_path = False
        if path not in self._callbacks:
            self._callbacks[path] = []
            new_path = True
        self._callbacks[path].append(callback)

        if new_path:
            await self._update_ls_tree_watches()

        if path not in self._last_path_value:
            self._last_path_value[path] = None

        await callback(path, self._last_path_value[path])

    async def unwatch_path(self, path, callback):
        """Unregister a callback when a path's directory listing entry
        changes.
        """
        self._callbacks[path].remove(callback)

        # If a path now lacks any callbacks, clean up
        if not self._callbacks[path]:
            self._callbacks.pop(path)
            self._last_path_value.pop(path, None)
            await self._update_ls_tree_watches()

    async def _update_ls_tree_watches(self):
        """Update the set of watches on the meta/ls/ tree to include all of the
        paths currently being aliased.
        """
        # Get the set of paths in the meta/ls/ tree which must be monitored to
        # keep up with all current alias targets.
        new_paths = set(chain(*[path_to_subdirectories(path)
                                for path in self._callbacks.keys()]))
        old_paths = set(self._ls_tree)

        added = new_paths - old_paths
        removed = old_paths - new_paths

        todo = []

        for path in added:
            self._ls_tree[path] = None
            todo.append(self._client.watch_property(
                "meta/ls/{}".format(path), self._on_ls_tree_property_changed))

        for path in removed:
            self._ls_tree.pop(path)
            todo.append(self._client.unwatch_property(
                "meta/ls/{}".format(path), self._on_ls_tree_property_changed))

        # Note: The tree doesn't meaningfully change after a path is added
        # until the initial value of the property is received.
        if removed:
            todo.append(self._on_ls_tree_changed())

        if todo:
            await asyncio.wait(todo, loop=self._loop)

    async def _on_ls_tree_property_changed(self, topic, value):
        """Callback when a property in meta/ls/ changes."""
        assert topic.startswith("meta/ls/")
        path = topic[len("meta/ls/"):]

        if path in self._ls_tree:
            if value is qth.Empty:
                value = None

            if self._ls_tree[path] != value:
                self._ls_tree[path] = value
                await self._on_ls_tree_changed()

    async def _on_ls_tree_changed(self):
        """
        Called when self._ls_tree changes. Calls user-supplied callbacks as
        required.
        """
        todo = []

        for path, callbacks in self._callbacks.items():
            value = get_path_listing(self._ls_tree, path)
            if value != self._last_path_value[path]:
                self._last_path_value[path] = value
                todo.extend(cb(path, value) for cb in self._callbacks[path])

        if todo:
            await asyncio.wait(todo, loop=self._loop)
