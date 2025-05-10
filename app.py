from flask import Flask, render_template_string, request, jsonify
import openstack
import os
import requests
import datetime
import logging

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>OpenStack Health Check</title>
  <style>
    body { font-family: sans-serif; background: #f4f4f4; padding: 20px; }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; background: white; }
    th, td { padding: 10px; border: 1px solid #ccc; text-align: left; }
    th { background-color: #333; color: white; }
    .ok { color: green; font-weight: bold; }
    .error { color: orange; font-weight: bold; }
    .unreachable { color: red; font-weight: bold; }
    h1 { color: #333; }
    h2 { margin-top: 30px; }
  </style>
</head>
<body>
  <h1>OpenStack Services Health Check</h1>
  <p><strong>Last check:</strong> {{ timestamp }}</p>
  {% for service in services %}
  <h2>{{ service.name }} ({{ service.type }}) - <span class="{{ service.status }}">{{ service.status.upper() }}</span></h2>
  <table>
    <thead>
      <tr>
        <th>Interface</th>
        <th>URL</th>
        <th>Status</th>
        <th>Error</th>
      </tr>
    </thead>
    <tbody>
      {% for ep in service.endpoints %}
      <tr>
        <td>{{ ep.interface }}</td>
        <td><a href="{{ ep.url }}" target="_blank">{{ ep.url }}</a></td>
        <td class="{{ 'ok' if ep.reachable else 'unreachable' }}">{{ 'OK' if ep.reachable else 'FAIL' }}</td>
        <td>{{ ep.error or '' }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endfor %}
</body>
</html>
"""

def get_connection():
    try:
        conn = openstack.connect(
            auth_url=os.getenv("OS_AUTH_URL"),
            username=os.getenv("OS_USERNAME"),
            password=os.getenv("OS_PASSWORD"),
            project_name=os.getenv("OS_PROJECT_NAME"),
            user_domain_name=os.getenv("OS_USER_DOMAIN_NAME"),
            project_domain_name=os.getenv("OS_PROJECT_DOMAIN_NAME"),
            region_name=os.getenv("OS_REGION_NAME"),
            identity_api_version=os.getenv("OS_IDENTITY_API_VERSION", "3")
        )
        return conn
    except Exception as e:
        logging.error(f"Erro ao conectar no OpenStack: {e}")
        raise

@app.route('/health', methods=['GET'])
def health_check():
    try:
        conn = get_connection()
        services = list(conn.identity.services())
        endpoints = list(conn.identity.endpoints())
    except Exception as e:
        error = f"Erro ao consultar serviços: {str(e)}"
        if "application/json" in request.headers.get("Accept", ""):
            return jsonify({"error": error}), 500
        return f"<h1>Erro: {error}</h1>", 500

    result = []
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    for service in services:
        service_data = {
            'name': service.name,
            'type': service.type,
            'status': 'unknown',
            'endpoints': []
        }

        related_endpoints = [ep for ep in endpoints if ep.service_id == service.id]

        if not related_endpoints:
            result.append(service_data)
            continue

        for endpoint in related_endpoints:
            url = endpoint.url
            try:
                r = requests.get(url, timeout=3)
                reachable = r.status_code < 500
                service_data['endpoints'].append({
                    'interface': endpoint.interface,
                    'url': url,
                    'reachable': reachable,
                    'error': None
                })
                if reachable:
                    service_data['status'] = 'ok'
            except Exception as e:
                service_data['endpoints'].append({
                    'interface': endpoint.interface,
                    'url': url,
                    'reachable': False,
                    'error': str(e)
                })
                service_data['status'] = 'unreachable'

        result.append(service_data)

    if "application/json" in request.headers.get("Accept", "") or request.args.get("format") == "json":
        return jsonify({"timestamp": timestamp, "services": result}), 200

    return render_template_string(TEMPLATE, services=result, timestamp=timestamp)

@app.route('/metrics', methods=['GET'])
def metrics():
    start_total = datetime.datetime.utcnow()

    try:
        conn = get_connection()
        services = list(conn.identity.services())
        endpoints = list(conn.identity.endpoints())
    except Exception as e:
        return f'# Error: {str(e)}\nopenstack_health_check_up 0\n', 500

    status_count = {"ok": 0, "unreachable": 0, "error": 0}
    metric_lines = []

    for service in services:
        service_status = "unknown"
        related_endpoints = [ep for ep in endpoints if ep.service_id == service.id]

        if not related_endpoints:
            status_count["unreachable"] += 1
            continue

        for endpoint in related_endpoints:
            url = endpoint.url
            safe_url = url.replace('"', '\\"')
            labels = (
                f'service="{service.name}", '
                f'type="{service.type}", '
                f'endpoint="{endpoint.interface}", '
                f'url="{safe_url}"'
            )

            try:
                start = datetime.datetime.utcnow()
                r = requests.get(url, timeout=3)
                duration = (datetime.datetime.utcnow() - start).total_seconds()

                reachable = r.status_code < 500

                metric_lines.append(f'openstack_service_up{{{labels}}} {1 if reachable else 0}')
                metric_lines.append(f'openstack_service_response_seconds{{{labels}}} {duration:.3f}')

                if reachable:
                    service_status = "ok"
                else:
                    service_status = "error"

            except Exception:
                service_status = "unreachable"
                metric_lines.append(f'openstack_service_up{{{labels}}} 0')
                metric_lines.append(f'openstack_service_response_seconds{{{labels}}} -1')

        status_count[service_status] += 1

    for status, count in status_count.items():
        metric_lines.append(f'openstack_service_status{{status="{status}"}} {count}')

    # ===== Neutron Metrics (API-based) =====
    try:
        agents = conn.network.agents()
        agent_count = 0
        for agent in agents:
            agent_count += 1
            host = agent.host.replace('"', '\\"')
            alive = 1 if agent.is_alive else 0
            metric_lines.append(f'openstack_neutron_agents_alive{{host="{host}", agent_type="{agent.agent_type}"}} {alive}')
        metric_lines.append(f'openstack_neutron_agents_total {agent_count}')
    except Exception as e:
        metric_lines.append(f'# Error collecting Neutron agents: {str(e)}')

    try:
        ports = list(conn.network.ports())
        status_count = {}
        for port in ports:
            status = port.status.upper()
            status_count[status] = status_count.get(status, 0) + 1
        for status, count in status_count.items():
            metric_lines.append(f'openstack_neutron_ports_status{{status="{status}"}} {count}')
        metric_lines.append(f'openstack_neutron_ports_total {len(ports)}')
    except Exception as e:
        metric_lines.append(f'# Error collecting Neutron ports: {str(e)}')

    try:
        networks = list(conn.network.networks())
        metric_lines.append(f'openstack_neutron_networks_total {len(networks)}')
    except Exception as e:
        metric_lines.append(f'# Error collecting Neutron networks: {str(e)}')

    try:
        subnets = list(conn.network.subnets())
        metric_lines.append(f'openstack_neutron_subnets_total {len(subnets)}')
    except Exception as e:
        metric_lines.append(f'# Error collecting Neutron subnets: {str(e)}')

    metric_lines.append("openstack_health_check_up 1")
    total_duration = (datetime.datetime.utcnow() - start_total).total_seconds()
    metric_lines.append(f'openstack_total_healthcheck_duration_seconds {total_duration:.3f}')

    return "\n".join(metric_lines) + "\n", 200, {"Content-Type": "text/plain"}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
