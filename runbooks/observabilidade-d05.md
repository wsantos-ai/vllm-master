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

## Disco local do Prometheus (Blocos P0, P1, P-desfazer)

**Autorizado pelo administrador em 2026-11-10** (liberou o estudo para mexer no ambiente). O banco do Prometheus está em
`emptyDir` e some quando o *pod* reinicia (AC-38); NFS, o único armazenamento do *cluster*, não é suportado pelo
Prometheus [F-051]. Estes blocos dão a ele uma pasta em `/` de `sabdiia03` (534 G livres em 2026-10-28), servida como
`PersistentVolume` `local` [F-052], e pedem o disco pelo Helm, para um `helm upgrade` futuro não desfazer:

- [d05-prometheus-disco.yaml](../configs/d05-prometheus-disco.yaml): `StorageClass` `d05-local-prometheus` e PV
  `d05-prometheus-sabdiia03` (50 Gi, `/var/lib/d05-prometheus`, só em 03, `Retain`);
- [d05-prometheus-disco-values.yaml](../configs/d05-prometheus-disco-values.yaml): `storageSpec` com esse PV e
  `retentionSize: 40GiB` [F-053]; a retenção de 10 dias não muda.

Custos: **o histórico atual (desde o último reinício) se perde**, porque o *pod* do Prometheus é recriado com o disco
novo; e o Prometheus fica **preso a `sabdiia03`**: se 03 cair, ele para até 03 voltar. Grafana e Alertmanager ficam como
estão (os painéis vão em `ConfigMap`, PD-38).

### P0 — Cria a pasta em `sabdiia03` (servidor `sabdiia03`, bash como `root`, depois de `sudo -i`; sem `kubectl`)

O Prometheus roda como usuário 1000, grupo 2000 (padrão do *chart*, [F-053]). Com SELinux ativo, a pasta recebe o tipo
`container_file_t`, ou o contêiner não escreve nela `[hipótese: containerd com SELinux]`.

