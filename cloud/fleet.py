#!/usr/bin/python

DOCUMENTATION = '''
---
module: fleet
version_added: "1.8"
short_description: controls a CoreOS cluster via the `fleetctl` CLI
description:
     -  This ansible module is a pass-thru to the `fleetctl` CLI.
        `fleetctl` is a command-line interface to fleet,
        the cluster-wide CoreOS init system.
        Depending on the command, successful invocations will
        also set ansible facts prefixed by `fleet_`.
        The ansible `fleet` module is compatible with fleet v0.8.3, though
        it should work with newer versions.
        This module should be run on a host with a working
        `fleetctl` binary.
        Unfortunately, this is probably not a CoreOS host itself,
        since CoreOS lacks a python interpreter.
        The `fleetctl` binary is available for Mac OSX and linux,
        see https://github.com/coreos/fleet/releases.

options:
  command:
    description:
      - The fleetctl command to run.
    required: true
    choices:
      - cat
      - debug-info
      - destroy
      - journal
      - list-machines
      - list-units
      - load
      - start
      - status
      - stop
      - submit
      - unload
      - verify
      - version
    aliases: []
  unit:
    description:
      - The name of the unit.
        Provided as the first argument to the following commands:
        { submit, verify, start, stop, status, load, unload, cat, journal }.
        Note: typically this unit name has already been submitted to the
        registry, or is already present on the filesystem.
        In the latter case, the ansible `template` or `copy` module
        would be most convenient in staging the server with such a file!
    required: false
    aliases: []
  extra_args:
    description:
      - Arbitrary extra arguments to pass to the fleetctl command.
        e.g. --no-block=true (when used with command=load).
        Note: some commands such as `list-machines` and `list-units`
        have predetermined arguments
    required: false
    aliases: []
  tunnel:
    description:
      - Establish an SSH tunnel through the provided
        address for communication with fleet and etcd.
        Defaults to localhost (port 22).
        Alternatively defined by the FLEETCTL_TUNNEL environment variable.
        e.g. 192.168.0.20 or 192.168.0.20:22
    required: false
    default: 0
    aliases: []
  binary:
    description:
      - Path and name of the fleetctl binary.
        Defaults to `fleetctl` (to be found on the default PATH).
    required: false
    default: fleetctl
  debug:
    description:
      - Print out more debug information to stderr.
    required: false
    default: false
    aliases: []
  endpoint:
    description:
      - etcd endpoint for fleet.
        Alternatively defined by the FLEETCTL_ENDPOINT environment variable.
    required: true
    default: http://127.0.0.1:4001
    aliases: []
  known_hosts_file:
    description:
      - File used to store remote machine fingerprints.
        Ignored if strict host key checking is disabled.
    required: false
    default: ~/.fleetctl/known_hosts
    aliases: []
  strict_host_key_checking:
    description:
      - Verify host keys presented by remote machines
        before initiating SSH connections.
    required: false
    default: true
    aliases: []

# informational: requirements for nodes
requirements: []
author: Fairiz Azizi <coderfi@gmail.com>
'''

EXAMPLES = '''
- name: list fleet machines on default host
  fleet: command=list-machines

- name: list-machines on the specified remote host
  fleet: command=list-units
         tunnel=coreos.example.com

- name: list-machines on a remote host specified by a var
  fleet: command=list-units
         tunnel="{{ fleet_manage_host }}"

- name: list fleet units on a remote host, disabling strict host key check
  fleet: command=list-units
         strict_host_key_checking=false

- name: create a hello unit from a template
  template: src=/mytemplates/hello.service.j2
            dest=/tmp/hello.service

- name: submit the hello unit
  fleet: command=submit
         tunnel=coreos.example.com
         strict_host_key_checking=false
         unit=/tmp/hello.service

- name: start the hello unit
  fleet: command=start
         tunnel=coreos.example.com
         strict_host_key_checking=false
         unit=hello

- name: look at the hello journal log
  fleet: command=journal
         extra_args="-lines=5"
         tunnel=coreos.example.com
         strict_host_key_checking=false
         unit: hello

- name: stop the hello unit
  fleet: command=stop
         tunnel=coreos.example.com
         strict_host_key_checking=false
         unit=hello

- name: destroy the hello unit
  fleet: command=destroy
         tunnel=coreos.example.com
         strict_host_key_checking=false
         unit=hello
'''

# ===========================================
# Module execution.
#

import pipes
import shlex
import subprocess

CMD_ARGS = {'list-machines': [
                    '-full=true',
                    '-fields=machine,ip,metadata',
                    '-no-legend=false'],
            'list-units': [
                    '-full=true',
                    '-fields=hash,unit,load,active,sub,machine',
                    '-no-legend=false']}


