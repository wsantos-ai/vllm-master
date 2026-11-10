# Observabilidade do serviço (D-05, PD-38)

Liga a GPU, o vLLM e o Kong ao Prometheus e ao Grafana que o *cluster* já tem (kube-prometheus-stack, *release*
`monitoring`). **Autorizado pelo administrador em 2026-11-10.** Base: AC-38 (o Prometheus só coleta `ServiceMonitor` e
`PodMonitor` com `release: monitoring`). Nada do administrador é editado: os objetos novos ficam em `vllms`, com
`decisao=d-05`, e saem pelo O-desfazer.

| Bloco | O que faz | Manifesto |
|---|---|---|
| O1 | GPU (DCGM) e vLLM no Prometheus; abre a porta 8000 do vLLM ao *namespace* `monitoring` | [d05-observabilidade.yaml](../configs/d05-observabilidade.yaml) |
| O2 | Kong no Prometheus e *plugin* `prometheus` na rota (por ator, código HTTP, latência) | [d05-observabilidade-kong.yaml](../configs/d05-observabilidade-kong.yaml) |
| O-desfazer | Tira tudo isso | — |

Grafana: `http://192.168.50.162` (`LoadBalancer` do administrador). O que se vê lá não é evidência: a evidência é o log
dos blocos. Painéis ficam para depois do O1, quando os nomes das métricas estiverem no log.

**Disco do Prometheus:** Blocos P0, P1 e P-desfazer, no fim. NFS não é suportado pelo banco do Prometheus [F-051]; o disco é uma pasta local em `sabdiia03`.

## Enviar os manifestos (notebook, PowerShell)

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
$c = "C:\www\vllm-master\configs"
scp "$c\d05-observabilidade.yaml" "$c\d05-observabilidade-kong.yaml" `
  "$c\d05-prometheus-disco.yaml" "$c\d05-prometheus-disco-values.yaml" `
  "${u}@192.168.50.151:/home/utec/vllm-estudo/"
```

## Bloco O1 — GPU e vLLM no Prometheus (servidor `sabdiia01`, bash)

Cria dois `ServiceMonitor` (`d05-gpu-dcgm`, `d05-vllm`) e a `NetworkPolicy` `d05-vllm-metricas`. Não reinicia nenhum
*pod*, não toca no Kong. Antes, confere se o *chart* `dcgm-exporter` de `default` (AC-38) tem *pods*: um 2º DCGM nas
mesmas GPUs. Se tiver, o bloco segue (só lê o DCGM do GPU Operator) e o log mostra para levar ao administrador.

**Expectativa (escrita antes):** a validação aceita os 3 objetos; em até 2 min aparecem os *jobs* `nvidia-dcgm-exporter`
(3 alvos `up`) e `vllm-server` (3 alvos `up`); `count(DCGM_FI_DEV_GPU_UTIL)` = 3; dezenas de métricas `vllm:`; o *chart*
de `default` sem *pods* `[hipótese]`.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 O1: GPU e vLLM no Prometheus (PD-38)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  NS=vllms; M=d05-observabilidade.yaml
  [ -f $M ] || { echo "ABORTA: $M ausente; envie os manifestos"; exit 1; }
  sha256sum $M
  echo "### 0. o chart dcgm-exporter de default tem pods?   $(date +%T)"
  helm list -n default 2>&1 | grep -Ei '^NAME|dcgm'
  kubectl get all -n default -l app.kubernetes.io/name=dcgm-exporter -o wide
  for O in servicemonitor/d05-gpu-dcgm servicemonitor/d05-vllm networkpolicy/d05-vllm-metricas; do
    ROT=$(kubectl get $O -n $NS -o jsonpath='{.metadata.labels.decisao}' 2>/dev/null) \
      && [ "$ROT" != d-05 ] && { echo "ABORTA: $O já existe e não é do estudo"; exit 1; }
  done

  echo "### 1. validação no servidor, sem aplicar   $(date +%T)"
  kubectl apply --dry-run=server -f $M || { echo "ABORTA: o cluster recusou o manifesto"; exit 1; }

  echo "### 2. aplica   $(date +%T)"
  kubectl apply -f $M
  kubectl get servicemonitor,networkpolicy -n $NS

  echo "### 3. o Prometheus coleta? (espera o job do vLLM, até 5 min)   $(date +%T)"
  B="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:9090/proxy/api/v1"
  for i in $(seq 1 20); do   # o operador recarrega um objeto por vez: até 5 min (§9, 2026-11-10)
    kubectl get --raw "$B/targets?state=active" \
      | grep -q '"scrapePool":"serviceMonitor/vllms/d05-vllm/0' && break
    sleep 15; done; echo "esperou $((i*15)) s"
  kubectl get --raw "$B/targets?state=active" | tr ',' '\n' \
    | grep -E '"(scrapePool|health)"' | paste - - | grep -E 'd05|dcgm|vllm' | sort | uniq -c
  kubectl get --raw "$B/targets?state=active" | tr ',' '\n' | grep '"lastError":"[^"]' \
    | sort | uniq -c | head -5
  kubectl get --raw "${B}/query?query=count(DCGM_FI_DEV_GPU_UTIL)" | tr '{' '\n' | grep value
  echo "--- nomes das métricas do vLLM e da GPU"
  kubectl get --raw "$B/label/__name__/values" | tr ',' '\n' | grep -oE '"(vllm:|DCGM_)[^"]*"'
} 2>&1 | tee d05-o1-$(hostname -s)-$(date +%F-%H%M).log
```

