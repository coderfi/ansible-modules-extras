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
module: fleet_facts
short_description: Gather facts about Fleet machines and units of a CoreOS cluster
description:
    - Gather facts about Fleet machines and units of a CoreOS cluster.
    - Returns a dictionary containing facts by machine or by unit.
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
version_added: "2.2"
author: "Fairiz Azizi (github.com/coderfi)"
options:
  endpoint:
    description:
      - The Fleet API TCP listening address and socket
    default: http://127.0.0.1:49153
'''

EXAMPLES = '''
# Gather facts about all Fleet machines and units.
- action:
    module: fleet_facts
    endpoint=http://127.0.0.1:49153
  register: fleet_facts
'''

# ===========================================
# Module execution.
#

try:
    import fleet.v1 as fleet
    HAS_FLEET = True
except ImportError:
    HAS_FLEET = False


def list_fleet(client, module):
    machines_arr = []
    for meta in client.list_machines():
        machines_arr.append(meta.as_dict())

    units_arr = []
    for meta in client.list_units():
        units_arr.append(meta.as_dict())

    module.exit_json(
        machines=machines_arr,
        units=units_arr
    )


def main():
    argument_spec = dict(
        endpoint=dict(
            required=False,
            default='http://127.0.0.1:49153'
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

    list_fleet(client, module)


# import module snippets
from ansible.module_utils.basic import *

main()