**Expectativa (escrita antes):** pasta criada, dono `1000:2000`, modo `drwxrwx---`; `/` com mais de 500 G livres.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 P0: pasta do Prometheus"
  [ "$(hostname -s)" = sabdiia03 ] || { echo "ABORTA: este bloco é para sabdiia03"; exit 1; }
  [ "$(id -u)" = 0 ] || { echo "ABORTA: rode como root (sudo -i)"; exit 1; }
  D=/var/lib/d05-prometheus
  [ -d $D ] && echo "AVISO: $D já existe; conteúdo:" && ls -la $D | head
  mkdir -p $D && chown 1000:2000 $D && chmod 0770 $D
  S=$(getenforce 2>/dev/null || echo ausente); echo "SELinux: $S"
  [ "$S" = Enforcing ] || [ "$S" = Permissive ] && chcon -t container_file_t $D
  ls -ldZ $D; df -h /
} 2>&1 | tee d05-p0-$(hostname -s)-$(date +%F-%H%M).log
```

### P1 — PV e `helm upgrade` do *release* `monitoring` (servidor `sabdiia01`, bash)

Mesmo jeito do K2 (`acesso-aplicacoes-d05.md`): mesma versão do *chart*, `--reuse-values`, só os campos do arquivo de
*values*. Antes, guarda os *values* atuais (podem ter a senha do Grafana: o arquivo fica com modo `600`, fora do log) e o
objeto `Prometheus`.

**Expectativa (escrita antes):** *release* `monitoring` revisão 1 → 2; o operador recria o *StatefulSet* do Prometheus
(o `volumeClaimTemplates` de um *StatefulSet* não muda no lugar) `[hipótese]`; PVC
`prometheus-monitoring-kube-prometheus-prometheus-db-prometheus-monitoring-kube-prometheus-prometheus-0` `Bound` ao PV
`d05-prometheus-sabdiia03`; *pod* `2/2` em `sabdiia03` em até 5 min; os mesmos alvos `up` de antes (GPU, vLLM, Kong);
Grafana e Alertmanager sem reinício.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 P1: disco local do Prometheus (PD-38)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  NS=monitoring; REL=monitoring; TS=$(date +%F-%H%M)
  M=d05-prometheus-disco.yaml; V=d05-prometheus-disco-values.yaml
  for F in $M $V; do [ -f $F ] || { echo "ABORTA: $F ausente; envie os manifestos"; exit 1; }; done
  sha256sum $M $V
  CH=$(helm list -n $NS -o json | grep -o '"chart":"kube-prometheus-stack-[0-9.]*"' | cut -d'"' -f4)
  echo "chart: $CH"
  [ "$CH" = kube-prometheus-stack-91.3.0 ] || { echo "ABORTA: chart inesperado"; exit 1; }
  helm history $REL -n $NS | tail -3
  echo "### 1. cópia antes   $(date +%T)"
  ( umask 077; helm get values $REL -n $NS -o yaml > monitoring-values-antes-$TS.yaml )
  kubectl get prometheus -n $NS -o yaml > monitoring-prometheus-cr-antes-$TS.yaml
  ls -l monitoring-*-antes-$TS.yaml
  kubectl get pods -n $NS -o wide

  echo "### 2. StorageClass e PV   $(date +%T)"
  kubectl apply --dry-run=server -f $M || { echo "ABORTA: o cluster recusou o manifesto"; exit 1; }
  kubectl apply -f $M
  kubectl get storageclass d05-local-prometheus; kubectl get pv d05-prometheus-sabdiia03

  echo "### 3. helm upgrade (mesma versão, --reuse-values)   $(date +%T)"
  REPO=https://prometheus-community.github.io/helm-charts
  helm upgrade $REL kube-prometheus-stack --repo $REPO \
    --version 91.3.0 -n $NS --reuse-values -f $V --wait --timeout 10m \
    || { echo "FALHOU o helm upgrade; traga o log (desfazer: P-desfazer)"; exit 1; }
  helm history $REL -n $NS | tail -2

  echo "### 4. o Prometheus subiu com o disco?   $(date +%T)"
  for i in $(seq 1 30); do
    kubectl get pvc -n $NS 2>/dev/null | grep -q 'd05-local-prometheus' && break; sleep 10; done
  kubectl rollout status statefulset/prometheus-monitoring-kube-prometheus-prometheus -n $NS \
    --timeout=5m
  kubectl get pvc -n $NS; kubectl get pv d05-prometheus-sabdiia03
  kubectl get pods -n $NS -o wide
  kubectl get prometheus -n $NS -o yaml | grep -E '^    (retention|retentionSize):'
  kubectl get events -n $NS --sort-by=.lastTimestamp | tail -8 | cut -c1-200

  echo "### 5. coleta de volta? (espera os alvos, até 5 min)   $(date +%T)"
  B="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:9090/proxy/api/v1"
  for i in $(seq 1 20); do
    kubectl get --raw "$B/targets?state=active" 2>/dev/null | grep -q 'd05-kong' && break
    sleep 15; done; echo "esperou $((i*15)) s"
  kubectl get --raw "$B/targets?state=active" | tr ',' '\n' \
    | grep -E '"(scrapePool|health)"' | paste - - | grep d05 | sort | uniq -c
  kubectl get --raw "$B/status/tsdb" | tr ',' '\n' | grep -E 'numSeries|headStats' | head -3
} 2>&1 | tee d05-p1-$(hostname -s)-$(date +%F-%H%M).log
```

Depois, no `sabdiia03` (como `root`), confira que o banco está na pasta: `ls -la /var/lib/d05-prometheus` (espera-se
`prometheus-db/` com `wal/` dentro) `[não executado]`.

**Resultado (2026-11-10):** P0 OK às 16:58 ([log](../logs-analysis/d05-p0-sabdiia03-2026-11-10-1658.log)): pasta
`1000:2000` (o 1000 é o `utec` do *host*), SELinux `Disabled`, `/` com 445 G livres. **P1 falhou às 17:01**
([log](../logs-analysis/d05-p1-sabdiia01-2026-11-10-1701.log)): `StorageClass` e PV criados (PV `Available`), mas o
`helm upgrade` parou em `conflict with "Freelens" using v1: .spec.type` no `Service` `monitoring-grafana`. O
`LoadBalancer` do Grafana (`192.168.50.162`) foi posto à mão pelo Freelens, não pelo Helm: os *values* do *release* têm
5 bytes (`null` `[hipótese]`, *chart* com os padrões, `ClusterIP`). O Helm aplica pelo servidor (*server-side apply*) e
recusa mudar um campo de outro dono. Forçar voltaria o Grafana a `ClusterIP` e tiraria o IP externo.