### O1-diag — Por que o vLLM não entrou no Prometheus? (servidor `sabdiia01`, bash; só leitura)

O O1 de 2026-11-10 15:59 ([log](../logs-analysis/d05-o1-sabdiia01-2026-11-10-1559.log)) pôs a GPU no Prometheus (3 alvos
`up`), mas o `d05-vllm` não gerou nenhum alvo nem métrica `vllm:`. Este bloco confere, nesta ordem: se o operador aceitou
o `ServiceMonitor` (estado dele e log do operador), se o *job* está na configuração, se o Prometheus achou os *pods* e
descartou (alvos `dropped`), e as portas do `Service` e das `EndpointSlice` do `vllm-server`.

**Expectativa (escrita antes) `[hipótese]`:** o `Service` vivo tem a porta sem o nome `http`, ou o operador recusou o
`ServiceMonitor`; o log do operador ou o estado do objeto diz qual.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 O1-diag: vLLM fora do Prometheus (só leitura)"
  NS=vllms
  B="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:9090/proxy/api/v1"
  echo "### 1. o ServiceMonitor, com estado"
  kubectl get servicemonitor d05-vllm -n $NS -o yaml
  echo "### 2. o job está na configuração?"
  kubectl get --raw "$B/status/config" | tr '\\' '\n' | grep -o 'job_name: .*d05.*' | sort -u
  echo "### 3. alvos descartados do d05-vllm (quantos e por quê)"
  kubectl get --raw "$B/targets?state=dropped" | tr '{' '\n' | grep -c 'd05-vllm'
  kubectl get --raw "$B/targets?state=dropped" | tr '{' '\n' | grep 'd05-vllm' | head -2 \
    | tr ',' '\n' | grep -E 'service_name|endpointslice_port_name|endpoint_port_name|__address__'
  echo "### 4. portas do Service e das EndpointSlice"
  kubectl get svc vllm-server -n $NS -o jsonpath='{.metadata.labels}{"\n"}{.spec.ports}{"\n"}'
  kubectl get endpointslice -n $NS -l kubernetes.io/service-name=vllm-server \
    -o jsonpath='{range .items[*]}{.metadata.name} {.ports} {.endpoints[*].addresses}{"\n"}{end}'
  echo "### 5. log do operador e do Prometheus (30 min)"
  kubectl logs -n monitoring deploy/monitoring-kube-prometheus-operator --since=30m 2>&1 \
    | grep -iE 'd05|vllms|reject|invalid' | tail -10 | cut -c1-300
  kubectl logs -n monitoring prometheus-monitoring-kube-prometheus-prometheus-0 -c prometheus \
    --since=30m 2>&1 | grep -iE 'error|warn|vllms' | tail -10 | cut -c1-300
} 2>&1 | tee d05-o1-diag-$(hostname -s)-$(date +%F-%H%M).log
```

**Resultado (2026-11-10 16:18, [log](../logs-analysis/d05-o1-diag-sabdiia01-2026-11-10-1618.log)):** o operador aceitou o `d05-vllm`, o *job* está na
configuração, `Service` e `EndpointSlice` têm a porta `http` e os 3 *pods*. O Prometheus começou a descobrir os alvos às
16:01:36, 2 min 14 s depois do `apply` e 14 s depois da conferência do O1: o `sleep 120` foi curto (§9). O diagnóstico não
consultou os alvos ativos; o O1-confere fecha.

### O1-confere — O vLLM está no Prometheus? (servidor `sabdiia01`, bash; só leitura)

**Expectativa (escrita antes):** `serviceMonitor/vllms/d05-vllm/0` com 3 alvos `up`; dezenas de métricas `vllm:`. Se
`down`, o `lastError` diz se é a `NetworkPolicy` (*timeout*) ou o caminho.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 O1-confere: vLLM no Prometheus (só leitura)"
  B="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:9090/proxy/api/v1"
  kubectl get --raw "$B/targets?state=active" | tr ',' '\n' \
    | grep -E '"(scrapePool|health)"' | paste - - | grep d05 | sort | uniq -c
  kubectl get --raw "$B/targets?state=active" | tr ',' '\n' | grep -E '"(scrapeUrl|lastError)"' \
    | paste - - | grep ':8000/' | cut -c1-250
  echo "--- métricas do vLLM"
  kubectl get --raw "$B/label/__name__/values" | tr ',' '\n' | grep -oE '"vllm:[^"]*"'
} 2>&1 | tee d05-o1-confere-$(hostname -s)-$(date +%F-%H%M).log
```

