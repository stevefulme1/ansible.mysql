#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Steve Fulmer (@stevefulme1)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: mysql_innodb_cluster
short_description: Manage MySQL InnoDB Cluster via MySQL Shell AdminAPI
description:
  - Create, dissolve, and manage MySQL InnoDB Clusters using the MySQL Shell (C(mysqlsh)) AdminAPI.
  - Add or remove instances from an existing cluster.
  - Requires C(mysqlsh) to be installed and accessible on the target host.
version_added: '5.1.0'
author:
  - Steve Fulmer (@stevefulme1)
options:
  state:
    description:
      - Desired state of the cluster.
      - C(present) ensures the cluster exists, creating it if necessary.
      - C(absent) dissolves the cluster.
    type: str
    choices: [present, absent]
    default: present
  name:
    description:
      - Name of the InnoDB Cluster.
    type: str
    required: true
  mode:
    description:
      - Operation mode for the module.
      - C(cluster) manages the cluster itself (create/dissolve).
      - C(instance) manages instances within an existing cluster (add/remove).
    type: str
    choices: [cluster, instance]
    default: cluster
  instance:
    description:
      - Instance address in C(user@host:port) or C(host:port) format.
      - Required when O(mode=instance).
    type: str
  instance_state:
    description:
      - Desired state of the instance within the cluster.
      - C(present) adds the instance; C(absent) removes it.
      - Only used when O(mode=instance).
    type: str
    choices: [present, absent]
    default: present
  instance_password:
    description:
      - Password for the instance being added or removed.
      - Used with O(mode=instance) operations.
    type: str
  recovery_method:
    description:
      - Recovery method to use when adding an instance.
      - C(auto) lets MySQL Shell decide; C(clone) forces clone; C(incremental) forces incremental recovery.
    type: str
    choices: [auto, clone, incremental]
    default: auto
  mysqlsh_path:
    description:
      - Path to the C(mysqlsh) binary.
      - If not specified, the module searches C(PATH) for C(mysqlsh).
    type: path
  multi_primary:
    description:
      - Whether to create the cluster in multi-primary mode.
      - Default is single-primary mode.
    type: bool
    default: false
  force:
    description:
      - Force the dissolve operation even if instances are unreachable.
      - Only used when O(state=absent).
    type: bool
    default: false
  adopt_from_gr:
    description:
      - Whether to adopt an existing Group Replication group when creating the cluster.
    type: bool
    default: false

attributes:
  check_mode:
    support: partial
    details:
      - The module reports what would change but does not execute C(mysqlsh) commands in check mode.
  idempotent:
    support: full

extends_documentation_fragment:
  - ansible.mysql.mysql

seealso:
  - module: ansible.mysql.mysql_innodb_cluster_info
  - module: ansible.mysql.mysql_group_replication
  - name: MySQL InnoDB Cluster documentation
    description: Official MySQL InnoDB Cluster reference.
    link: https://dev.mysql.com/doc/mysql-shell/en/mysql-innodb-cluster.html

notes:
  - This module requires C(mysqlsh) (MySQL Shell) to be installed on the target host.
  - The module uses the MySQL Shell AdminAPI via CLI invocation.
  - Connection parameters (O(login_user), O(login_password), O(login_host), O(login_port))
    are used to build the C(mysqlsh) connection URI.
'''

EXAMPLES = r'''
- name: Create an InnoDB Cluster
  ansible.mysql.mysql_innodb_cluster:
    name: myCluster
    state: present
    login_user: root
    login_password: secret
    login_host: 192.0.2.1

- name: Create a multi-primary InnoDB Cluster
  ansible.mysql.mysql_innodb_cluster:
    name: myCluster
    state: present
    multi_primary: true
    login_user: root
    login_password: secret

- name: Add an instance to the cluster
  ansible.mysql.mysql_innodb_cluster:
    name: myCluster
    mode: instance
    instance: root@192.0.2.2:3306
    instance_password: secret
    instance_state: present
    login_user: root
    login_password: secret
    login_host: 192.0.2.1

- name: Remove an instance from the cluster
  ansible.mysql.mysql_innodb_cluster:
    name: myCluster
    mode: instance
    instance: 192.0.2.2:3306
    instance_state: absent
    login_user: root
    login_password: secret
    login_host: 192.0.2.1

- name: Dissolve the cluster
  ansible.mysql.mysql_innodb_cluster:
    name: myCluster
    state: absent
    force: true
    login_user: root
    login_password: secret
    login_host: 192.0.2.1

- name: Adopt an existing Group Replication group
  ansible.mysql.mysql_innodb_cluster:
    name: myCluster
    state: present
    adopt_from_gr: true
    login_user: root
    login_password: secret