### P1-diag — Estado do *release* e o que foi editado à mão (servidor `sabdiia01`, bash; só leitura)

Confere: versão do Helm e as opções de conflito do `upgrade`; se a falha deixou revisão nova e se o objeto `Prometheus`
mudou; a diferença entre o manifesto do Helm (revisão 1) e o que está no *cluster* (`kubectl diff`), que mostra toda
edição feita fora do Helm; os donos dos campos do `Service` do Grafana; e o padrão do `service` no *subchart* do Grafana.

**Expectativa (escrita antes) `[hipótese]`:** Helm 4; revisão 2 `failed`; objeto `Prometheus` sem `storage`; a única
diferença relevante é `type: LoadBalancer` no `Service` do Grafana; padrão do *subchart* `service.type: ClusterIP`.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 P1-diag: release monitoring (só leitura)"
  NS=monitoring; REL=monitoring
  echo "### 1. Helm e opções de conflito"
  helm version --short
  helm upgrade --help | grep -iE 'server-side|force|conflict' | cut -c1-160
  echo "### 2. revisões, objeto Prometheus, pods, PV"
  helm history $REL -n $NS | tail -3
  kubectl get prometheus -n $NS -o yaml | grep -E '^    (retention|retentionSize|storage):' -A3
  kubectl get pods -n $NS -o wide | cut -c1-120
  kubectl get pv d05-prometheus-sabdiia03
  echo "### 3. o que difere do manifesto do Helm (revisão 1): edições fora do Helm"
  helm get manifest $REL -n $NS --revision 1 > monitoring-manifest-rev1.yaml
  kubectl diff -f monitoring-manifest-rev1.yaml 2>&1 | grep -E '^(diff|[-+] )' \
    | grep -vE 'generation:|resourceVersion|creationTimestamp|^\+\+\+|^---' | head -80
  echo "### 4. donos dos campos do Service do Grafana"
  kubectl get svc monitoring-grafana -n $NS --show-managed-fields -o yaml \
    | grep -E 'manager:|operation:|f:type|f:loadBalancer|f:ports|f:annotations' | head -30
  echo "### 5. padrão do service no subchart do Grafana (91.3.0)"
  T=$(mktemp -d); REPO=https://prometheus-community.github.io/helm-charts
  helm pull kube-prometheus-stack --repo $REPO --version 91.3.0 --untar -d $T >/dev/null
  grep -n -A6 '^service:' $T/kube-prometheus-stack/charts/grafana/values.yaml | head -12
  grep -n '^version:' $T/kube-prometheus-stack/charts/grafana/Chart.yaml; rm -rf $T
} 2>&1 | tee d05-p1-diag-$(hostname -s)-$(date +%F-%H%M).log
```

**Resultado (2026-11-10 17:07, [log](../logs-analysis/d05-p1-diag-sabdiia01-2026-11-10-1707.log)):** Helm `v4.1.1`.
**A revisão 2 ficou `failed`, mas o upgrade aplicou o resto antes de parar** (AC-41): o objeto `Prometheus` já tem
`retentionSize: 40GiB` e o `storage`, o *pod* do Prometheus foi recriado (~17:03) com o PV `Bound`, e o Grafana também
(~17:01, agora em `sabdiia02`), porque o *checksum* do secret no *Deployment* mudou. A única edição fora do Helm é o
`type: LoadBalancer` do `Service` do Grafana (dono `Freelens`, `Update`). Padrão do *subchart* `grafana` `13.2.4`:
`service.type: ClusterIP`. A senha do Grafana vem do secret existente, se houver (`lookup`), senão é gerada ao acaso
(`randAlphaNum 40`, *template* `grafana.password` do *chart* `grafana-13.2.4` [F-054]).

### P1b — Completa o *upgrade* com o `LoadBalancer` do Grafana no Helm (servidor `sabdiia01`, bash)

Os *values* passam a declarar `grafana.service.type: LoadBalancer`, o mesmo valor que já está no *cluster*: o Helm não
muda o campo e não há conflito `[hipótese: server-side apply só acusa conflito quando o valor muda]`. O bloco mostra antes
quando o secret do Grafana foi gravado (sem o conteúdo), para saber se a senha mudou às 17:01.

**Expectativa (escrita antes):** revisão 3 `deployed`; o `Service` do Grafana segue `LoadBalancer` `192.168.50.162`;
Prometheus e Grafana **sem** novo reinício (`AGE` maior que antes); PVC `Bound`; alvos `d05-*` `up`.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 P1b: upgrade com o LoadBalancer do Grafana"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  NS=monitoring; REL=monitoring; V=d05-prometheus-disco-values.yaml
  [ -f $V ] || { echo "ABORTA: $V ausente; envie os manifestos"; exit 1; }
  sha256sum $V
  grep -q 'type: LoadBalancer' $V || { echo "ABORTA: $V antigo; envie o novo"; exit 1; }
  echo "### 1. antes: secret do Grafana (quem gravou e quando, sem o conteúdo), pods, serviço"
  kubectl get secret monitoring-grafana -n $NS -o \
    jsonpath='{range .metadata.managedFields[*]}{.manager} {.operation} {.time}{"\n"}{end}'
  kubectl get pods -n $NS -o wide | cut -c1-120
  kubectl get svc monitoring-grafana -n $NS
  echo "### 2. helm upgrade   $(date +%T)"
  REPO=https://prometheus-community.github.io/helm-charts
  helm upgrade $REL kube-prometheus-stack --repo $REPO \
    --version 91.3.0 -n $NS --reuse-values -f $V --wait --timeout 10m \
    || { echo "FALHOU o helm upgrade; traga o log"; exit 1; }
  helm history $REL -n $NS | tail -3 | cut -c1-120
  echo "### 3. depois   $(date +%T)"
  sleep 20
  kubectl get pods -n $NS -o wide | cut -c1-120
  kubectl get svc monitoring-grafana -n $NS
  kubectl get pvc -n $NS
  kubectl get secret monitoring-grafana -n $NS -o \
    jsonpath='{range .metadata.managedFields[*]}{.manager} {.operation} {.time}{"\n"}{end}'
  echo "### 4. coleta e banco   $(date +%T)"
  B="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:9090/proxy/api/v1"
  kubectl get --raw "$B/targets?state=active" | tr ',' '\n' \
    | grep -E '"(scrapePool|health)"' | paste - - | grep d05 | sort | uniq -c
  for Q in prometheus_tsdb_head_series prometheus_tsdb_wal_storage_size_bytes; do
    echo "$Q: $(kubectl get --raw "$B/query?query=$Q" | grep -oE '"[0-9.e+]+"\]' | head -1)"
  done
} 2>&1 | tee d05-p1b-$(hostname -s)-$(date +%F-%H%M).log
```

