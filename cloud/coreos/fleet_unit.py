#!/usr/bin/python
#
# This is a free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This Ansible library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this library.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
module: fleet_unit
short_description: Manages Fleet units in a CoreOS cluster
description:
    - Manages Fleet units in a CoreOS cluster
    - Returns a dictionary with a message about what was changed
requirements:
    - fleet python library U(https://github.com/cnelson/python-fleet)
    - a working CoreOS cluster with the Fleet API TCP socket enabled
      (be sure to pick an accessible ip address)
      see U(https://coreos.com/fleet/docs/latest/deployment-and-configuration.html#api)
notes:
    - this module has been tested on a CoreOS stable (723.3.0) cluster,
      with fleetctl version 0.10.2,
      and python fleet version 0.1.2,
      though it may work with other versions
version_added: "2.1"
author: "Fairiz Azizi (github.com/coderfi)"
options:
  state:
    description:
      - the desired state the Unit should be in after the command executes
      - absent: destroys the unit
      - started: starts the unit, creating it if necessary,
        if it exists and is already started, nothing is done
      - stopped: stops the unit
      - present: does not alter the start/stop state,
        however, if the unit does not exist, then create it in the
        loaded (i.e. stopped) state.
      - restarted: stop the service, then starts it, creating the unit as necessary
    default: started
  name:
    description:
      - the unit identifier, e.g. 'foo.service'
      - when creating a unit, this is the name that will be used
      - when modifying the state of an existing unit, this identifies
        the unit to modify
  src:
    description:
      - path to the systemd configuration file U(http://www.freedesktop.org/software/systemd/man/systemd.unit.html)
        This can be a relative or absolute path.
      - used only if the unit is to be created,
        one and only one of: src, text or options may be specified
  text:
    description:
      - a string containing the systemd configuration file U(http://www.freedesktop.org/software/systemd/man/systemd.unit.html)
      - used only if the unit is to be created,
        one and only one of: src, text or options may be specified
  options:
    description:
      - a hash/dictionary of Unit options, each containing section, name, value
      - these represent the contents of a systemd configuration file U(http://www.freedesktop.org/software/systemd/man/systemd.unit.html)
      - used only if the unit is to be created,
        one and only one of: src, text or options may be specified
  oneway:
    description:
      - if set, do not poll Fleet to verify that the unit has changed to the desired state
    default: false
  poll_secs:
    description:
      - how long to wait, in seconds, before checking to see if the unit finally changed to the desired state
    default: 1.0
  poll_retry:
    description:
      - the maximum number of times to check
    default: 10
  endpoint:
    description:
      - The Fleet API TCP listening address and socket
    default: http://127.0.0.1:49153
'''

EXAMPLES = '''
# Launches MyApp, creating the unit and starting it if needed,
# explicitly listing options
- fleet_unit:
    state: launched
    name: MyApp.service
    options:
      - section: Unit
        name:  After
        value: docker.service
      - section: Unit
        name:  Requires
        value: docker.service
      - section: Service
        name:    ExecStartPre
        value:   -/usr/bin/docker kill busybox1
      - section: Service
        name:    ExecStartPre
        value:   -/usr/bin/docker rm busybox1
      - section: Service
        name:    ExecStartPre
        value:   -/usr/bin/docker pull busybox
      - section: Service
        name:    ExecStart
        value:   /usr/bin/docker run --name busybox1 busybox /bin/sh -c "while true; do echo Hello World; sleep 1; done"
      - section: Service
        name:    ExecStop
        value:   /usr/bin/docker stop busybox1
# Loads MyApp, but does not try to start it,
# using an inline string
- fleet_unit:
    state: present
    name: MyApp.service
    text: |
        [Unit]
        Description=MyApp
        After=docker.service
        Requires=docker.service

        [Service]
        TimeoutStartSec=0
        ExecStartPre=-/usr/bin/docker kill busybox1
        ExecStartPre=-/usr/bin/docker rm busybox1
        ExecStartPre=/usr/bin/docker pull busybox
        ExecStart=/usr/bin/docker run --name busybox1 busybox /bin/sh -c "while true; do echo Hello World; sleep 1; done"
        ExecStop=/usr/bin/docker stop busybox1
# Loads MyApp, but does not try to start it,
# using a systemd configuration file (let's pretend it looks like the text field in the inline string example)
- fleet_unit:
    state: present
    name: MyApp.service
    src: MyApp.service
# Destroys MyApp, stopping it if necessary,if it exists
- fleet_unit:
    state: absent
    name: MyApp.service
# Stops MyApp, if it exists and is started
- fleet_unit:
    state: stopped
    name: MyApp.service
'''

# ===========================================
# Module execution.
#

try:
    import fleet.v1 as fleet
    HAS_FLEET = True
except ImportError:
    HAS_FLEET = False

import time


class NotFound(Exception):
    pass


def unit(client, module):
    msg = None
    inst = None
    changed = False
    state = module.params.get('state')
    name = module.params.get('name')

    if state == 'absent':
        if not name:
            module.fail_json(msg="name is required")

        try:
            inst = get_unit(client, name)
            inst.destroy()
            changed = True
            msg = "destroyed existing unit %s" % name
        except NotFound as e:
            msg = 'unit did not exist: %s' % name
        except fleet.APIError as e:
            module.fail_json(
                msg="could not destroy unit %s: %s" % (name, str(e))
            )
    else:
        inst = None

        if name:
            try:
                inst = get_unit_if_exists(client, name)
            except fleet.APIError as e:
                module.fail_json(
                    msg="could not retrieve unit %s: %s" % (name, str(e))
                )

        if state in ('stopped', 'restarted'):
            if inst is None:
                msg = 'unit did not exist: %s' % name
            elif inst.currentState == 'launched':
                inst = set_desired_state_or_fail(
                    client, inst, 'inactive', module)
                msg = 'unit %s stopped' % name
                changed = True
            else:
                msg = 'unit %s already stopped' % name

        if state in ('started', 'restarted'):
            if inst is None:
                inst = create_unit_or_fail(
                    client, module, name, inst, 'launched')
                msg = 'unit %s created and started' % name
                changed = True
            elif inst.currentState != 'launched':
                inst = set_desired_state_or_fail(
                    client, inst, 'launched', module)
                msg = 'existing unit %s was started' % name
                changed = True
            else:
                msg = 'existing unit %s has already started' % name
        else:
            assert state == 'present'
            if inst is None:
                inst = create_unit_or_fail(
                    client, module, name, inst, 'loaded')
                msg = 'unit %s created (but not started)' % name
                changed = True
            else:
                msg = 'existing unit %s state unchanged from %s' % (
                    name, inst.currentState)

    module.exit_json(
        msg=msg,
        changed=changed
    )


def get_unit(client, name):
    try:
        return client.get_unit(name)
    except fleet.APIError as e:
        if e.code == 404:
            raise NotFound(name)
        else:
            raise

def get_unit_if_exists(client, name):
    try:
        return get_unit(client, name)
    except NotFound:
        return None


def set_desired_state_or_fail(client, inst, state, module):
    try:
        target_state = inst.set_desired_state(state)
        if target_state != state:
            module.fail_json(
                msg="could not set state to %s for unit %s: currentState=%s"
                    % (state, inst.name, target_state)
            )

        if not module.params.get('oneway'):
            remaining = module.params.get('poll_retry')
            while True:
                inst = get_unit(client, inst.name)
                if inst.currentState == target_state:
                    break

                remaining -= 1
                if remaining <= 0:
                    module.fail_json(
                        msg=("after {0} retries, "
                             "the unit {1] was in the {2] state, "
                             "expected {3}").format(
                                 module.params.get('poll_retry'),
                                 inst.name, inst.currentState, target_state)
                    )
                else:
                    time.sleep(module.params.get('poll_secs', 1))

        return inst
    except fleet.APIError as e:
        module.fail_json(
            msg="could not retrieve unit %s: %s" % (inst.name, str(e))
        )


def create_unit_or_fail(client, module, name, inst, state):
    options = module.params.get('options', None) or None
    from_file = module.params.get('src', None) or None
    text = module.params.get('text', None) or None

    n = 0
    if options: n += 1
    if from_file: n += 1
    if text: n += 1

    if (n == 0) or (n > 1):
        module.fail_json(
            msg="one and only of {text, options, from_file} must be specified"
        )

    try:
        inst = fleet.Unit(
            desired_state=state,
            options=options,
            from_file=from_file,
            from_string=text
        )
    except IOError, ioe:
        if from_file:
            module.fail_json(
                msg="unable to create unit from_file=%s: %s"
                    % (from_file, str(ioe))
            )
        raise
    else:
        try:
            return client.create_unit(name, inst)
        except fleet.APIError as apie:
            module.fail_json(
                msg="could not create unit %s: %s" % (name, str(apie))
            )


def main():
    argument_spec = dict(
        endpoint=dict(
            required=False,
            default='http://127.0.0.1:49153'
        ),
        name=dict(
            required=False,
        ),
        state=dict(
            default='started',
            choices=[
                'present',
                'started',
                'stopped',
                'restarted',
                'absent'
            ]
        ),
        poll_secs=dict(
            default=1.0
        ),
        poll_retry=dict(
            default=10
        ),
        oneway=dict(
            default=False
        ),
        src=dict(
            required=False
        ),
        text=dict(
            required=False
        ),
        options=dict(
            required=False
        ),
    )

    module = AnsibleModule(
        argument_spec=argument_spec
    )

    if not HAS_FLEET:
        module.fail_json(msg='fleet required for this module '
                             '(https://github.com/cnelson/python-fleet)')

    try:
        client = fleet.Client(module.params.get('endpoint'))
    except ValueError as e:
        module.fail_json(msg=str(e))

    unit(client, module)


# import module snippets
from ansible.module_utils.basic import *

main()
