#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Steve Fulmer (@stevefulme1)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: mysql_innodb_cluster_info
short_description: Gather information about MySQL InnoDB Cluster
description:
  - Retrieves status and metadata for MySQL InnoDB Clusters.
  - Queries the InnoDB Cluster metadata schema and MySQL Shell AdminAPI for cluster status.
version_added: '5.1.0'
author:
  - Steve Fulmer (@stevefulme1)
options:
  name:
    description:
      - Name of the InnoDB Cluster to query.
      - If not specified, returns information about all clusters found in the metadata schema.
    type: str
  mysqlsh_path:
    description:
      - Path to the C(mysqlsh) binary.
      - If not specified, the module searches C(PATH) for C(mysqlsh).
    type: path

attributes:
  check_mode:
    support: full
    details:
      - This module is read-only and always runs in check mode.
  idempotent:
    support: full

extends_documentation_fragment:
  - ansible.mysql.mysql

seealso:
  - module: ansible.mysql.mysql_innodb_cluster
  - module: ansible.mysql.mysql_group_replication
  - name: MySQL InnoDB Cluster documentation
    description: Official MySQL InnoDB Cluster reference.
    link: https://dev.mysql.com/doc/mysql-shell/en/mysql-innodb-cluster.html

notes:
  - This module queries the C(mysql_innodb_cluster_metadata) schema for cluster and instance metadata.
  - If C(mysqlsh) is available, it additionally retrieves live cluster status via the AdminAPI.
  - This is an info module and does not make any changes.
'''

EXAMPLES = r'''
- name: Get information about all InnoDB Clusters
  ansible.mysql.mysql_innodb_cluster_info:
    login_user: root
    login_password: secret
    login_host: 192.0.2.1
  register: cluster_info

- name: Get information about a specific cluster
  ansible.mysql.mysql_innodb_cluster_info:
    name: myCluster
    login_user: root
    login_password: secret
  register: cluster_info

- name: Display cluster topology
  ansible.builtin.debug:
    var: cluster_info.clusters
'''

RETURN = r'''
clusters:
  description: List of InnoDB Cluster information dictionaries.
  returned: always
  type: list
  elements: dict
  contains:
    cluster_name:
      description: Name of the cluster.
      type: str
      returned: always
      sample: myCluster
    cluster_id:
      description: Internal cluster ID from the metadata schema.
      type: int
      returned: always
      sample: 1
    description:
      description: Cluster description from the metadata schema.
      type: str
      returned: always
    primary_mode:
      description: The primary mode of the cluster (C(pm) for single-primary, C(mm) for multi-primary).
      type: str
      returned: always
      sample: pm
    instances:
      description: List of instances in the cluster from the metadata schema.
      type: list
      elements: dict
      returned: always
      contains:
        instance_id:
          description: Internal instance ID.
          type: int
          returned: always
        address:
          description: Instance address (host:port).
          type: str
          returned: always
          sample: "192.0.2.1:3306"
        mysql_server_uuid:
          description: The MySQL server UUID.
          type: str
          returned: always
    status:
      description: Live cluster status from the AdminAPI (when C(mysqlsh) is available).
      type: dict
      returned: when mysqlsh is available
'''

import json
import os
import warnings

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    mysql_connect,
    mysql_driver,
    mysql_driver_fail_msg,
    mysql_common_argument_spec,
)
from ansible.module_utils.common.text.converters import to_native


def get_clusters_from_metadata(cursor, name=None):
    """Query the InnoDB Cluster metadata schema for cluster info."""
    clusters = []
    try:
        if name:
            cursor.execute(
                "SELECT cluster_id, cluster_name, description, primary_mode "
                "FROM mysql_innodb_cluster_metadata.clusters "
                "WHERE cluster_name = %s", (name,))
        else:
            cursor.execute(
                "SELECT cluster_id, cluster_name, description, primary_mode "
                "FROM mysql_innodb_cluster_metadata.clusters")
        rows = cursor.fetchall()
    except Exception:
        return clusters

    for row in rows:
        if isinstance(row, dict):
            cluster = dict(row)
        else:
            cluster = {
                'cluster_id': row[0],
                'cluster_name': row[1],
                'description': row[2],
                'primary_mode': row[3],
            }

        # Get instances for this cluster
        try:
            cursor.execute(
                "SELECT instance_id, cluster_id, address, mysql_server_uuid "
                "FROM mysql_innodb_cluster_metadata.instances "
                "WHERE cluster_id = %s", (cluster['cluster_id'],))
            instance_rows = cursor.fetchall()
            instances = []
            for irow in instance_rows:
                if isinstance(irow, dict):
                    instances.append(dict(irow))
                else:
                    instances.append({
                        'instance_id': irow[0],
                        'cluster_id': irow[1],
                        'address': irow[2],
                        'mysql_server_uuid': irow[3],
                    })
            cluster['instances'] = instances
        except Exception:
            cluster['instances'] = []

        clusters.append(cluster)

    return clusters


def get_cluster_status_via_shell(module, mysqlsh, uri):
    """Get live cluster status via mysqlsh AdminAPI."""
    cmd = [mysqlsh, '--uri', uri, '--no-password', '--json=raw',
           '-e', 'dba.getCluster().status()']
    rc, stdout, stderr = module.run_command(cmd)
    if rc != 0:
        return None
    try:
        return json.loads(stdout)
    except (ValueError, TypeError):
        return None


def build_connection_uri(module):
    """Build a mysqlsh connection URI from module parameters."""
    user = module.params['login_user'] or 'root'
    password = module.params['login_password']
    host = module.params['login_host'] or 'localhost'
    port = module.params['login_port'] or 3306

    if password:
        return "%s:%s@%s:%s" % (user, password, host, port)
    return "%s@%s:%s" % (user, host, port)


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        name=dict(type='str'),
        mysqlsh_path=dict(type='path'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    name = module.params['name']

    if mysql_driver is None:
        module.fail_json(msg=mysql_driver_fail_msg)

    warnings.filterwarnings('error', category=mysql_driver.Warning)

    login_user = module.params['login_user']
    login_password = module.params['login_password']
    config_file = module.params['config_file']
    ssl_cert = module.params['client_cert']
    ssl_key = module.params['client_key']
    ssl_ca = module.params['ca_cert']
    check_hostname = module.params['check_hostname']
    connect_timeout = module.params['connect_timeout']

    try:
        cursor, db_conn = mysql_connect(
            module, login_user, login_password, config_file,
            ssl_cert, ssl_key, ssl_ca, None,
            cursor_class='DictCursor',
            connect_timeout=connect_timeout,
            check_hostname=check_hostname)
    except Exception as e:
        if os.path.exists(config_file):
            module.fail_json(
                msg="unable to connect to database, check login_user and "
                    "login_password are correct or %s has the credentials. "
                    "Exception message: %s" % (config_file, to_native(e)))
        else:
            module.fail_json(
                msg="unable to find %s. Exception message: %s" % (config_file, to_native(e)))

    clusters = get_clusters_from_metadata(cursor, name)

    # Try to get live status via mysqlsh if available
    mysqlsh_path = module.params.get('mysqlsh_path')
    if not mysqlsh_path:
        mysqlsh_path = module.get_bin_path('mysqlsh')

    if mysqlsh_path:
        uri = build_connection_uri(module)
        status = get_cluster_status_via_shell(module, mysqlsh_path, uri)
        if status and clusters:
            for cluster in clusters:
                if cluster.get('cluster_name') == status.get('clusterName', ''):
                    cluster['status'] = status

    module.exit_json(changed=False, clusters=clusters)


if __name__ == '__main__':
    main()
