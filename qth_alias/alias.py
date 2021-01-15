import math, functools, itertools  # noqa
import asyncio

import qth


PROPERTY_BEHAVIOURS = [
    qth.PROPERTY_MANY_TO_ONE,
    qth.PROPERTY_ONE_TO_MANY,
]
EVENT_BEHAVIOURS = [
    qth.EVENT_MANY_TO_ONE,
    qth.EVENT_ONE_TO_MANY,
]


class Alias(object):
    """Holds the state (and logic) associated with a given alias."""

    def __init__(self, alias_server, target, alias,
                 transform=None, inverse=None, description=""):
        self._alias_server = alias_server

        self._target = target
        self._alias = alias
        self._transform_code = transform
        self._inverse_code = inverse
        self._description = description

        self._deleted = False

        # The most recently received registration of the target
        self._target_registration = None

        # This lock must be held while changes resulting from the target's
        # registration details are reconclied.
        # * (Un)registering the alias
        # * Seting up (and clearing) watches of the target and alias
        #   property/event
        #
        self._registration_change_lock = asyncio.Lock(loop=self._loop)

        # The most recently sent alias registration
        self._alias_registration = None

        # Are we currently watching as a property?
        self._watching_property = False

        # Are we currently watching as an event?
        self._watching_event = False

        # Values we've sent to the target or alias which we'll shortly receive
        # back through the registered watchers. These values are ignored and
        # removed from these lists to avoid a feedback loop.
        self._ignored_target_values = []
        self._ignored_alias_values = []

    async def async_init(self):
        """Call asynchronously shortly after construction to complete setup."""
        await asyncio.wait([
            self._ls.watch_path(
                self._target, self._on_target_registration_changed),
        ], loop=self._loop)

    async def delete(self):
        """Remove the alias."""
        self._deleted = True

        async with self._registration_change_lock:
            todo = []

            # Remove the alias registration
            if self._alias_registration:
                todo.append(self._client.unregister(self._alias))

            # Unwatch the target/property
            if self._watching_property:
                todo.append(self._client.unwatch_property(
                    self._alias,
                    self._on_alias_set))
                todo.append(self._client.unwatch_property(
                    self._target,
                    self._on_target_set))
            if self._watching_event:
                todo.append(self._client.unwatch_event(
                    self._alias,
                    self._on_alias_sent))
                todo.append(self._client.unwatch_event(
                    self._target,
                    self._on_target_sent))

            # Set/send the alias on unregister value
            if self._alias_registration:
                if "on_unregister" in self._alias_registration:
                    if (self._alias_registration["behaviour"]
                            in PROPERTY_BEHAVIOURS):
                        todo.append(self._client.set_property(
                            self._alias,
                            self._alias_registration["on_unregister"]))
                    else:
                        todo.append(self._client.send_event(
                            self._alias,
                            self._alias_registration["on_unregister"]))
                if self._alias_registration.get("delete_on_unregister", False):
                    todo.append(self._client.delete_property(self._alias))

            if todo:
                await asyncio.wait(todo, loop=self._loop)

    @property
    def json(self):
        """Return the JSON-serialisable specification for this alias."""
        return {
            "target": self._target,
            "alias": self._alias,
            "transform": self._transform_code,
            "inverse": self._inverse_code,
            "description": self._description,
        }

    @property
    def _loop(self):
        return self._alias_server._loop

    @property
    def _client(self):
        return self._alias_server._client

    @property
    def _ls(self):
        return self._alias_server._ls

    def _eval_transform(self, code, value):
        """Eval 'code' with local variable 'value'.

        If code is None, just pass through the value. If the value is
        qth.Empty, just pass that through too. If an exception is raised, pass
        through the value and send an error event.
        """
        if code is None:
            return value
        elif value is qth.Empty:
            return value
        else:
            try:
                return eval(code, globals(), {"value": value})
            except Exception as e:
                self._alias_server._error_sync(
                    "transform/invert: Exception while transforming/inverting "
                    "value for alias {} with code {}: {}".format(
                        self._alias,
                        repr(code),
                        str(e)))
                return value

    def _transform(self, target_value):
        """Transform a value from the target value to an alias value."""
        return self._eval_transform(self._transform_code, target_value)

    def _inverse(self, alias_value):
        """Transform a value from the alias value to a target value."""
        return self._eval_transform(self._inverse_code, alias_value)

    async def _on_target_set(self, _path, target_value):
        """Called when the target property is set."""
        if target_value in self._ignored_target_values:
            self._ignored_target_values.remove(target_value)
        else:
            alias_value = self._transform(target_value)
            self._ignored_alias_values.append(alias_value)
            await self._client.set_property(self._alias, alias_value)

    async def _on_alias_set(self, _path, alias_value):
        """Called when the alias property is set."""
        if alias_value in self._ignored_alias_values:
            self._ignored_alias_values.remove(alias_value)
        else:
            transform_value = self._inverse(alias_value)
            self._ignored_target_values.append(transform_value)
            await self._client.set_property(self._target, transform_value)

    async def _on_target_sent(self, _path, target_value):
        """Called when an event is received from the target."""
        if target_value in self._ignored_target_values:
            self._ignored_target_values.remove(target_value)
        else:
            alias_value = self._transform(target_value)
            self._ignored_alias_values.append(alias_value)
            await self._client.send_event(self._alias, alias_value)

    async def _on_alias_sent(self, _path, alias_value):
        """Called when an event is received from the alias."""
        if alias_value in self._ignored_alias_values:
            self._ignored_alias_values.remove(alias_value)
        else:
            transform_value = self._inverse(alias_value)
            self._ignored_target_values.append(transform_value)
            await self._client.send_event(self._target, transform_value)

    async def _on_target_registration_changed(self, _path, registration):
        """Called when the target's registration info changes."""
        if self._deleted:
            return

        # Find a non-directory registration
        if registration:
            for entry in registration:
                if entry["behaviour"] != qth.DIRECTORY:
                    self._target_registration = entry
                    break
        else:
            self._target_registration = None

        async with self._registration_change_lock:
            if self._deleted:
                return

            todo = []

            # Update the Qth registration as required
            if self._target_registration is not None:
                # Copy the relevant fields from the registration
                new_alias_registration = {}
                for field in ["behaviour", "description",
                              "on_unregister", "delete_on_unregister"]:
                    if field in self._target_registration:
                        new_alias_registration[field] = \
                            self._target_registration[field]

                # Use the alias description instead
                new_alias_registration["description"] = self._description

                # If an on_unregister value is given, convert this into the
                # alias' form
                if "on_unregister" in new_alias_registration:
                    new_alias_registration["on_unregister"] = \
                        self._transform(
                            new_alias_registration["on_unregister"])

                if new_alias_registration != self._alias_registration:
                    self._alias_registration = new_alias_registration
                    todo.append(self._client.register(
                        self._alias, **new_alias_registration))
            elif self._alias_registration is not None:
                # Unregister the alias since the target was also unregistered
                self._alias_registration = None
                todo.append(self._client.unregister(self._alias))

            # Update the watches as required (NB: Don't remove watches when
            # unregistering since we still want to forward
            # un_unregister/delete_on_unregister values sent by the registrar).
            if self._target_registration is not None:
                is_property = self._target_registration["behaviour"] in \
                    PROPERTY_BEHAVIOURS
                is_event = self._target_registration["behaviour"] in \
                    EVENT_BEHAVIOURS

                # Remove old watches
                if self._watching_property and not is_property:
                    self._watching_property = False
                    todo.append(self._client.unwatch_property(
                        self._alias, self._on_alias_set))
                    todo.append(self._client.unwatch_property(
                        self._target, self._on_target_set))
                if self._watching_event and not is_event:
                    self._watching_event = False
                    todo.append(self._client.unwatch_event(
                        self._alias, self._on_alias_sent))
                    todo.append(self._client.unwatch_event(
                        self._target, self._on_target_sent))

                # Add new watch
                if not self._watching_property and is_property:
                    self._watching_property = True
                    todo.append(self._client.watch_property(
                        self._alias, self._on_alias_set))
                    todo.append(self._client.watch_property(
                        self._target, self._on_target_set))
                if not self._watching_event and is_event:
                    self._watching_event = True
                    todo.append(self._client.watch_event(
                        self._alias, self._on_alias_sent))
                    todo.append(self._client.watch_event(
                        self._target, self._on_target_sent))

            if todo:
                await asyncio.wait(todo, loop=self._loop)