**Resultado (2026-11-10 17:13, [log](../logs-analysis/d05-p1b-sabdiia01-2026-11-10-1713.log)):** revisão 3 `deployed`, sem conflito; Grafana segue em `192.168.50.162`; nenhum *pod* reiniciou; PVC `Bound`; alvos `d05-*` `up`; secret do Grafana gravado só em 2026-09-14 (a senha não mudou). Disco resolvido.

Se a senha do Grafana parar de funcionar, o secret foi regravado às 17:01 e o banco do Grafana, sem disco, começou do
zero com ela. Quem tem acesso lê a senha nova direto no servidor, **fora de qualquer log**:
`kubectl get secret monitoring-grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d; echo`.

### P-desfazer — Volta o Prometheus ao `emptyDir` (servidor `sabdiia01`, bash)

`helm rollback` para a revisão anterior ao P1 e apaga PVC, PV e `StorageClass`. Os dados ficam em
`/var/lib/d05-prometheus` de 03 (`Retain`); apague à mão se não forem servir.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 P-desfazer"
  NS=monitoring; REL=monitoring
  helm history $REL -n $NS | tail -3
  ULT=$(helm history $REL -n $NS -o json | grep -o '"revision":[0-9]*' | tail -1 | cut -d: -f2)
  ANT=$((ULT - 1))
  echo "rollback para a revisão $ANT"
  helm rollback $REL $ANT -n $NS --wait --timeout 10m || { echo "FALHOU o rollback"; exit 1; }
  kubectl rollout status statefulset/prometheus-monitoring-kube-prometheus-prometheus -n $NS \
    --timeout=5m
  kubectl get pvc -n $NS -o name | grep prometheus-db | xargs -r kubectl delete -n $NS
  kubectl delete pv d05-prometheus-sabdiia03 --ignore-not-found
  kubectl delete storageclass d05-local-prometheus --ignore-not-found
  kubectl get pods,pvc -n $NS -o wide
} 2>&1 | tee d05-p-desfazer-$(hostname -s)-$(date +%F-%H%M).log
```

## Painéis do Grafana (Bloco G, G-desfazer)

Dois painéis em JSON versionado, em [configs/grafana/](../configs/grafana/):

| Arquivo | Painel no Grafana | O que mostra |
|---|---|---|
| `d05-painel-vllm-gpu.json` | **D-05 — vLLM e GPU** | por réplica: rodando e na fila, *KV cache*, preempções, TTFT e ITL (p50/p95), fila/*prefill*/*decode* (p95), *tokens*/s, concluídas/min, *prefix cache*; por nó: *clock*, temperatura, potência, uso, *tensor cores*, memória |
| `d05-painel-kong.json` | **D-05 — Kong (rota do vLLM)** | requisições/min por código HTTP e por ator, erros por ator, latência p95 (total, vLLM, Kong), banda por ator |

Nomes de métricas tirados dos logs (AC-39, AC-40) e do código do Kong 3.9.0 [F-049]: `kong_http_requests_total` e
`kong_bandwidth_bytes` têm o rótulo `consumer`; os histogramas de latência, não (latência só por rota). Cada arquivo vira
um `ConfigMap` em `vllms` com o rótulo `grafana_dashboard: "1"`, que o *sidecar* do Grafana procura em todos os
*namespaces* (`searchNamespace: ALL`, *chart* 91.3.0 [F-053]); a fonte de dados é escolhida no topo do painel (padrão
`Prometheus`, `uid: prometheus`). **Editar no Grafana não persiste** (`allowUiUpdates: false` [F-053], e o Grafana está
sem disco): mude o JSON no repositório e rode o G de novo.

Envie os arquivos (notebook, PowerShell):

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
$g = "C:\www\vllm-master\configs\grafana"
scp "$g\d05-painel-vllm-gpu.json" "$g\d05-painel-kong.json" "${u}@192.168.50.151:/home/utec/vllm-estudo/"
```

