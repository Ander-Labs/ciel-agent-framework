# Multi-tenancy — Guía arquitectónica

## Criterio de avance relevant
Deploy enterprise en k8s/VPS con tracing, MCP, ACP, adapters funcionales y aislamiento real por tenant.

---

## Objetivo
Permitir que un mismo despliegue sirva a mas de un tenant sin fugas de datos, credenciales, contexto ni trazas.

---

## Alcance inicial

- Proveedores de modelos: `ProviderConfig.tenant`, aislar credenciales y modelos visibles por tenant.
- Runtime: propagar `tenant_id` en metadatos de sesión, requests y tool calls.
- Observabilidad: incluir `tenant_id` en `AuditEvent` y trazas.
- Seguridad: políticas de aprobación, redacción y auditoría evaluadas en contexto del tenant.
- Gateway/despliegue: routing por tenant, namespaces o headers, segun infraestructura objetivo.

---

## Reglas basicas

1. El tenant se resuelve temprano y se propaga explicitamente, nunca por inferencia.
2. Ningun componente puede leer/escribir fuera del tenant asignado, salvo operadores autorizados.
3. Las credenciales, logs y resultados de tools se marcan con `tenant_id`.
4. Si falta `tenant_id`, se ejecuta en modo tomador/por defecto sin mezclar datos de otros tenants.
5. El aislamiento se verifica en runtime y en pruebas.

---

## Modelo basico

### Atributos por tenant
- `tenant_id`: identificador estable.
- `name`, `env`, `quota`, `policies`, `allowed_providers`.

### Contexto de ejecucion
- ID de sesion ligado a un tenant.
- Tool calls con metadata `tenant_id`.
- Trazas con `trace_id`, `span_id`, `tenant_id`.

---

## Aislamiento por capa

### Proveedores (`ciel.providers`)
- Usar `ProviderConfig.tenant`.
- `ProviderRegistry` permite registrar por tenant.
- Http headers/metadata cuando corresponda.

### Runtime (`ciel.runtime`)
- Incluir `tenant_id` en `ChatRequest.extra`.
- Dispatchers pueden filtrar tools por tenant.
- Memoria/contexto separado por `tenant_id`.

### Seguridad (`ciel.security`)
- `ApprovalRequest` con `tenant` y validacion por tenant.
- Redaccion PII con reglas diferenciadas por tenant.
- Auditoria inyecta `tenant_id` en eventos.

### Observabilidad (`ciel.observability`)
- Sinks soportan filtrado por tenant.
- Trazas exportables a backend enterprise.

### Gateway (`ciel.gateway`)
- Mapping tenant -> namespace/provider/header.
- Auth, API keys, quotas por tenant.
- Endpoints protegidos por tenant.

---

## Mecanismos de despliegue

- K8s: namespaces, quotas, RBAC, secrets por tenant.
- VPS: procesos/puertos por tenant, reverse proxy con rutas o headers.
- Adapters: encolar por tenant, serializar tenant en mensajes.

---

## Checklist multi-tenant

### Producto
- [ ] `tenant_id` por defecto en todos los contratos relevantes.
- [ ] Pruebas de aislamiento por tenant en providers, runtime y security.
- [ ] Auditoria con tenant metadata verificada.
- [ ] Documento de despliegue con separacion por tenant.
- [ ] Criterio de avance medido en trazas, MCP, ACP y adapter sin mezclas.

---

## Documentacion esperada

- `docs/design/multi_tenancy.md`: este documento.
- `docs/dev/TODO.md`: items pendientes y decisiones.
- `docs/ROADMAP.md`: criterios por fase.