**Resultado (2026-11-10 16:30, [log](../logs-analysis/d05-o1-confere-sabdiia01-2026-11-10-1630.log)):** 3 alvos `up` do vLLM e 3 da GPU, sem erro; 97 métricas `vllm:` (AC-39).

### O1-limpeza — Remove o `dcgm-exporter` quebrado de `default` (servidor `sabdiia01`, bash)

**Autorizado pelo administrador em 2026-11-10** (liberou o estudo para mexer no ambiente). O *chart*
`dcgm-exporter-2.4.0` (*release* `dcgm-exporter-1793243508`, instalado em 2026-10-29) está em `CrashLoopBackOff` nos 3
nós, ~3.500 reinícios cada, e não serve a nada: o DCGM do GPU Operator já é coletado pelo O1
([log](../logs-analysis/d05-o1-sabdiia01-2026-11-10-1559.log)). O bloco guarda os *values* e o manifesto do *release*,
desinstala e confere que a GPU segue coletada. Desfazer: `kubectl apply -f` no manifesto guardado.

**Resultado (2026-11-10 16:19, [log](../logs-analysis/d05-o1-limpeza-sabdiia01-2026-11-10-1619.log)):** desinstalado (DaemonSet, Service, ServiceAccount, ServiceMonitor); nada sobrou em `default`; GPU segue coletada (`count` = 3). Cópia em `sabdiia01`: `/home/utec/vllm-estudo/dcgm-default-manifest-2026-11-10-1619.yaml`.