### Bloco G — Aplica os painéis e confere cada consulta (servidor `sabdiia01`, bash)

**Expectativa (escrita antes):** dois `ConfigMap` `d05-painel-*` criados; o *sidecar* registra os dois arquivos em até
1 min; cada uma das 30 consultas devolve ao menos 1 série, menos as que dependem de tráfego desde 17:03 (reinício do
Prometheus): `histogram_quantile` sem requisição na janela devolve série com `NaN`, que conta como série.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 G: painéis do Grafana (PD-38)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  NS=vllms
  command -v python3 >/dev/null || { echo "ABORTA: sem python3"; exit 1; }
  for N in vllm-gpu kong; do
    F=d05-painel-$N.json
    [ -f $F ] || { echo "ABORTA: $F ausente; envie os arquivos"; exit 1; }
    python3 -m json.tool $F >/dev/null || { echo "ABORTA: $F não é JSON válido"; exit 1; }
    sha256sum $F
  done

  echo "### 1. ConfigMaps   $(date +%T)"
  for N in vllm-gpu kong; do
    kubectl create configmap d05-painel-$N -n $NS --from-file=d05-painel-$N.json \
      --dry-run=client -o yaml \
      | kubectl label --local -f - grafana_dashboard=1 decisao=d-05 -o yaml \
      | kubectl apply --server-side --field-manager=d05 -f -
  done
  kubectl get configmap -n $NS -l grafana_dashboard=1 --show-labels

  echo "### 2. cada consulta no Prometheus (nº de séries | consulta)   $(date +%T)"
  B="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:9090/proxy/api/v1"
  for N in vllm-gpu kong; do
    python3 -c 'import json,sys,urllib.parse as u
