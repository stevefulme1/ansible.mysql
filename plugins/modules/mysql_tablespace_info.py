#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Steve Fulmer (@stevefulme1)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: mysql_tablespace_info
short_description: Gather information about MySQL/InnoDB tablespaces
description:
- Gathers information about InnoDB tablespaces from C(information_schema.innodb_tablespaces)
  and C(information_schema.files).
- Can return all tablespaces or filter by name.
version_added: '5.1.0'
author:
- Steve Fulmer (@stevefulme1)
options:
  name:
    description:
    - Name of a specific tablespace to retrieve information for.
    - If not specified, returns information about all tablespaces.
    type: str

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

extends_documentation_fragment:
- ansible.mysql.mysql

seealso:
- module: ansible.mysql.mysql_tablespace
- name: MySQL InnoDB tablespaces reference
  description: Official MySQL documentation for InnoDB tablespaces.
  link: https://dev.mysql.com/doc/refman/8.0/en/innodb-tablespace.html
'''

EXAMPLES = r'''
- name: Get information about all tablespaces
  ansible.mysql.mysql_tablespace_info:
  register: all_tablespaces

- name: Get information about a specific tablespace
  ansible.mysql.mysql_tablespace_info:
    name: my_tablespace
  register: ts_info

- name: Display tablespace details
  ansible.builtin.debug:
    var: ts_info.tablespaces
'''

RETURN = r'''
tablespaces:
  description: List of tablespace information dictionaries.
  returned: success
  type: list
  elements: dict
  sample:
    - name: my_tablespace
      space_id: 42
      space_type: General
      encryption: false
      file_name: ./my_tablespace.ibd
      engine: InnoDB
      file_size: 114688
'''

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


def get_tablespaces(cursor, name=None):
    """Query information_schema for tablespace details."""
    query = ("SELECT t.SPACE AS space_id, t.NAME AS name, "
             "t.SPACE_TYPE AS space_type, t.ENCRYPTION AS encryption, "
             "f.FILE_NAME AS file_name, f.ENGINE AS engine, "
             "f.TOTAL_EXTENTS * f.EXTENT_SIZE AS file_size "
             "FROM information_schema.innodb_tablespaces t "
             "LEFT JOIN information_schema.files f "
             "ON t.NAME = f.TABLESPACE_NAME")

    params = ()
    if name:
        query += " WHERE t.NAME = %s"
        params = (name,)

    query += " ORDER BY t.NAME"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    tablespaces = []
    for row in rows:
        if isinstance(row, dict):
            ts = {
                'name': row.get('name', ''),
                'space_id': row.get('space_id', 0),
                'space_type': row.get('space_type', ''),
                'encryption': row.get('encryption', 'N') == 'Y',
                'file_name': row.get('file_name', ''),
                'engine': row.get('engine', 'InnoDB'),
                'file_size': row.get('file_size', 0),
            }
        else:
            ts = {
                'space_id': row[0] if len(row) > 0 else 0,
                'name': row[1] if len(row) > 1 else '',
                'space_type': row[2] if len(row) > 2 else '',
                'encryption': (row[3] if len(row) > 3 else 'N') == 'Y',
                'file_name': row[4] if len(row) > 4 else '',
                'engine': row[5] if len(row) > 5 else 'InnoDB',
                'file_size': row[6] if len(row) > 6 else 0,
            }
        tablespaces.append(ts)

    return tablespaces


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        name=dict(type='str'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    name = module.params['name']

    if mysql_driver is None:
        module.fail_json(msg=mysql_driver_fail_msg)
    else:
        warnings.filterwarnings('error', category=mysql_driver.Warning)

    login_password = module.params["login_password"]
    login_user = module.params["login_user"]
    ssl_cert = module.params["client_cert"]
    ssl_key = module.params["client_key"]
    ssl_ca = module.params["ca_cert"]
    check_hostname = module.params["check_hostname"]
    connect_timeout = module.params['connect_timeout']
    config_file = module.params['config_file']

    try:
        cursor, db_conn = mysql_connect(
            module, login_user, login_password, config_file,
            ssl_cert, ssl_key, ssl_ca, None,
            cursor_class='DictCursor',
            connect_timeout=connect_timeout,
            check_hostname=check_hostname,
        )
    except Exception as e:
        if os.path.exists(config_file):
            module.fail_json(
                msg="unable to connect to database, check login_user and "
                    "login_password are correct or %s has the credentials. "
                    "Exception message: %s" % (config_file, to_native(e)))
        else:
            module.fail_json(
                msg="unable to find %s. Exception message: %s" % (config_file, to_native(e)))

    try:
        tablespaces = get_tablespaces(cursor, name)
    except Exception as e:
        module.fail_json(msg="Failed to query tablespace information: %s" % to_native(e))

    warnings.simplefilter("ignore")
    module.exit_json(changed=False, tablespaces=tablespaces)


if __name__ == '__main__':
    main()