**Expectativa (escrita antes):** `helm uninstall` sem erro; nenhum objeto do *release* em `default` (DaemonSet, Service,
ServiceMonitor); `count(DCGM_FI_DEV_GPU_UTIL)` segue 3; os 3 `nvidia-dcgm-exporter` do GPU Operator seguem `Running`.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 O1-limpeza: remove dcgm-exporter de default"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  R=dcgm-exporter-1793243508; NS=default; TS=$(date +%F-%H%M)
  helm status $R -n $NS >/dev/null 2>&1 || { echo "release $R não existe: nada a fazer"; exit 0; }
  helm list -n $NS | grep -E "^NAME|$R"
  echo "### 1. cópia antes   $(date +%T)"
  helm get values $R -n $NS -o yaml > dcgm-default-values-$TS.yaml
  helm get manifest $R -n $NS > dcgm-default-manifest-$TS.yaml
  wc -l dcgm-default-values-$TS.yaml dcgm-default-manifest-$TS.yaml
  grep -E '^kind:' dcgm-default-manifest-$TS.yaml | sort | uniq -c
  echo "### 2. desinstala   $(date +%T)"
  helm uninstall $R -n $NS --wait --timeout 3m \
    || { echo "FALHOU o uninstall; traga o log"; exit 1; }
  echo "### 3. sobrou algo?   $(date +%T)"
  sleep 15
  kubectl get all,servicemonitor -n $NS -l app.kubernetes.io/instance=$R
  echo "### 4. a GPU segue coletada?   $(date +%T)"
  kubectl get pods -n gpu-operator -l app=nvidia-dcgm-exporter -o wide
  B="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:9090/proxy/api/v1"
  kubectl get --raw "$B/query?query=count(DCGM_FI_DEV_GPU_UTIL)" | tr '{' '\n' | grep value
} 2>&1 | tee d05-o1-limpeza-$(hostname -s)-$(date +%F-%H%M).log
```

## Bloco O2 — Kong no Prometheus e *plugin* na rota (servidor `sabdiia01`, bash)

Cria o `PodMonitor` `d05-kong` e o `KongPlugin` `d05-prometheus`, e acrescenta o *plugin* à rota (mantém os que já
estão). Vale para todas as aplicações e atores. **Regra do AC-37:** depois deste bloco, rode `teste-kong-ia.js` do
notebook; o caso 4 (*streaming*) tem de dar `OK`. Os casos 2 e 7 falham desde o H-desfazer (sem *guard*, voltam `200`):
isso é esperado. Se o 4 falhar, rode o O-desfazer na hora.

**Expectativa (escrita antes):** validação aceita; rota com `d05-key-auth,d05-rate-limit,d05-prometheus`; *job*
`podMonitor/vllms/d05-kong/0` com 1 alvo `up`; depois da 1ª requisição pela rota, métricas `kong_http_requests_total` e
`kong_request_latency_ms` com `consumer` `[hipótese: nomes não conferidos no código]`; *streaming* OK.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 O2: Kong no Prometheus (PD-38)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  NS=vllms; M=d05-observabilidade-kong.yaml
  [ -f $M ] || { echo "ABORTA: $M ausente; envie os manifestos"; exit 1; }
  sha256sum $M
  for O in podmonitor/d05-kong kongplugin/d05-prometheus; do
    ROT=$(kubectl get $O -n $NS -o jsonpath='{.metadata.labels.decisao}' 2>/dev/null) \
      && [ "$ROT" != d-05 ] && { echo "ABORTA: $O já existe e não é do estudo"; exit 1; }
  done
  ANTES=$(kubectl get ingress vllm-server -n $NS \
    -o jsonpath='{.metadata.annotations.konghq\.com/plugins}')
  echo "plugins na rota antes: $ANTES"
  [ -n "$ANTES" ] || { echo "ABORTA: rota sem anotação; rode antes o G1 e o C"; exit 1; }

  echo "### 1. validação no servidor, sem aplicar   $(date +%T)"
  kubectl apply --dry-run=server -f $M || { echo "ABORTA: o cluster recusou o manifesto"; exit 1; }

  echo "### 2. aplica e liga à rota   $(date +%T)"
  kubectl apply -f $M
  case ",$ANTES," in *,d05-prometheus,*) P=$ANTES ;; *) P=$ANTES,d05-prometheus ;; esac
  kubectl annotate ingress vllm-server -n $NS --overwrite konghq.com/plugins=$P

  echo "### 3. o Kong aceitou?   $(date +%T)"
  sleep 20
  kubectl get ingress vllm-server -n $NS \
    -o jsonpath='plugins na rota: {.metadata.annotations.konghq\.com/plugins}{"\n"}'
  kubectl get events -n $NS --sort-by=.lastTimestamp \
    | grep -viE 'pulled|scheduled|created|started|probe' | tail -5 | cut -c1-200
  kubectl logs -n kong deploy/kong-controller --since=2m 2>&1 \
    | grep -iE 'error|prometheus' | tail -5

  echo "### 4. de 01, sem chave: 401 (a rota segue de pé)   $(date +%T)"
  curl -sk -o /dev/null -w 'HTTP %{http_code}\n' --max-time 10 -X POST \
    -H 'Content-Type: application/json' -d '{}' https://192.168.50.161/vllm/v1/chat/completions

  echo "### 5. o Prometheus coleta o Kong? (espera o job, até 5 min)   $(date +%T)"
  B="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:9090/proxy/api/v1"
  for i in $(seq 1 20); do   # o operador recarrega um objeto por vez: até 5 min (§9, 2026-11-10)
    kubectl get --raw "$B/targets?state=active" \
      | grep -q '"scrapePool":"podMonitor/vllms/d05-kong/0' && break
    sleep 15; done; echo "esperou $((i*15)) s"
  kubectl get --raw "$B/targets?state=active" | tr ',' '\n' \
    | grep -E '"(scrapePool|health)"' | paste - - | grep d05-kong | sort | uniq -c
  echo "--- nomes das métricas do Kong"
  kubectl get --raw "$B/label/__name__/values" | tr ',' '\n' | grep -oE '"kong_[^"]*"'
} 2>&1 | tee d05-o2-$(hostname -s)-$(date +%F-%H%M).log
```