for p in json.load(open(sys.argv[1]))["panels"]:
    for t in p.get("targets", []): print(u.quote(t["expr"], safe=""))' d05-painel-$N.json
  done | while read -r E; do
    S=$(kubectl get --raw "$B/query?query=$E" | grep -o '"metric"' | wc -l)
    D=$(python3 -c 'import sys,urllib.parse as u; print(u.unquote(sys.argv[1]))' "$E")
    printf '%3s | %s\n' "$S" "$(echo "$D" | cut -c1-90)"
  done

  echo "### 3. o sidecar do Grafana pegou?   $(date +%T)"
  sleep 60
  kubectl logs -n monitoring deploy/monitoring-grafana --all-containers --since=3m 2>&1 \
    | grep -i 'd05' | tail -6 | cut -c1-200
} 2>&1 | tee d05-g-$(hostname -s)-$(date +%F-%H%M).log
```

**Resultado (2026-11-10 17:24, [log](../logs-analysis/d05-g-sabdiia01-2026-11-10-1724.log)):** os dois `ConfigMap` aplicados; as 30 consultas devolvem 1 a 4 séries; o *sidecar* gravou os dois painéis em `/tmp/dashboards/` 1 s depois.

Depois, abra `http://192.168.50.162` → *Dashboards* → **D-05 — vLLM e GPU** e **D-05 — Kong (rota do vLLM)**. O que
se vê na tela não é evidência; o log do G é.

### G-desfazer — Tira os painéis (servidor `sabdiia01`, bash)

```bash
kubectl delete configmap -n vllms -l grafana_dashboard=1,decisao=d-05
```

## Alertas (Bloco A, A-desfazer)

Um `PrometheusRule` ([configs/d05-alertas.yaml](../configs/d05-alertas.yaml)) com 11 alertas em 3 grupos. Limiares
tirados do estudo: fila, *KV cache*, preempções e latência do AC-31 (Nemo, 32 usuários por GPU: fila 0, *KV cache* máx.
34 %, 0 preempções, p95 de 25 s por pergunta); *clock* e temperatura do AC-17 (estrangulamento: SM de 1560 para ~400 MHz,
a partir de 82 °C). Os do Kong (5xx acima de 5 %, 429 por 10 min) são escolha de operação.

| Grupo | Alerta | Dispara quando | Gravidade |
|---|---|---|---|
| vLLM | `D05VllmReplicaFora` | menos de 3 réplicas com `/metrics` de pé, por 3 min | critical |
| | `D05VllmFila` | fila > 0 numa réplica por 5 min | warning |
| | `D05VllmKvCacheAlto` | *KV cache* > 80 % por 5 min | warning |
| | `D05VllmPreempcoes` | alguma preempção em 10 min | warning |
| | `D05VllmLatenciaAlta` | p95 ponta a ponta > 25 s por 10 min | warning |
| GPU | `D05GpuEstrangulada` | SM < 1000 MHz com uso > 50 %, por 2 min | critical |
| | `D05GpuQuente` | > 80 °C por 5 min | warning |
| | `D05GpuSemMetricas` | DCGM em menos de 3 nós, por 5 min | warning |
| Kong | `D05KongErros5xx` | > 5 % de 5xx (com tráfego), por 5 min | critical |
| | `D05KongLimiteDoAtor` | um ator com 429 por 10 min | warning |
| | `D05KongSemMetricas` | Prometheus sem a porta 8100 do Kong, por 5 min | warning |

Os alertas aparecem no Prometheus, no Alertmanager e no Grafana (*Alerting* → *Alert rules*, fonte Prometheus). **Ninguém
é avisado por e-mail ou mensagem** enquanto o Alertmanager não tiver um *receiver* de verdade: o bloco mostra os que
existem. Para mudar um limiar: edite o YAML e rode o A de novo.

