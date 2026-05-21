#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Steve Fulmer (@stevefulme1)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: mysql_tablespace
short_description: Manage MySQL/InnoDB tablespaces
description:
- Creates, alters, and drops InnoDB general tablespaces in MySQL.
- Supports setting the datafile path, encryption, and storage engine.
version_added: '5.1.0'
author:
- Steve Fulmer (@stevefulme1)
options:
  name:
    description:
    - Name of the tablespace.
    type: str
    required: true
  state:
    description:
    - Whether the tablespace should be present or absent.
    type: str
    choices: [present, absent]
    default: present
  datafile:
    description:
    - Path to the datafile for the tablespace.
    - Required when creating a new tablespace (C(state=present) and tablespace does not exist).
    type: str
  encryption:
    description:
    - Whether the tablespace should be encrypted.
    - Requires MySQL 5.7+ with keyring plugin configured.
    type: bool
  engine:
    description:
    - Storage engine for the tablespace.
    type: str
    default: InnoDB

notes:
- Compatible with MySQL 5.7+ and MySQL 8.0+.
- MariaDB uses a different tablespace model; this module targets InnoDB general tablespaces.
- Dropping a tablespace requires that no tables reside in it.

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

extends_documentation_fragment:
- ansible.mysql.mysql

seealso:
- module: ansible.mysql.mysql_tablespace_info
- name: MySQL CREATE TABLESPACE reference
  description: Official MySQL documentation for CREATE TABLESPACE.
  link: https://dev.mysql.com/doc/refman/8.0/en/create-tablespace.html
'''

EXAMPLES = r'''
- name: Create a general tablespace
  ansible.mysql.mysql_tablespace:
    name: my_tablespace
    datafile: /var/lib/mysql/my_tablespace.ibd
    state: present

- name: Create an encrypted tablespace
  ansible.mysql.mysql_tablespace:
    name: secure_ts
    datafile: /var/lib/mysql/secure_ts.ibd
    encryption: true
    state: present

- name: Alter tablespace encryption
  ansible.mysql.mysql_tablespace:
    name: my_tablespace
    encryption: false
    state: present

- name: Drop a tablespace
  ansible.mysql.mysql_tablespace:
    name: my_tablespace
    state: absent
'''

RETURN = r'''
queries:
  description: List of executed queries which modified the server state.
  returned: always
  type: list
  sample: ["CREATE TABLESPACE `my_tablespace` ADD DATAFILE 'my_tablespace.ibd' ENGINE = InnoDB"]
tablespace:
  description: Current tablespace information after changes.
  returned: success
  type: dict
  sample:
    name: my_tablespace
    file_name: my_tablespace.ibd
    encryption: false
    engine: InnoDB
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
from ansible_collections.ansible.mysql.plugins.module_utils.database import (
    mysql_quote_identifier,
)
from ansible.module_utils.common.text.converters import to_native


def get_tablespace_info(cursor, name):
    """Get tablespace information from information_schema."""
    query = ("SELECT SPACE, NAME, SPACE_TYPE, ENCRYPTION "
             "FROM information_schema.innodb_tablespaces "
             "WHERE NAME = %s")
    cursor.execute(query, (name,))
    row = cursor.fetchone()
    if not row:
        return None

    info = {}
    if isinstance(row, dict):
        info['name'] = row.get('NAME', name)
        info['encryption'] = row.get('ENCRYPTION', 'N') == 'Y'
        info['space_type'] = row.get('SPACE_TYPE', '')
    else:
        info['name'] = row[1] if len(row) > 1 else name
        info['encryption'] = (row[3] if len(row) > 3 else 'N') == 'Y'
        info['space_type'] = row[2] if len(row) > 2 else ''

    # Get file info
    file_query = ("SELECT FILE_NAME, ENGINE "
                  "FROM information_schema.files "
                  "WHERE TABLESPACE_NAME = %s")
    cursor.execute(file_query, (name,))
    file_row = cursor.fetchone()
    if file_row:
        if isinstance(file_row, dict):
            info['file_name'] = file_row.get('FILE_NAME', '')
            info['engine'] = file_row.get('ENGINE', 'InnoDB')
        else:
            info['file_name'] = file_row[0] if len(file_row) > 0 else ''
            info['engine'] = file_row[1] if len(file_row) > 1 else 'InnoDB'
    else:
        info['file_name'] = ''
        info['engine'] = 'InnoDB'

    return info