def parse_facts(command,
                command_args,
                output):
    """ Gathers facts from the output of a fleetctl command.

    Note: this should only be called if the fleetctl command
    executed successfully.

    :param command the fleetctl command that generated this output
           The following commands are supported:
              list-machines (-full command args recommended)
              list-units (-full command args recommended)
    :param command_args the command_args passed (if any
    :param output the raw string output from the command

    :return a dictionary (of ansible facts)
            or an empty one if could not parse any facts.
            All keys begin with 'fleet_'
    """

    # this is somewhat hacky, too bad fleetctl commands do not
    # provide machine parseable output (yet)

    facts = {}

    if command == 'list-machines':
        '''
        MACHINE        IP        METADATA
        bc85e23c...    1.1.1.1    key1=val1,key2=val2
        d2f17670...    2.2.2.2
        '''
        by_keys = ('ip', )

        facts['fleet_machines'] = machines = {}
        facts['fleet_machines_by'] = by = {'meta': {}}
        for by_key in by_keys:
            by[by_key] = {}

        rows = output.split('\n')
        if len(rows) > 1:
            by_meta = by['meta']

            for row in rows[1:]:
                row = row.split(None, 3)

                if not row:
                    continue

                metadata = {}
                machine_data = dict(id=row[0],
                                    ip=row[1],
                                    metadata=metadata)

                if row[2]:
                    for kv in row[2].split(','):
                        if '=' not in kv:
                            # then must be blank (i.e. no tags)
                            continue

                        k, v = kv.split('=')

                        kmeta = by_meta.get(k, None)
                        if not kmeta:
                            kmeta = by_meta[k] = {}

                        vmeta = kmeta.get(v, None)
                        if not vmeta:
                            vmeta = kmeta[v] = {}

                        metadata[k] = v
                        vmeta[machine_data['id']] = machine_data

                for by_key in by_keys:
                    v = machine_data[by_key]
                    if v:
                        by_machines = by[by_key].get(v, None)
                        if not by_machines:
                            by_machines = by[by_key][v] = {}
                        by_machines[machine_data['id']] = machine_data

                machines[machine_data['id']] = machine_data

            facts['fleet_num_machines'] = len(machines)

    elif command == 'list-units':
        '''
        HASH    UNIT                LOAD    ACTIVE    SUB    MACHINE
        2783a93    docker-registry.1.service    loaded    active    running    2f1d2afe.../192.168.1.1
        '''
        by_keys = ('load', 'active', 'sub', 'machine')

        facts['fleet_units'] = units = {}
        facts['fleet_units_by'] = by = {}
        for by_key in by_keys:
            by[by_key] = {}

        rows = output.split('\n')
        if len(rows) > 1:
            header = [x.lower() for x in rows[0].split()]

            for row in rows[1:]:
                row = row.split(None, 7)

                if not row:
                    continue

                unit_data = dict(zip(header, row))
                for k, v in unit_data.items():
                    if v == '-' or (not v):
                        unit_data[k] = None

                for by_key in by_keys:
                    v = unit_data[by_key]
                    if v:
                        by_units = by[by_key].get(v, None)
                        if not by_units:
                            by_units = by[by_key][v] = {}
                        by_units[unit_data['hash']] = unit_data

                units[unit_data['hash']] = unit_data

            facts['fleet_num_units'] = len(units)
    #else: TBI parse other command outputs!

    return facts


def main():
    module = AnsibleModule(
        argument_spec=dict(
            binary=dict(required=False,
                        default='fleetctl'),
            command=dict(required=True,
                         choices=['cat',
                              'debug-info',
                              'destroy',
                              'journal',
                              'list-machines',
                              'list-units',
                              'load',
                              'start',
                              'status',
                              'stop',
                              'submit',
                              'unload',
                              'verify']),
            extra_args=dict(required=False),
            unit=dict(required=False),
            debug=dict(required=False,
                       default=False,
                       type='bool'),
            strict_host_key_checking=dict(required=False,
                                          type='bool',
                                          default=True),
            endpoint=dict(required=False,
                          default='http://127.0.0.1:4001'),
            known_hosts_file=dict(required=False,
                                  default='~/.fleetctl/known_hosts'),
            tunnel=dict(required=False,
                        default=''),
        ),
        supports_check_mode=False,
        check_invalid_arguments=False
    )

    binary           = module.params.get('binary')
    command          = module.params.get('command')
    unit             = module.params.get('unit')
    extra_args       = module.params.get('extra_args')
    debug            = module.params.get('debug')
    strict_host      = module.params.get('strict_host_key_checking')
    endpoint         = module.params.get('endpoint')
    known_hosts_file = module.params.get('known_hosts_file')
    tunnel           = module.params.get('tunnel')

    args = []

    def argh(name, value):
        if value in (0, True, False):
            args.append("-%s=%s" % (name, value))
        elif value:
            args.append("-%s=%s" % (name, pipes.quote(value)))
        #else do nothing

    args.append(binary)
    argh('debug', debug)
    argh('strict-host-key-checking', strict_host)
    argh('endpoint', endpoint)
    argh('known-hosts-file', known_hosts_file)
    argh('tunnel', tunnel)
    args.append(command)

    if extra_args:
        shlex_args = shlex.split(extra_args)
        args.extend(shlex_args)

    command_args = CMD_ARGS.get(command)
    if command_args:
        args.extend(command_args)

    if command in ('submit', 'verify',
                   'start', 'stop', 'status',
                   'destroy',
                   'load', 'unload',
                   'cat', 'journal'):
        # generically pass the unit argument

        if not unit:
            module.fail_json(msg="unit argument required for command=%s" \
                                 % command)
            return
        args.append(unit)
    #else hope for the best...

    try:
        output = subprocess.check_output(
                     args)

        ansible_facts = parse_facts(command,
                                    command_args,
                                    output)

        module.exit_json(changed=True,
                         msg='OK',
                         output=output,
                         ansible_facts=ansible_facts)
    except subprocess.CalledProcessError, e:
        module.fail_json(returncode=e.returncode,
                         output=e.output,
                         msg=unicode(e))
        return


# import module snippets
from ansible.module_utils.basic import *

main()