Envie o arquivo (notebook, PowerShell):

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
scp C:\www\vllm-master\configs\d05-alertas.yaml "${u}@192.168.50.151:/home/utec/vllm-estudo/"
```

### Bloco A — Aplica os alertas (servidor `sabdiia01`, bash)

**Expectativa (escrita antes):** `ruleSelector` do Prometheus = `release: monitoring`; o *webhook* do operador aceita as
11 expressões no `--dry-run=server`; os 3 grupos `d05-*` carregados em até 5 min, as 11 regras com `health` `ok` e estado
`inactive` (sem carga, nada dispara); o Alertmanager só com os *receivers* padrão do *chart* (`null`) `[hipótese]`.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 A: alertas (PD-38)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  command -v python3 >/dev/null || { echo "ABORTA: sem python3"; exit 1; }
  NS=vllms; M=d05-alertas.yaml
  [ -f $M ] || { echo "ABORTA: $M ausente; envie o arquivo"; exit 1; }
  sha256sum $M
  echo "### 0. que PrometheusRule o Prometheus carrega?   $(date +%T)"
  RS=$(kubectl get prometheus -n monitoring -o jsonpath='{.items[0].spec.ruleSelector}')
  echo "ruleSelector: $RS"
  echo "ruleNamespaceSelector: $(kubectl get prometheus -n monitoring \
    -o jsonpath='{.items[0].spec.ruleNamespaceSelector}')"
  [ "$RS" = '{"matchLabels":{"release":"monitoring"}}' ] \
    || { echo "ABORTA: seletor diferente do esperado; ajuste o rótulo do YAML"; exit 1; }

  echo "### 1. validação (webhook do operador) e aplicação   $(date +%T)"
  kubectl apply --dry-run=server -f $M || { echo "ABORTA: o cluster recusou as regras"; exit 1; }
  kubectl apply -f $M
  kubectl get prometheusrule -n $NS

  echo "### 2. regras carregadas? (até 5 min)   $(date +%T)"
  B="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:9090/proxy/api/v1"
  for i in $(seq 1 20); do
    kubectl get --raw "$B/rules" | grep -q '"name":"d05-kong"' && break; sleep 15; done
  echo "esperou $((i*15)) s"
  kubectl get --raw "$B/rules" > d05-regras.json
  python3 -c 'import json
for g in json.load(open("d05-regras.json"))["data"]["groups"]:
    if not g["name"].startswith("d05"): continue
    for r in g["rules"]:
        print(g["name"], r["name"], r.get("health"), r.get("state"), r.get("lastError", ""))'

  echo "### 3. Alertmanager: rotas e receivers (só nomes)   $(date +%T)"
  A="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-alertmanager:9093/proxy"
  kubectl get --raw "$A/api/v2/status" | python3 -c 'import json,sys
c = json.load(sys.stdin)["config"]["original"]
for l in c.splitlines():
    if l.strip().startswith(("receiver:", "- name:", "- receiver:")): print(l)'
  echo "### 4. alertas d05 disparando agora"
  kubectl get --raw "$B/alerts" | tr '{' '\n' | grep -o '"alertname":"D05[^"]*"' | sort | uniq -c
  rm -f d05-regras.json
} 2>&1 | tee d05-a-$(hostname -s)-$(date +%F-%H%M).log
```

**Resultado (2026-11-10 17:49, [log](../logs-analysis/d05-a-sabdiia01-2026-11-10-1749.log)):** `ruleSelector` `release: monitoring`; as 11 regras aceitas
pelo *webhook* e carregadas em 60 s, nenhuma com erro; o grupo `d05-vllm` já avaliado (5 `ok`, `inactive`), `d05-gpu` e
`d05-kong` ainda `unknown` (lidos antes da 1ª avaliação `[hipótese]`); nenhum alerta disparando. **Alertmanager só com o
*receiver* `"null"`: os alertas não chegam a ninguém.**

### A-confere — As 11 regras avaliadas (servidor `sabdiia01`, bash; só leitura)

**Expectativa:** as 11 com `health` `ok`; estado `inactive`, salvo carga ou GPU quente no momento.

**Resultado (2026-11-10 17:54, [log](../logs-analysis/d05-a-confere-sabdiia01-2026-11-10-1754.log)):** as 11 `ok`, `inactive`. O `unknown` do A era só a 1ª avaliação pendente.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  D-05 A-confere (só leitura)"
  B="/api/v1/namespaces/monitoring/services/monitoring-kube-prometheus-prometheus:9090/proxy/api/v1"
  kubectl get --raw "$B/rules" | python3 -c 'import json,sys
for g in json.load(sys.stdin)["data"]["groups"]:
    if g["name"].startswith("d05"):
        print(g["name"], "avaliado em", g.get("lastEvaluation", "?"))
        for r in g["rules"]:
            print("  ", r["name"], r.get("health"), r.get("state"), r.get("lastError", ""))'
} 2>&1 | tee d05-a-confere-$(hostname -s)-$(date +%F-%H%M).log
```

### A-desfazer — Tira os alertas (servidor `sabdiia01`, bash)

```bash
kubectl delete prometheusrule d05-alertas -n vllms
```

## Trazer os logs (notebook, PowerShell)

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
scp "${u}@192.168.50.151:/home/utec/vllm-estudo/d05-[op]*.log" C:\www\vllm-master\logs-analysis\
# o log do P0 fica em sabdiia03:
scp "${u}@192.168.50.150:/home/utec/vllm-estudo/d05-p0-*.log" C:\www\vllm-master\logs-analysis\
```
