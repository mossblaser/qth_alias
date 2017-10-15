Qth Alias
=========

Qth Alias allows you to create aliases for Qth properties and events.

In addition to simple aliases, Qth Alias can create aliases which are
transformations of their target. For example, an alias of a property which
holds a value between 0 and 63 might be turned into a float between 0.0 and
1.0.

Motivation
----------

Aliases are useful for mapping low-level entities (e.g. trees of sensor nodes
and sensors organised by network topology) in into a higher-level structures
(e.g. trees of rooms and and uses).

For a motivating example, you might have a tree which looks like this:

* `lighting_controller/`
    * `light0`
    * `light1`
    * `light2`
    * ...
* `lounge/`
    * ...
* `kitchen/`
    * ...
* `bedroom/`
    * ...

Here we have the low-level properties controlling lights grouped together into
a single directory relating to the underlying hardware device. Ideally,
however, the properties for controling the lights would appear in the relevant
room directory. Qth Alias allows you to create properties (and events) which
are aliases of other Qth properties (and events) in the tree, for example:

* `lighting_controller/`
    * `light0`
    * `light1`
    * `light2`
    * ...
* `lounge/`
    * `light` (alias of `lighting_controller/light0`)
    * ...
* `kitchen/`
    * `light` (alias of `lighting_controller/light1`)
    * ...
* `bedroom/`
    * `light` (alias of `lighting_controller/light2`)
    * ...

Here, the aliased and underlying properties can be used interchangably. What's
more, Qth Alias allows you to define simple transformations on property and
event values. For example, say our low-level lighting properties expect an
integer value between 0 and 63 but, being civilised people, we'd prefer our
property to have a value between 0.0 and 1.0. By specifying an appropriate
transformation, Qth alias can create such aliases.

Usage
-----

First, start the Qth Alias server:

    $ qth_alias

### Adding Aliases (`meta/alias/add`)

Aliases can then be created and managed via Qth itself. To create a new alias,
send an event to `meta/alias/add` with a payload structured in one of the
following forms:

* Short-form for defining a straight-forward alias

      ["path/of/existing/property/or/event", "path/of/new/alias"]

* Long-form:

      {
          "target": "path/of/existing/property/or/event",
          "alias": "path/of/new/alias",
          "transform": "native_to_alias(value)",
          "inverse": "alias_to_native(value)",
          "description": "Human readable description for alias.",
      }

  The 'target' and 'alias' values are mandatory and give the Qth paths of the
  target of the alias and the alias itself.
  
  The 'transform' and 'inverse' values are strings containing valid Python 3
  expressions which transform the variable 'value' into the form used by the
  alias (or back into the target form in the case of 'inverse'. If either one
  of 'transform' or 'inverse' is given, the other must also be given. For
  example, if the target values are integers between 0 and 63 and the alias
  should use values 0.0 - 1.0:
  
      "transform": "value / 63.0",
      "inverse": "int(round(value * 63))",
  
  Alternatively, you may omit 'transform' and 'inverse' (or set them to `null`)
  and no transformation will be applied.
  
  The 'description' value is a human readable description to use for the alias'
  listing in the Qth directory. If not given, a default description stating
  what the alias' target is will be used.

Aliases must have unique targets. Aliases may in turn be aliased by create
cyclic dependencies must not be created (this is checked).

If an alias is added with an existing 'alias' path, the existing alias will be
replaced.

### Error reporting (`meta/alias/error`)

If there is a problem creating an alias (or evaluating the transform or inverse
code) a human-readable error event is sent to `meta/alias/error`.

### Removing aliases (`meta/alias/remove`)

To delete an existing alias, send an event with the alias's Qth path to
`meta/alias/remove`.

### Listing existing aliases (`meta/alias/aliases`)

The configured set of aliases can be found in the `meta/alias/aliases`
property. This will be of the form of a dictionary of long-form alias
descriptions keyed by the alias path. Though not recommended, it is also valid
to create and delete aliases by changing this property directly. Only long form
specifications should be added.


Development
-----------

Tests can be run using py.test:

    $ python setup.py develop
    $ pip install -r requirements-test.py
    $ py.test tests/
    $ flake8 tests/ qth_alias/
