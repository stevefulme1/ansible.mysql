#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, Steve Fulmer (@stevefulme1)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: mysql_router_info
short_description: Gather information about MySQL Router status
description:
  - Queries the MySQL Router REST API for routing status, destinations, and metadata.
  - Returns route and destination details from the Router's HTTP endpoint.
version_added: '5.1.0'
author:
  - Steve Fulmer (@stevefulme1)
options:
  router_host:
    description:
      - Hostname or IP address where the MySQL Router REST API is listening.
    type: str
    default: localhost
  router_port:
    description:
      - Port where the MySQL Router REST API is listening.
    type: int
    default: 8443
  router_username:
    description:
      - Username for the MySQL Router REST API.
    type: str
  router_password:
    description:
      - Password for the MySQL Router REST API.
    type: str
  use_ssl:
    description:
      - Whether to use HTTPS when connecting to the Router REST API.
    type: bool
    default: true
  validate_certs:
    description:
      - Whether to validate SSL certificates for the Router REST API.
    type: bool
    default: false

attributes:
  check_mode:
    support: full
    description: This module is read-only and always supports check mode.
    details:
      - This module is read-only and always runs in check mode.
  idempotent:
    support: full
    description: This module only reads data and always returns the same result.

seealso:
  - module: ansible.mysql.mysql_router
  - module: ansible.mysql.mysql_innodb_cluster
  - name: MySQL Router REST API documentation
    description: Official MySQL Router REST API reference.
    link: https://dev.mysql.com/doc/mysql-router/en/mysql-router-rest-api.html

notes:
  - This module queries the MySQL Router REST API, which must be enabled in the Router configuration.
  - The REST API is typically available on port 8443 with HTTPS.
  - Does not require the C(ansible.mysql.mysql) doc fragment since it connects to the Router REST API,
    not directly to a MySQL database server.
'''

EXAMPLES = r'''
- name: Get MySQL Router status
  ansible.mysql.mysql_router_info:
    router_host: 192.0.2.1
    router_port: 8443
    router_username: admin
    router_password: secret
  register: router_info

- name: Display Router routes
  ansible.builtin.debug:
    var: router_info.routes

- name: Get Router info with custom SSL settings
  ansible.mysql.mysql_router_info:
    router_host: 192.0.2.1
    use_ssl: true
    validate_certs: false
    router_username: admin
    router_password: secret
'''

RETURN = r'''
router_status:
  description: Overall Router status information.
  returned: success
  type: dict
  contains:
    process_id:
      description: Process ID of the MySQL Router instance.
      type: int
      returned: when available
    product_edition:
      description: MySQL Router product edition.
      type: str
      returned: when available
    time_started:
      description: Timestamp when the Router was started.
      type: str
      returned: when available
    version:
      description: MySQL Router version.
      type: str
      returned: when available
routes:
  description: List of configured routes.
  returned: success
  type: list
  elements: dict
  contains:
    name:
      description: Name of the route.
      type: str
      returned: always
      sample: "bootstrap_rw"
    route_info:
      description: Route details including destinations and status.
      type: dict
      returned: when route details are available
destinations:
  description: List of route destinations.
  returned: success
  type: list
  elements: dict
'''

import json

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import open_url


def query_router_api(module, base_url, path, username=None, password=None, validate_certs=False):
    """Query a MySQL Router REST API endpoint."""
    url = "%s%s" % (base_url, path)

    try:
        response = open_url(
            url,
            method='GET',
            url_username=username,
            url_password=password,
            validate_certs=validate_certs,
            force_basic_auth=True,
        )
        body = response.read()
        return json.loads(body)
    except Exception as e:
        return None


def main():
    argument_spec = dict(
        router_host=dict(type='str', default='localhost'),
        router_port=dict(type='int', default=8443),
        router_username=dict(type='str'),
        router_password=dict(type='str', no_log=True),
        use_ssl=dict(type='bool', default=True),
        validate_certs=dict(type='bool', default=False),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    router_host = module.params['router_host']
    router_port = module.params['router_port']
    username = module.params['router_username']
    password = module.params['router_password']
    use_ssl = module.params['use_ssl']
    validate_certs = module.params['validate_certs']

    scheme = 'https' if use_ssl else 'http'
    base_url = "%s://%s:%s" % (scheme, router_host, router_port)

    # Query Router status
    router_status = query_router_api(
        module, base_url, '/api/20190715/router/status',
        username, password, validate_certs)
    if router_status is None:
        router_status = {}

    # Query routes
    routes_data = query_router_api(
        module, base_url, '/api/20190715/routes',
        username, password, validate_certs)
    routes = []
    if routes_data and 'items' in routes_data:
        for item in routes_data['items']:
            route_name = item.get('name', '')
            # Get details for each route
            route_info = query_router_api(
                module, base_url, '/api/20190715/routes/%s/status' % route_name,
                username, password, validate_certs)
            routes.append({
                'name': route_name,
                'route_info': route_info or {},
            })

    # Query destinations
    destinations_data = query_router_api(
        module, base_url, '/api/20190715/routes',
        username, password, validate_certs)
    destinations = []
    if routes:
        for route in routes:
            dest_data = query_router_api(
                module, base_url,
                '/api/20190715/routes/%s/destinations' % route['name'],
                username, password, validate_certs)
            if dest_data and 'items' in dest_data:
                for dest in dest_data['items']:
                    destinations.append(dest)

    module.exit_json(
        changed=False,
        router_status=router_status,
        routes=routes,
        destinations=destinations,
    )


if __name__ == '__main__':
    main()
