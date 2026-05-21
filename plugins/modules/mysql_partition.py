#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Steve Fulmer (@stevefulme1)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: mysql_partition
short_description: Manage MySQL table partitions
description:
- Manages partitions on MySQL tables using C(ALTER TABLE).
- Supports C(ADD PARTITION), C(DROP PARTITION), C(TRUNCATE PARTITION),
  and C(REORGANIZE PARTITION).
- Partition state is read from C(information_schema.partitions) for idempotency.
version_added: '5.1.0'
author:
- Steve Fulmer (@stevefulme1)
options:
  state:
    description:
    - Desired state of the partition.
    - C(present) adds a partition if it does not exist.
    - C(absent) drops a partition.
    - C(truncated) truncates a partition's data.
    - C(reorganized) reorganizes an existing partition into new partitions.
    type: str
    choices: [present, absent, truncated, reorganized]
    default: present
  table:
    description:
    - Name of the table to manage partitions on.
    type: str
    required: true
  schema:
    description:
    - Database/schema containing the table.
    type: str
    required: true
  partition_name:
    description:
    - Name of the partition to add, drop, truncate, or reorganize.
    type: str
    required: true
  partition_type:
    description:
    - Type of partitioning.
    - Required when C(state=present) and the table is not yet partitioned.
    type: str
    choices: [RANGE, LIST, HASH, KEY]
  values_less_than:
    description:
    - Upper bound for a RANGE partition.
    - Use C(MAXVALUE) for the catch-all partition.
    type: str
  values_in:
    description:
    - Comma-separated list of values for a LIST partition.
    type: str
  partition_count:
    description:
    - Number of partitions for HASH/KEY partitioning.
    - Only used when initially partitioning a table.
    type: int
  reorganize_into:
    description:
    - List of new partition definitions when C(state=reorganized).
    - Each item is a dict with C(name) and C(values_less_than) or C(values_in).
    type: list
    elements: dict
    suboptions:
      name:
        description: Name of the new partition.
        type: str
        required: true
      values_less_than:
        description: Upper bound for the new RANGE partition.
        type: str
      values_in:
        description: Values for the new LIST partition.
        type: str

notes:
- Compatible with MySQL 5.7+ and MySQL 8.0+.
- MariaDB partition syntax is similar but may differ in edge cases.
- Adding a RANGE partition requires values greater than the current maximum.

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

extends_documentation_fragment:
- ansible.mysql.mysql

seealso:
- name: MySQL partitioning reference
  description: Official MySQL documentation for table partitioning.
  link: https://dev.mysql.com/doc/refman/8.0/en/partitioning.html
'''

EXAMPLES = r'''
- name: Add a RANGE partition
  ansible.mysql.mysql_partition:
    schema: mydb
    table: orders
    partition_name: p2024
    values_less_than: "2025"
    state: present

- name: Add a MAXVALUE partition
  ansible.mysql.mysql_partition:
    schema: mydb
    table: orders
    partition_name: p_future
    values_less_than: MAXVALUE
    state: present

- name: Drop a partition
  ansible.mysql.mysql_partition:
    schema: mydb
    table: orders
    partition_name: p2020
    state: absent

- name: Truncate a partition
  ansible.mysql.mysql_partition:
    schema: mydb
    table: orders
    partition_name: p2022
    state: truncated

- name: Reorganize a partition into two
  ansible.mysql.mysql_partition:
    schema: mydb
    table: orders
    partition_name: p_future
    state: reorganized
    reorganize_into:
      - name: p2025
        values_less_than: "2026"
      - name: p_future
        values_less_than: MAXVALUE

- name: Add a LIST partition
  ansible.mysql.mysql_partition:
    schema: mydb
    table: regions
    partition_name: p_west
    values_in: "'CA','OR','WA'"
    state: present
'''

RETURN = r'''
queries:
  description: List of executed queries which modified the server state.
  returned: always
  type: list
  sample: ["ALTER TABLE `mydb`.`orders` ADD PARTITION (PARTITION p2024 VALUES LESS THAN (2025))"]
partition:
  description: Information about the partition after changes.
  returned: success
  type: dict
  sample:
    partition_name: p2024
    partition_method: RANGE
    partition_expression: year(order_date)
    partition_description: "2025"
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


