import asyncio

import json
import logging

import qth
from qth_ls import Ls

from qth_alias.version import __version__  # noqa
from qth_alias.alias import Alias


def has_cycle(aliases):
    """Chcek if {alias: target, ...} dictionary contains a cyclic dependency.
    If there is, returns the cycle as a list of paths.
    """
    for start in aliases:
        visited = [start]

        pos = start
        while pos in aliases:
            pos = aliases[pos]
            if pos in visited:
                return visited + [pos]
            visited.append(pos)

    return None


class AliasServer(object):
    """The Qth alias server."""

    def __init__(self, cache_file="/dev/null", prefix="meta/alias/",
                 host=None, port=None, keepalive=10, loop=None):
        """
        Initialise the Qth Alias server. Call async_init() soon after
        construciton.

        Parameters
        ----------
        cache_file : str
            Filename into which the current set of aliases is saved and loaded.
        prefix : str
            The prefix for the Qth paths which control the alias server.
        host : str or None
            Qth hostname.
        port : int or None
            Qth port.
        keepalive : int
            MQTT Keepalive interval.
        loop : qsyncio.AbstractEventLoop
            The event loop to use.
        """
        self._cache_file = cache_file
        self._loop = loop or asyncio.get_event_loop()

        self._add_path = prefix + "add"
        self._remove_path = prefix + "remove"
        self._aliases_path = prefix + "aliases"
        self._error_path = prefix + "error"

        self._client = qth.Client(
            "qth_alias",
            "Defines aliases of Qth properties and events.",
            host=host, port=port, keepalive=keepalive, loop=self._loop
        )

        self._ls = Ls(self._client, self._loop)

        # Lock to hold while self._aliases is being updated.
        self._aliases_lock = asyncio.Lock(loop=self._loop)

        # The current set of alias registrations.
        # {"path/to/alias": Alias, ...}
        self._aliases = {}

    async def async_init(self):
        """Call asynchronously shortly after construction to complete setup."""

        # Load existing aliases from file
        initial_aliases = {}
        try:
            with open(self._cache_file, "r") as f:
                initial_aliases = json.load(f)
        except Exception as e:
            logging.exception(e)

        # Register with Qth Registrar
        await asyncio.wait([
            self._client.register(self._aliases_path,
                                  qth.PROPERTY_ONE_TO_MANY,
                                  "The currently registered set of aliases. "
                                  "A dictionary {'path/to/alias': {'target': "
                                  "'path/to/target', 'alias': "
                                  "'path/to/alias', 'transform': 'f(value)', "
                                  "'inverse': 'f_inverse(value)', "
                                  "'description': '...'}, ...}"),
            self._client.register(self._add_path,
                                  qth.EVENT_MANY_TO_ONE,
                                  "Create (or update) an alias. "
                                  "Call with ['target', 'alias'] or "
                                  "a dictionary {'path/to/alias': {'target': "
                                  "'path/to/target', 'alias': "
                                  "'path/to/alias', 'transform': 'f(value)', "
                                  "'inverse': 'f_inverse(value)', "
                                  "'description': '...'}, ...}"),
            self._client.register(self._remove_path,
                                  qth.EVENT_MANY_TO_ONE,
                                  "Remove an alias. Call with the alias' "
                                  "path."),
            self._client.register(self._error_path, qth.EVENT_ONE_TO_MANY,
                                  "An event raised whenever qth_alias "
                                  "encounters a problem."),
            self._client.watch_event(self._add_path, self._on_add),
            self._client.watch_event(self._remove_path, self._on_remove),
            self._client.watch_property(self._aliases_path, self._on_change),
        ], loop=self._loop)

        # Set property to initialise the alias set (and also the property in
        # Qth).
        await self._client.set_property(self._aliases_path, initial_aliases)

    async def close(self):
        """Shut down the alias server"""
        async with self._aliases_lock:
            # Unregister everything and delete all aliases
            await asyncio.wait([
                self._client.unregister(self._aliases_path),
                self._client.unregister(self._add_path),
                self._client.unregister(self._remove_path),
                self._client.unregister(self._error_path),
                self._client.unwatch_event(self._add_path, self._on_add),
                self._client.unwatch_event(self._remove_path, self._on_remove),
                self._client.unwatch_property(self._aliases_path,
                                              self._on_change),
            ] + [
                alias.delete() for alias in self._aliases.values()
            ], loop=self._loop)

            # Delete aliases property (after all watches have been removed)
            await self._client.delete_property(self._aliases_path)

            self._aliases = {}

    @property
    def _aliases_json(self):
        """Return the JSON-serialisable equivilent of _aliases."""
        return {path: alias.json for path, alias in self._aliases.items()}

    def _error_sync(self, message):
        """Non-async wrapper around _error."""
        self._loop.create_task(self._error(message))

    async def _error(self, message):
        """Report an error via the console and meta/alias/error."""
        logging.error(message)
        await self._client.send_event(self._error_path, message)

    async def _on_add(self, _topic, alias_spec):
        """Callback from the meta/alias/add event."""
        # Convert from short-form
        if isinstance(alias_spec, list):
            if len(alias_spec) == 2:
                alias_spec = {
                    "target": alias_spec[0],
                    "alias": alias_spec[1],
                }
            else:
                await self._error(
                    "{}: short form alias must have two entries".format(
                        self._add_path))
                return

        if not isinstance(alias_spec, dict):
            await self._error("{}: expected a list or dictionary".format(
                self._add_path))
            return

        # Check for missing target/alias
        if "target" not in alias_spec:
            await self._error("{}: no 'target' in alias specification.".format(
                self._add_path))
            return
        if "alias" not in alias_spec:
            await self._error("{}: no 'alias' in alias specification.".format(
                self._add_path))
            return

        # Fill in defaults
        if "transform" not in alias_spec:
            alias_spec["transform"] = None
        if "inverse" not in alias_spec:
            alias_spec["inverse"] = None
        if "description" not in alias_spec:
            alias_spec["description"] = "Alias of {}.".format(
                alias_spec["target"])

        # Check for extra fields
        fields = set(alias_spec)
        expected = set("target alias transform inverse description".split())
        if fields != expected:
            await self._error("{}: unexpected extra fields {}".format(
                self._add_path,
                ", ".join(map(repr, fields - expected))
            ))
            return

        # Validate the provided entries
        if "target" not in alias_spec:
            await self._error("{}: expected a 'target' entry".format(
                self._add_path))
            return
        if "alias" not in alias_spec:
            await self._error(": expected an 'alias' entry".format(
                self._add_path))
            return
        if ((alias_spec["transform"] is None) !=
                (alias_spec["inverse"] is None)):
            await self._error(
                "{}: expected either both or neither of 'transform' and "
                "'inverse' to be supplied.".format(
                    self._add_path))
            return

        # Insert into the specification
        aliases = self._aliases_json.copy()
        aliases[alias_spec["alias"]] = alias_spec
        await self._update_aliases(aliases)

    async def _on_remove(self, _topic, alias_path):
        """Callback from the meta/alias/remove event."""
        # Remove the alias
        aliases = self._aliases_json.copy()
        aliases.pop(alias_path, None)
        await self._update_aliases(aliases)

    async def _on_change(self, _topic, aliases):
        """Callback from changes to meta/alias/aliases property."""
        await self._update_aliases(aliases)

    async def _update_aliases(self, aliases):
        """Update the set of aliases to match a new specification."""
        async with self._aliases_lock:
            # Do nothing if not changed
            if self._aliases_json == aliases:
                return

            # Check for dependency cycles
            cycle = has_cycle({a["alias"]: a["target"]
                               for a in aliases.values()})
            if cycle:
                # Revert if cycle is found
                await self._error("cyclic alias dependency: {}".format(
                    " -> ".join(cycle)))
                await self._client.set_property(self._aliases_path,
                                                self._aliases_json)
                return

            old_aliases = set(self._aliases)
            new_aliases = set(aliases)

            added = new_aliases - old_aliases
            removed = old_aliases - new_aliases
            changed = set()

            # Changed aliases are treated as removed-then-added
            for path in old_aliases & new_aliases:
                if self._aliases[path].json != aliases[path]:
                    changed.add(path)

            logging.info(
                "Updating aliases: Added: %s. Changed: %s. Removed: %s.",
                ", ".join(added), ", ".join(changed), ", ".join(removed))

            todo = []

            # Update the set of aliases
            for path in removed | changed:
                todo.append(self._aliases.pop(path).delete())
            for path in added | changed:
                alias = Alias(self, **aliases[path])
                todo.append(alias.async_init())
                self._aliases[path] = alias

            # Update the property
            todo.append(self._client.set_property(
                self._aliases_path,
                self._aliases_json))

            if todo:
                await asyncio.wait(todo, loop=self._loop)

            # Save aliases to file
            try:
                with open(self._cache_file, "w") as f:
                    json.dump(self._aliases_json, f)
            except Exception as e:
                logging.exception(e)