**Resultado (2026-11-10 16:34, [log](../logs-analysis/d05-o2-sabdiia01-2026-11-10-1634.log)):** rota com os 3 *plugins*, `401` sem chave, alvo do Kong `up` em 45 s, 17 métricas `kong_` (`kong_http_requests_total`, `kong_request_latency_ms`, `kong_kong_latency_ms`, `kong_bandwidth_bytes`). Os erros `TLS handshake error from 10.244.182.128` do *controller* começam antes do `apply` (19:34:12 UTC = 16:34:12): não vêm do *plugin*.

Depois, do notebook (Git Bash; o teste já usa a chave do `.env` da aplicação):

```bash
cd /c/www/vllm-app
NODE_TLS_REJECT_UNAUTHORIZED=0 node test/teste-kong-ia.js
```

**Teste (2026-11-10 16:39, [log](../logs-analysis/kong-ia-wsantosdell-2026-11-10-1639.log)):** caso 4 (*streaming*) `OK`, 1º pedaço em 0,064 s (AC-40).

## Bloco O-desfazer — Tira os objetos de observabilidade (servidor `sabdiia01`, bash)

Volta a rota aos *plugins* sem `d05-prometheus` e apaga os 5 objetos. O Prometheus para de coletar em ~2 min.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 O-desfazer"
  NS=vllms
  A=$(kubectl get ingress vllm-server -n $NS \
    -o jsonpath='{.metadata.annotations.konghq\.com/plugins}')
  P=$(echo ",$A," | sed 's/,d05-prometheus,/,/; s/^,//; s/,$//')
  kubectl annotate ingress vllm-server -n $NS --overwrite konghq.com/plugins=$P
  kubectl delete kongplugin d05-prometheus -n $NS --ignore-not-found
  kubectl delete podmonitor d05-kong -n $NS --ignore-not-found
  kubectl delete servicemonitor d05-gpu-dcgm d05-vllm -n $NS --ignore-not-found
  kubectl delete networkpolicy d05-vllm-metricas -n $NS --ignore-not-found
  sleep 20; kubectl get ingress vllm-server -n $NS \
    -o jsonpath='plugins na rota: {.metadata.annotations.konghq\.com/plugins}{"\n"}'
  kubectl get servicemonitor,podmonitor,networkpolicy -n $NS
} 2>&1 | tee d05-o-desfazer-$(hostname -s)-$(date +%F-%H%M).log
```

## Trazer os logs (notebook, PowerShell)

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
scp "${u}@192.168.50.151:/home/utec/vllm-estudo/d05-[op]*.log" C:\www\vllm-master\logs-analysis\
# o log do P0 fica em sabdiia03:
scp "${u}@192.168.50.150:/home/utec/vllm-estudo/d05-p0-*.log" C:\www\vllm-master\logs-analysis\
```