def get_partition_info(cursor, schema, table, partition_name=None):
    """Query information_schema.partitions for partition details."""
    query = ("SELECT PARTITION_NAME, PARTITION_METHOD, PARTITION_EXPRESSION, "
             "PARTITION_DESCRIPTION, TABLE_ROWS "
             "FROM information_schema.partitions "
             "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s")
    params = [schema, table]

    if partition_name:
        query += " AND PARTITION_NAME = %s"
        params.append(partition_name)
    else:
        query += " AND PARTITION_NAME IS NOT NULL"

    query += " ORDER BY PARTITION_ORDINAL_POSITION"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    partitions = []
    for row in rows:
        if isinstance(row, dict):
            p = {
                'partition_name': row.get('PARTITION_NAME', ''),
                'partition_method': row.get('PARTITION_METHOD', ''),
                'partition_expression': row.get('PARTITION_EXPRESSION', ''),
                'partition_description': row.get('PARTITION_DESCRIPTION', ''),
                'table_rows': row.get('TABLE_ROWS', 0),
            }
        else:
            p = {
                'partition_name': row[0] if len(row) > 0 else '',
                'partition_method': row[1] if len(row) > 1 else '',
                'partition_expression': row[2] if len(row) > 2 else '',
                'partition_description': row[3] if len(row) > 3 else '',
                'table_rows': row[4] if len(row) > 4 else 0,
            }
        partitions.append(p)

    return partitions


def partition_exists(cursor, schema, table, partition_name):
    """Check if a specific partition exists."""
    parts = get_partition_info(cursor, schema, table, partition_name)
    return len(parts) > 0


def build_table_ref(schema, table):
    """Build a quoted schema.table reference."""
    return "%s.%s" % (
        mysql_quote_identifier(schema, 'database'),
        mysql_quote_identifier(table, 'table'),
    )


def add_partition(cursor, schema, table, partition_name, values_less_than=None, values_in=None):
    """Add a partition to a table."""
    table_ref = build_table_ref(schema, table)

    if values_less_than is not None:
        if values_less_than.upper() == 'MAXVALUE':
            part_def = "PARTITION %s VALUES LESS THAN MAXVALUE" % partition_name
        else:
            part_def = "PARTITION %s VALUES LESS THAN (%s)" % (partition_name, values_less_than)
    elif values_in is not None:
        part_def = "PARTITION %s VALUES IN (%s)" % (partition_name, values_in)
    else:
        part_def = "PARTITION %s" % partition_name

    query = "ALTER TABLE %s ADD PARTITION (%s)" % (table_ref, part_def)
    cursor.execute(query)
    return query


def drop_partition(cursor, schema, table, partition_name):
    """Drop a partition from a table."""
    table_ref = build_table_ref(schema, table)
    query = "ALTER TABLE %s DROP PARTITION %s" % (table_ref, partition_name)
    cursor.execute(query)
    return query


def truncate_partition(cursor, schema, table, partition_name):
    """Truncate a partition."""
    table_ref = build_table_ref(schema, table)
    query = "ALTER TABLE %s TRUNCATE PARTITION %s" % (table_ref, partition_name)
    cursor.execute(query)
    return query