def create_tablespace(cursor, name, datafile, encryption, engine):
    """Build and execute CREATE TABLESPACE."""
    quoted_name = mysql_quote_identifier(name, 'database')
    query = "CREATE TABLESPACE %s ADD DATAFILE '%s'" % (quoted_name, datafile)

    if engine:
        query += " ENGINE = %s" % engine

    if encryption is not None:
        query += " ENCRYPTION = '%s'" % ('Y' if encryption else 'N')

    cursor.execute(query)
    return query


def alter_tablespace_encryption(cursor, name, encryption):
    """Alter tablespace encryption setting."""
    quoted_name = mysql_quote_identifier(name, 'database')
    enc_val = 'Y' if encryption else 'N'
    query = "ALTER TABLESPACE %s ENCRYPTION = '%s'" % (quoted_name, enc_val)
    cursor.execute(query)
    return query


def drop_tablespace(cursor, name):
    """Drop a tablespace."""
    quoted_name = mysql_quote_identifier(name, 'database')
    query = "DROP TABLESPACE %s" % quoted_name
    cursor.execute(query)
    return query


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        name=dict(type='str', required=True),
        state=dict(type='str', default='present', choices=['present', 'absent']),
        datafile=dict(type='str'),
        encryption=dict(type='bool'),
        engine=dict(type='str', default='InnoDB'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    name = module.params['name']
    state = module.params['state']
    datafile = module.params['datafile']
    encryption = module.params['encryption']
    engine = module.params['engine']

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

    executed_queries = []
    current = get_tablespace_info(cursor, name)

    if state == 'absent':
        if current is None:
            module.exit_json(changed=False, queries=executed_queries, tablespace={})

        if module.check_mode:
            module.exit_json(changed=True, queries=["DROP TABLESPACE `%s`" % name], tablespace={})

        try:
            q = drop_tablespace(cursor, name)
            executed_queries.append(q)
        except Exception as e:
            module.fail_json(
                msg="Failed to drop tablespace '%s': %s" % (name, to_native(e)),
                queries=executed_queries,
            )

        warnings.simplefilter("ignore")
        module.exit_json(changed=True, queries=executed_queries, tablespace={})

    # state == 'present'
    if current is None:
        # Create
        if not datafile:
            module.fail_json(msg="'datafile' is required when creating a new tablespace.")

        if module.check_mode:
            module.exit_json(changed=True, queries=["CREATE TABLESPACE ..."], tablespace={})

        try:
            q = create_tablespace(cursor, name, datafile, encryption, engine)
            executed_queries.append(q)
        except Exception as e:
            module.fail_json(
                msg="Failed to create tablespace '%s': %s" % (name, to_native(e)),
                queries=executed_queries,
            )

        new_info = get_tablespace_info(cursor, name) or {}
        warnings.simplefilter("ignore")
        module.exit_json(changed=True, queries=executed_queries, tablespace=new_info)

    # Tablespace exists - check if encryption needs changing
    changed = False
    if encryption is not None and current.get('encryption') != encryption:
        if module.check_mode:
            module.exit_json(changed=True, queries=["ALTER TABLESPACE ..."], tablespace=current)

        try:
            q = alter_tablespace_encryption(cursor, name, encryption)
            executed_queries.append(q)
            changed = True
        except Exception as e:
            module.fail_json(
                msg="Failed to alter tablespace '%s': %s" % (name, to_native(e)),
                queries=executed_queries,
            )

    new_info = get_tablespace_info(cursor, name) or current
    warnings.simplefilter("ignore")
    module.exit_json(changed=changed, queries=executed_queries, tablespace=new_info)


if __name__ == '__main__':
    main()
