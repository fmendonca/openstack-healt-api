# OpenStack Health API

Esta aplicação expõe um serviço de health check e métricas para ambientes OpenStack, ideal para dashboards no Grafana e alertas no Prometheus.

---

## 🔧 Funcionalidades

- `/health` — Página HTML detalhada com status de cada serviço e endpoint.
- `/metrics` — Métricas Prometheus com:
  - Status por serviço e endpoint
  - Tempo de resposta (latência)
  - Contadores por status (ok, error, unreachable)
  - Tempo total da checagem

---

## 🚀 Como usar

### 🐳 Build da imagem (UBI 9 + Python 3.9)

```bash
podman build -t openstack-health-api .