def reorganize_partition(cursor, schema, table, partition_name, reorganize_into):
    """Reorganize a partition into new partitions."""
    table_ref = build_table_ref(schema, table)

    new_parts = []
    for p in reorganize_into:
        name = p['name']
        vlt = p.get('values_less_than')
        vi = p.get('values_in')

        if vlt is not None:
            if vlt.upper() == 'MAXVALUE':
                new_parts.append("PARTITION %s VALUES LESS THAN MAXVALUE" % name)
            else:
                new_parts.append("PARTITION %s VALUES LESS THAN (%s)" % (name, vlt))
        elif vi is not None:
            new_parts.append("PARTITION %s VALUES IN (%s)" % (name, vi))
        else:
            new_parts.append("PARTITION %s" % name)

    query = "ALTER TABLE %s REORGANIZE PARTITION %s INTO (%s)" % (
        table_ref, partition_name, ', '.join(new_parts))
    cursor.execute(query)
    return query


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        state=dict(type='str', default='present',
                   choices=['present', 'absent', 'truncated', 'reorganized']),
        table=dict(type='str', required=True),
        schema=dict(type='str', required=True),
        partition_name=dict(type='str', required=True),
        partition_type=dict(type='str', choices=['RANGE', 'LIST', 'HASH', 'KEY']),
        values_less_than=dict(type='str'),
        values_in=dict(type='str'),
        partition_count=dict(type='int'),
        reorganize_into=dict(
            type='list', elements='dict',
            options=dict(
                name=dict(type='str', required=True),
                values_less_than=dict(type='str'),
                values_in=dict(type='str'),
            ),
        ),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[
            ('state', 'reorganized', ['reorganize_into']),
        ],
        mutually_exclusive=[
            ['values_less_than', 'values_in'],
        ],
    )

    state = module.params['state']
    table = module.params['table']
    schema = module.params['schema']
    partition_name = module.params['partition_name']
    values_less_than = module.params['values_less_than']
    values_in = module.params['values_in']
    reorganize_into = module.params['reorganize_into']

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
    exists = partition_exists(cursor, schema, table, partition_name)

    if state == 'present':
        if exists:
            # Already present, no change needed
            parts = get_partition_info(cursor, schema, table, partition_name)
            module.exit_json(
                changed=False, queries=executed_queries,
                partition=parts[0] if parts else {},
            )

        if module.check_mode:
            module.exit_json(changed=True, queries=["ALTER TABLE ... ADD PARTITION ..."], partition={})

        try:
            q = add_partition(cursor, schema, table, partition_name, values_less_than, values_in)
            executed_queries.append(q)
        except Exception as e:
            module.fail_json(
                msg="Failed to add partition '%s': %s" % (partition_name, to_native(e)),
                queries=executed_queries,
            )

        parts = get_partition_info(cursor, schema, table, partition_name)
        warnings.simplefilter("ignore")
        module.exit_json(
            changed=True, queries=executed_queries,
            partition=parts[0] if parts else {},
        )

    elif state == 'absent':
        if not exists:
            module.exit_json(changed=False, queries=executed_queries, partition={})

        if module.check_mode:
            module.exit_json(changed=True, queries=["ALTER TABLE ... DROP PARTITION ..."], partition={})

        try:
            q = drop_partition(cursor, schema, table, partition_name)
            executed_queries.append(q)
        except Exception as e:
            module.fail_json(
                msg="Failed to drop partition '%s': %s" % (partition_name, to_native(e)),
                queries=executed_queries,
            )

        warnings.simplefilter("ignore")
        module.exit_json(changed=True, queries=executed_queries, partition={})

    elif state == 'truncated':
        if not exists:
            module.fail_json(
                msg="Partition '%s' does not exist on table '%s.%s'." % (partition_name, schema, table))

        if module.check_mode:
            module.exit_json(changed=True, queries=["ALTER TABLE ... TRUNCATE PARTITION ..."], partition={})

        try:
            q = truncate_partition(cursor, schema, table, partition_name)
            executed_queries.append(q)
        except Exception as e:
            module.fail_json(
                msg="Failed to truncate partition '%s': %s" % (partition_name, to_native(e)),
                queries=executed_queries,
            )

        parts = get_partition_info(cursor, schema, table, partition_name)
        warnings.simplefilter("ignore")
        module.exit_json(
            changed=True, queries=executed_queries,
            partition=parts[0] if parts else {},
        )

    elif state == 'reorganized':
        if not exists:
            module.fail_json(
                msg="Partition '%s' does not exist on table '%s.%s' and cannot be reorganized." % (
                    partition_name, schema, table))

        if module.check_mode:
            module.exit_json(changed=True, queries=["ALTER TABLE ... REORGANIZE PARTITION ..."], partition={})

        try:
            q = reorganize_partition(cursor, schema, table, partition_name, reorganize_into)
            executed_queries.append(q)
        except Exception as e:
            module.fail_json(
                msg="Failed to reorganize partition '%s': %s" % (partition_name, to_native(e)),
                queries=executed_queries,
            )

        # Return info about the first new partition
        new_name = reorganize_into[0]['name'] if reorganize_into else partition_name
        parts = get_partition_info(cursor, schema, table, new_name)
        warnings.simplefilter("ignore")
        module.exit_json(
            changed=True, queries=executed_queries,
            partition=parts[0] if parts else {},
        )

    warnings.simplefilter("ignore")


if __name__ == '__main__':
    main()