'''

RETURN = r'''
cluster_name:
  description: Name of the InnoDB Cluster.
  returned: always
  type: str
  sample: myCluster
changed:
  description: Whether any changes were made.
  returned: always
  type: bool
msg:
  description: Human-readable status message.
  returned: always
  type: str
  sample: "Cluster 'myCluster' created successfully"
stdout:
  description: Standard output from the mysqlsh command.
  returned: when a command is executed
  type: str
stderr:
  description: Standard error from the mysqlsh command.
  returned: when a command is executed
  type: str
'''

import json

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_common_argument_spec,
)


def build_connection_uri(module):
    """Build a mysqlsh connection URI from module parameters."""
    user = module.params['login_user'] or 'root'
    password = module.params['login_password']
    host = module.params['login_host'] or 'localhost'
    port = module.params['login_port'] or 3306

    if password:
        return "%s:%s@%s:%s" % (user, password, host, port)
    return "%s@%s:%s" % (user, host, port)


def find_mysqlsh(module):
    """Find the mysqlsh binary."""
    mysqlsh_path = module.params.get('mysqlsh_path')
    if mysqlsh_path:
        return mysqlsh_path
    return module.get_bin_path('mysqlsh', required=True)


def get_cluster_status(module, mysqlsh, uri):
    """Get cluster status via mysqlsh. Returns dict or None."""
    cmd = [mysqlsh, '--uri', uri, '--no-password', '--json=raw',
           '-e', 'dba.getCluster().status()']
    rc, stdout, stderr = module.run_command(cmd)
    if rc != 0:
        return None
    try:
        return json.loads(stdout)
    except (ValueError, TypeError):
        return None


def cluster_exists(module, mysqlsh, uri, name):
    """Check if a cluster exists by trying to get its status."""
    status = get_cluster_status(module, mysqlsh, uri)
    if status and isinstance(status, dict):
        cluster_name = status.get('clusterName', '')
        return cluster_name == name
    return False


def instance_in_cluster(module, mysqlsh, uri, instance_addr):
    """Check if an instance is already in the cluster."""
    status = get_cluster_status(module, mysqlsh, uri)
    if not status:
        return False
    topology = status.get('defaultReplicaSet', {}).get('topology', {})
    for addr in topology:
        # Normalize comparison: topology keys are host:port
        if instance_addr.rstrip('/') in addr or addr in instance_addr:
            return True
    return False


def create_cluster(module, mysqlsh, uri, name, multi_primary, adopt_from_gr):
    """Create an InnoDB Cluster."""
    options = []
    if multi_primary:
        options.append('"multiPrimary": true')
    if adopt_from_gr:
        options.append('"adoptFromGR": true')

    opts_str = '{%s}' % ', '.join(options) if options else '{}'
    js_cmd = "dba.createCluster('%s', %s)" % (name, opts_str)

    cmd = [mysqlsh, '--uri', uri, '--no-password', '--json=raw', '-e', js_cmd]
    rc, stdout, stderr = module.run_command(cmd)
    return rc, stdout, stderr


def dissolve_cluster(module, mysqlsh, uri, force):
    """Dissolve an InnoDB Cluster."""
    force_str = 'true' if force else 'false'
    js_cmd = "dba.getCluster().dissolve({force: %s})" % force_str

    cmd = [mysqlsh, '--uri', uri, '--no-password', '--json=raw', '-e', js_cmd]
    rc, stdout, stderr = module.run_command(cmd)
    return rc, stdout, stderr


def add_instance(module, mysqlsh, uri, instance_addr, instance_password, recovery_method):
    """Add an instance to the cluster."""
    opts_parts = ['"recoveryMethod": "%s"' % recovery_method]
    if instance_password:
        opts_parts.append('"password": "%s"' % instance_password)
    opts_str = '{%s}' % ', '.join(opts_parts)

    js_cmd = "dba.getCluster().addInstance('%s', %s)" % (instance_addr, opts_str)
    cmd = [mysqlsh, '--uri', uri, '--no-password', '--json=raw', '-e', js_cmd]
    rc, stdout, stderr = module.run_command(cmd)
    return rc, stdout, stderr


def remove_instance(module, mysqlsh, uri, instance_addr):
    """Remove an instance from the cluster."""
    js_cmd = "dba.getCluster().removeInstance('%s')" % instance_addr
    cmd = [mysqlsh, '--uri', uri, '--no-password', '--json=raw', '-e', js_cmd]
    rc, stdout, stderr = module.run_command(cmd)
    return rc, stdout, stderr


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        state=dict(type='str', default='present', choices=['present', 'absent']),
        name=dict(type='str', required=True),
        mode=dict(type='str', default='cluster', choices=['cluster', 'instance']),
        instance=dict(type='str'),
        instance_state=dict(type='str', default='present', choices=['present', 'absent']),
        instance_password=dict(type='str', no_log=True),
        recovery_method=dict(type='str', default='auto', choices=['auto', 'clone', 'incremental']),
        mysqlsh_path=dict(type='path'),
        multi_primary=dict(type='bool', default=False),
        force=dict(type='bool', default=False),
        adopt_from_gr=dict(type='bool', default=False),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        required_if=[
            ('mode', 'instance', ['instance']),
        ],
        supports_check_mode=True,
    )

    state = module.params['state']
    name = module.params['name']
    mode = module.params['mode']
    instance_addr = module.params['instance']
    instance_state = module.params['instance_state']
    instance_password = module.params['instance_password']
    recovery_method = module.params['recovery_method']
    multi_primary = module.params['multi_primary']
    force = module.params['force']
    adopt_from_gr = module.params['adopt_from_gr']

    result = dict(
        changed=False,
        cluster_name=name,
        msg='',
    )

    mysqlsh = find_mysqlsh(module)
    uri = build_connection_uri(module)

    if mode == 'cluster':
        exists = cluster_exists(module, mysqlsh, uri, name)

        if state == 'present':
            if exists:
                result['msg'] = "Cluster '%s' already exists" % name
            elif module.check_mode:
                result['changed'] = True
                result['msg'] = "Cluster '%s' would be created" % name
            else:
                rc, stdout, stderr = create_cluster(module, mysqlsh, uri, name,
                                                    multi_primary, adopt_from_gr)
                if rc != 0:
                    module.fail_json(
                        msg="Failed to create cluster '%s': %s" % (name, stderr),
                        stdout=stdout, stderr=stderr)
                result['changed'] = True
                result['msg'] = "Cluster '%s' created successfully" % name
                result['stdout'] = stdout
                result['stderr'] = stderr

        elif state == 'absent':
            if not exists:
                result['msg'] = "Cluster '%s' does not exist" % name
            elif module.check_mode:
                result['changed'] = True
                result['msg'] = "Cluster '%s' would be dissolved" % name
            else:
                rc, stdout, stderr = dissolve_cluster(module, mysqlsh, uri, force)
                if rc != 0:
                    module.fail_json(
                        msg="Failed to dissolve cluster '%s': %s" % (name, stderr),
                        stdout=stdout, stderr=stderr)
                result['changed'] = True
                result['msg'] = "Cluster '%s' dissolved successfully" % name
                result['stdout'] = stdout
                result['stderr'] = stderr

    elif mode == 'instance':
        if not cluster_exists(module, mysqlsh, uri, name):
            module.fail_json(msg="Cluster '%s' does not exist" % name)

        in_cluster = instance_in_cluster(module, mysqlsh, uri, instance_addr)

        if instance_state == 'present':
            if in_cluster:
                result['msg'] = "Instance '%s' already in cluster '%s'" % (instance_addr, name)
            elif module.check_mode:
                result['changed'] = True
                result['msg'] = "Instance '%s' would be added to cluster '%s'" % (instance_addr, name)
            else:
                rc, stdout, stderr = add_instance(module, mysqlsh, uri, instance_addr,
                                                  instance_password, recovery_method)
                if rc != 0:
                    module.fail_json(
                        msg="Failed to add instance '%s' to cluster '%s': %s" % (instance_addr, name, stderr),
                        stdout=stdout, stderr=stderr)
                result['changed'] = True
                result['msg'] = "Instance '%s' added to cluster '%s'" % (instance_addr, name)
                result['stdout'] = stdout
                result['stderr'] = stderr

        elif instance_state == 'absent':
            if not in_cluster:
                result['msg'] = "Instance '%s' not in cluster '%s'" % (instance_addr, name)
            elif module.check_mode:
                result['changed'] = True
                result['msg'] = "Instance '%s' would be removed from cluster '%s'" % (instance_addr, name)
            else:
                rc, stdout, stderr = remove_instance(module, mysqlsh, uri, instance_addr)
                if rc != 0:
                    module.fail_json(
                        msg="Failed to remove instance '%s' from cluster '%s': %s" % (instance_addr, name, stderr),
                        stdout=stdout, stderr=stderr)
                result['changed'] = True
                result['msg'] = "Instance '%s' removed from cluster '%s'" % (instance_addr, name)
                result['stdout'] = stdout
                result['stderr'] = stderr

    module.exit_json(**result)


if __name__ == '__main__':
    main()
