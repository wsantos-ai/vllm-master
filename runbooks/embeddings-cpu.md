# Embeddings em CPU (PD-39)

Pedido do usuário (2026-11-12): servir *embeddings* para a aplicação NIB num *pod* **sem GPU**. As 3 GPUs são do
chat (D-06). Modelo escolhido pelo usuário: **`BAAI/bge-m3`**, revisão `5617a9f61b028005a4858fdac845db406aefb181`
(XLM-RoBERTa, 24 camadas, vetor de **1024**, `max_position_embeddings` 8194, *pooling* CLS, pesos `float32`) [F-057].
Servidor: **Text Embeddings Inference (TEI)**, imagem `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9`, que
expõe `POST /v1/embeddings` no formato da OpenAI [F-056].

**Risco que o E1 existe para medir:** a CPU dos nós é Xeon E5-2690 (Sandy Bridge), **sem AVX2** (§2). O TEI é
compilado com `-C target-cpu=native` (`.cargo/config.toml` do repositório, conferido em 2026-11-12) e a CPU da
máquina que gera a imagem publicada não é conhecida: o binário pode usar instruções que esta CPU não tem e cair com
`Illegal instruction` (código de saída 132) `[hipótese]`. Se cair, a alternativa é um servidor mínimo em Python
(`sentence-transformers` sobre PyTorch, que já roda nesta CPU: o vLLM o importa, AC-13), num bloco seguinte.

Escopo: tudo em `vllms` com `decisao=d-05` (o estudo apaga só isso); o administrador liberou o estudo para mexer
no ambiente em 2026-11-10. O E1 não muda nada do chat: não cria `Service`, rota nem `NetworkPolicy`, e apaga o
*pod* de teste no fim. Fica em `sabdiia02` só a pasta dos pesos.

| Bloco | O que faz |
|---|---|
| E1 | baixa o `bge-m3` em `sabdiia02`, sobe um *pod* de teste do TEI, mede dimensão, latência e coerência; apaga o *pod* |
| E1-desfazer | apaga o *pod* (se sobrou) e os pesos de `sabdiia02` |
| E2 | serviço permanente: `Deployment`, `Service`, `NetworkPolicy` e rota `POST /vllm/v1/embeddings` no Kong ([manifesto](../configs/d05-embeddings.yaml)) |
| E2-cliente | teste pelo Kong de uma máquina liberada (notebook) |
| E2-desfazer | tira o serviço e a rota (os pesos ficam) |

O E1 mostrou que o TEI roda nesta CPU (AC-42); o E2 o põe no ar.

## E1 — Viabilidade do TEI em CPU com `bge-m3` (servidor `sabdiia01`, bash com `kubectl`)

Por que `sabdiia02`: em 03 já ficam Prometheus, Grafana e Kong; 01 é onde se roda `kubectl` e tem a pendência de
DNS dos *pods* (PD-28). O download usa `hostNetwork` e a imagem `v0.19.1` do vLLM, já presente nos nós, como o
Bloco W de [acesso-aplicacoes-d05.md](acesso-aplicacoes-d05.md). Os pesos vêm só em `.bin` e ONNX no Hub; o bloco
grava também um `model.safetensors` convertido do `.bin` (arquivo a mais na pasta do *snapshot*, nada é trocado),
porque o *backend* `candle` do TEI lê *safetensors* `[não verificado: o TEI pode escolher o ONNX]`. O log do TEI diz
qual *backend* subiu.

O *pod* de teste: `requests` 4 CPU / 4 Gi, `limits` 8 CPU / 24 Gi (no aquecimento usou 10,8 Gi), `restartPolicy: Never` (uma queda aparece como
`Failed` com o código de saída, sem laço de reinício). `OMP_NUM_THREADS`, `MKL_NUM_THREADS` e `RAYON_NUM_THREADS` em 8
para as bibliotecas não abrirem uma *thread* por CPU do nó (32) com limite de 8. O vLLM de 02 reserva 8 CPU e pode
usar 16; somados, 24 de 32.

**Expectativa (escrita antes):**

- seção 1: *pod* de pesos `Succeeded`; `pytorch_model.bin` e `model.safetensors` com ~2,3 GB cada, `onnx/` presente;
- seção 2, um de três: (a) `ready=true`: o TEI roda sem AVX2; (b) `Failed` com `exitCode=132` ou `Illegal
  instruction` no log: não roda, segue para o servidor em Python; (c) `ErrImagePull`/`ImagePullBackOff`: o nó não
  alcança `ghcr.io`, e a imagem tem de ser baixada de outro jeito;
- seção 4 (só em (a)): dimensão **1024** nos três casos; similaridade da pergunta com a frase relacionada maior que
  com a não relacionada; latências `[não medido]`: são o número que este bloco existe para obter (CPU sem AVX2).

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  E1: TEI em CPU com bge-m3 em sabdiia02 (PD-39)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: rode em sabdiia01 (kubectl)"; exit 1; }
  NS=vllms; NO=sabdiia02; REV=5617a9f61b028005a4858fdac845db406aefb181
  IMG=ghcr.io/huggingface/text-embeddings-inference:cpu-1.9
  M=/hf-cache/hub/models--BAAI--bge-m3/snapshots/$REV

  echo "### 0. nó $NO e restos de execução anterior"
  kubectl describe node $NO | sed -n '/Allocated resources/,/Events/p' | head -10
  kubectl delete pod -n $NS d05-emb-pesos d05-emb-teste --ignore-not-found --wait=true

  echo "### 1. pesos do bge-m3 em $NO   $(date +%T)"
  sed -e "s|__NO__|$NO|g" -e "s|__REV__|$REV|g" <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata: {name: d05-emb-pesos, namespace: vllms, labels: {app: d05-emb-pesos, decisao: d-05}}
spec:
  nodeSelector: {kubernetes.io/hostname: __NO__}
  hostNetwork: true
  restartPolicy: Never
  automountServiceAccountToken: false
  containers:
  - name: pesos
    image: vllm/vllm-openai:v0.19.1
    command: ["/bin/bash", "-c"]
    args:
    - |
      set -e
      df -h /hf-cache
      python3 -c "from huggingface_hub import snapshot_download as s
      print('pesos em', s('BAAI/bge-m3',
        revision='__REV__', allow_patterns=['*.json', '*.model', 'pytorch_model.bin', 'onnx/*']))"
      D=/hf-cache/hub/models--BAAI--bge-m3/snapshots/__REV__
      [ -f $D/model.safetensors ] || python3 -c "import torch, safetensors.torch as st
      sd = torch.load('$D/pytorch_model.bin', map_location='cpu')
      st.save_file({k: v.contiguous() for k, v in sd.items()}, '$D/model.safetensors')
      print('model.safetensors:', len(sd), 'tensores')"
      ls -laL $D $D/onnx $D/1_Pooling
      du -shL /hf-cache/hub/models--BAAI--bge-m3
    env:
    - {name: HF_HOME, value: /hf-cache}
    - {name: HF_HUB_OFFLINE, value: "0"}
    resources:
      requests: {cpu: "1", memory: 4Gi}
      limits: {cpu: "4", memory: 16Gi}
    volumeMounts:
    - {name: hf-cache, mountPath: /hf-cache}
  volumes:
  - name: hf-cache
    hostPath: {path: /var/lib/vllm-estudo/hf-cache, type: DirectoryOrCreate}
EOF
  T0=$(date +%s)
  while [ $(( $(date +%s) - T0 )) -lt 1800 ]; do
    F=$(kubectl get pod -n $NS d05-emb-pesos -o jsonpath='{.status.phase}')
    echo "$(date +%T) $F"; case "$F" in Succeeded|Failed) break;; esac; sleep 30
  done
  kubectl logs -n $NS d05-emb-pesos 2>&1 | grep -vE '%\|' | cut -c1-160 | tail -30
  [ "$F" = Succeeded ] || { echo "ABORTA: pesos não baixaram ($F)"; exit 1; }
  kubectl delete pod -n $NS d05-emb-pesos --wait=true

  echo "### 2. pod de teste do TEI ($IMG)   $(date +%T)"
  sed -e "s|__NO__|$NO|g" -e "s|__IMG__|$IMG|g" -e "s|__M__|$M|g" <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata: {name: d05-emb-teste, namespace: vllms, labels: {app: d05-emb-teste, decisao: d-05}}
spec:
  nodeSelector: {kubernetes.io/hostname: __NO__}
  restartPolicy: Never
  automountServiceAccountToken: false
  containers:
  - name: tei
    image: __IMG__
    args: ["--model-id", "__M__", "--served-model-name", "BAAI/bge-m3", "--port", "8080",
           "--tokenization-workers", "4"]
    env:
    - {name: HF_HUB_OFFLINE, value: "1"}
    - {name: OMP_NUM_THREADS, value: "8"}
    - {name: MKL_NUM_THREADS, value: "8"}
    - {name: RAYON_NUM_THREADS, value: "8"}
    readinessProbe:
      httpGet: {path: /health, port: 8080}
      periodSeconds: 10
      failureThreshold: 3
    resources:
      requests: {cpu: "4", memory: 4Gi}
      limits: {cpu: "8", memory: 24Gi}
    volumeMounts:
    - {name: hf-cache, mountPath: /hf-cache}
  volumes:
  - name: hf-cache
    hostPath: {path: /var/lib/vllm-estudo/hf-cache, type: Directory}
EOF
  T0=$(date +%s); PRONTO=nao; C='.status.containerStatuses[0]'
  J="{.status.phase} ready={$C.ready} espera={$C.state.waiting.reason}"
  J="$J fim={$C.state.terminated.reason}/{$C.state.terminated.exitCode}"
  while [ $(( $(date +%s) - T0 )) -lt 1200 ]; do
    S=$(kubectl get pod -n $NS d05-emb-teste -o jsonpath="$J")
    echo "$(date +%T) $S"
    case "$S" in *ready=true*) PRONTO=sim; break;; Failed*|Succeeded*) break;; esac
    sleep 20
  done
  echo "pronto: $PRONTO  ($(( $(date +%s) - T0 )) s)"

  echo "### 3. log do TEI"
  kubectl logs -n $NS d05-emb-teste 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | cut -c1-300 | tail -40
  kubectl get events -n $NS --field-selector involvedObject.name=d05-emb-teste \
    -o custom-columns=HORA:.lastTimestamp,MOTIVO:.reason,MSG:.message | cut -c1-200 | tail -12

  if [ "$PRONTO" = sim ]; then
    echo "### 4. teste pelo port-forward   $(date +%T)"
    kubectl port-forward -n $NS pod/d05-emb-teste 18080:8080 >/dev/null 2>&1 & PF=$!
    for i in $(seq 1 15); do
      H=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/health)
      [ "$H" = 200 ] && break; sleep 2
    done
    echo "GET /health -> HTTP $H (port-forward)"
    python3 - <<'PY'
import json, math, time, urllib.request
U = 'http://127.0.0.1:18080/v1/embeddings'
def emb(xs):
    b = json.dumps({'model': 'BAAI/bge-m3', 'input': xs}).encode()
    r = urllib.request.Request(U, b, {'Content-Type': 'application/json'})
    t = time.time(); d = json.load(urllib.request.urlopen(r, timeout=600))
    return d, time.time() - t
longo = 'O vLLM serve o modelo de linguagem em três servidores com GPU no cluster. ' * 40
for nome, xs in [('curto', ['Qual é a capital do Brasil?']), ('longo', [longo]),
                 ('lote8', [longo] * 8)]:
    for i in range(3):
        d, s = emb(xs)
        v = d['data'][0]['embedding']
        print(f"{nome} #{i}: itens={len(d['data'])} dim={len(v)} "
              f"norma={math.sqrt(sum(x * x for x in v)):.3f} usage={d.get('usage')} {s:.3f} s")
d, _ = emb(['Qual é a capital do Brasil?', 'Brasília é a capital do Brasil.',
            'O gato dorme no sofá da sala.'])
q, a, b = [x['embedding'] for x in d['data']]
def cos(x, y):
    n = math.sqrt(sum(i * i for i in x) * sum(j * j for j in y))
    return sum(i * j for i, j in zip(x, y)) / n
print(f"similaridade: relacionada={cos(q, a):.3f}  não relacionada={cos(q, b):.3f}")
PY
    kill $PF 2>/dev/null
    echo "### 5. memória e CPU do pod (se houver metrics-server)"
    kubectl top pod -n $NS d05-emb-teste 2>&1 | tail -2
  fi

  echo "### 6. limpeza: apaga o pod de teste (os pesos ficam em $NO)"
  kubectl delete pod -n $NS d05-emb-teste --ignore-not-found --wait=true
  kubectl get pods -n $NS -o wide | cut -c1-140
  echo "== fim $(date -Is)"
} 2>&1 | tee embeddings-e1-$(hostname -s)-$(date +%F-%H%M).log
```

**Ler o resultado:** a linha `pronto:` e a seção 3 decidem entre (a), (b) e (c). Em (a), a seção 4 dá a dimensão e
o tempo de um texto curto, de um longo e de um lote de 8 longos (a 1ª chamada de cada caso inclui aquecimento); o
`usage` diz quantos *tokens* o texto longo tem.

**Resultado da 1ª rodada (2026-11-12 15:33, [log](../logs-analysis/embeddings-e1-sabdiia01-2026-11-12-1533.log)):
inconclusivo, por defeito do bloco.** Pesos baixados em 1 min (6,4 G, `model.safetensors` de 2.271.064.424 *bytes*
convertido); imagem `cpu-1.9` puxada de `ghcr.io` em 23,8 s (239.316.921 *bytes*): o nó alcança o registro. O TEI
arrancou sem `Illegal instruction` até `Warming up model` (18:35:28 UTC, 3 s depois do início) e confirmou
`Maximum number of tokens per request: 8192`. Mas o *pod* não tinha `readinessProbe`, então `ready=true` (18:35:37)
só dizia que o contêiner estava de pé, não que a porta 8080 já escutava: o `/health` e o teste levaram `Connection
refused` ainda no aquecimento, e o bloco apagou o *pod* em seguida. Não se sabe se o aquecimento terminaria ou
cairia por instrução ilegal. **Corrigido:** `readinessProbe` em `/health` e espera de até 30 s pelo `/health` no
*port-forward*; o log do TEI sai sem códigos de cor. Rodar o E1 de novo: a seção 1 reaproveita os pesos (o
`snapshot_download` só confere, e a conversão é pulada).

**2ª rodada (2026-11-12 15:42, [log](../logs-analysis/embeddings-e1-sabdiia01-2026-11-12-1542.log)): rodou a versão
antiga do bloco** (sem `readinessProbe`, sem limpar a cor do log, a linha `GET /health -> HTTP 000` no formato antigo):
o mesmo `Connection refused` 20 s depois do arranque. Dado novo: na seção 5, ainda no aquecimento (~50 s depois de
`Warming up model`), o *pod* usava **6,1 CPU e 10,8 Gi** e não tinha caído. Uma instrução ilegal derrubaria o processo
na primeira conta; meio minuto de cálculo pleno sem queda indica que o binário roda nesta CPU `[inferência]`, e que o
aquecimento é longo (minutos). Limite de memória do teste: 16 → 24 Gi, para o aquecimento não esbarrar nele.

**3ª rodada (2026-11-12 15:47, [log](../logs-analysis/embeddings-e1-sabdiia01-2026-11-12-1547.log)): o TEI roda
nesta CPU (AC-42).** Pronto em 81 s, com aquecimento de 54 s (a *probe* falhou uma vez às 18:48:30, como esperado);
`/health` 200; dimensão 1024 e norma 1 nos três casos.

| Caso | *Tokens* | Tempo (3 chamadas) |
|---|---|---|
| curto | 9 | 0,128 / 0,122 / 0,117 s |
| longo | 683 | 2,032 / 1,702 / 1,689 s |
| lote de 8 longos | 5.464 | 13,621 / 13,551 / 13,766 s |

Similaridade da pergunta: 0,741 com a frase relacionada, 0,282 com a não relacionada. Uso: 7.978m de CPU (o limite
de 8) e 10.785 Mi. O lote não rende mais que o texto sozinho: ~400 *tokens*/s nos dois. Avisos do TEI para o E2:
`forcing max_batch_requests=8` (limite do *backend*) e `Invalid hostname, defaulting to 0.0.0.0` (o Kubernetes põe o
nome do *pod* em `HOSTNAME`; passar `--hostname 0.0.0.0`).

### E1-desfazer (servidor `sabdiia01` para o *pod*; `sabdiia02` como `root` para os pesos)

```bash
kubectl delete pod -n vllms d05-emb-pesos d05-emb-teste --ignore-not-found
```

Em `sabdiia02`, como `root` (libera ~7 GB):

```bash
rm -rf /var/lib/vllm-estudo/hf-cache/hub/models--BAAI--bge-m3 && df -h /var/lib/vllm-estudo
```

## Enviar o manifesto (notebook, PowerShell)

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
scp "C:\www\vllm-master\configs\d05-embeddings.yaml" "${u}@192.168.50.151:/home/utec/vllm-estudo/"
```

## E2 — Serviço de *embeddings* e rota no Kong (servidor `sabdiia01`, bash com `kubectl`)

Aplica [configs/d05-embeddings.yaml](../configs/d05-embeddings.yaml):
- `Deployment` `embeddings-bge-m3`: 1 réplica em `sabdiia02`, com a configuração medida no E1 mais `--hostname 0.0.0.0`, a chave do TEI e os pesos montados só para leitura;
- `Service` `ClusterIP`;
- `NetworkPolicy` `embeddings-so-kong`;
- `Ingress` `embeddings-bge-m3`: `POST /vllm/v1/embeddings`, HTTPS, com `d05-key-auth`, `d05-rate-limit` e `d05-prometheus`, se este último existir.

Todos os recursos são novos e levam `decisao=d-05`; nada do chat muda. Cópia antes: os `Ingress`, `Service` e `NetworkPolicy` de `vllms` vão para `d05-vllms-antes-e2-<data>.yaml`.

Os testes feitos de 01 não seguem o caminho dos clientes, porque 01 não está na lista de IPs de ninguém: ele chega ao Kong com o IP de túnel (AC-33). Por isso o bloco confere duas coisas separadas:
- pelo Kong, de 01: que a rota existe e que a chave e a lista de IPs valem nela;
- direto no *pod*, por *port-forward* (sem Kong): a chave do TEI e a resposta.

O caminho completo é testado no E2-cliente.

**Expectativa (escrita antes):**

- seção 1: `--dry-run=server` sem erro; os 4 objetos `created`;
- seção 2: `rollout` completo em até ~2 min (no E1, o aquecimento levou 54 s); `Ready` 1/1;
- seção 3: log do TEI com `Ready` e **sem** `Invalid hostname`; `imageID` com o *digest* da `cpu-1.9`;
- seção 4: `Ingress` com o IP do Kong; plugins `d05-key-auth,d05-rate-limit,d05-prometheus`;
- seção 5, pelo Kong, de 01: sem chave → `401`; com a chave de `estacao` → `403 IP address not allowed`, sinal de que a lista vale na rota nova. Um `200` aqui é falha: a lista de IPs não estaria valendo;
- seção 6, direto no *pod*: sem `Authorization` → `401`, sinal de que a chave do TEI vale; com ela → `200`, dimensão 1024;
- se o TEI cair por tentar gravar na pasta dos pesos, a seção 3 mostra o erro. No E1 a pasta era de leitura e escrita; agora está montada só para leitura. Nesse caso, tire o `readOnly: true` do manifesto e reaplique.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  E2: embeddings (bge-m3, TEI cpu-1.9) e rota no Kong (PD-39)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: rode em sabdiia01 (kubectl)"; exit 1; }
  NS=vllms; MAN=d05-embeddings.yaml; TS=$(date +%F-%H%M)
  [ -f $MAN ] || { echo "ABORTA: falta $MAN (envie pelo scp do runbook)"; exit 1; }
  kubectl get secret vllm-nemo-api-key -n $NS >/dev/null || { echo "ABORTA: sem o Secret"; exit 1; }
  KIP=$(kubectl get svc kong-gateway-proxy -n kong \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
  echo "IP do Kong: $KIP"; [ -n "$KIP" ] || { echo "ABORTA: sem IP do Kong"; exit 1; }
  [ -f d05-chave-estacao.env ] || { echo "ABORTA: sem d05-chave-estacao.env (Bloco C)"; exit 1; }

  echo "### 0. cópia antes e restos do E1"
  kubectl get ingress,svc,networkpolicy -n $NS -o yaml > d05-vllms-antes-e2-$TS.yaml
  ls -l d05-vllms-antes-e2-$TS.yaml
  kubectl delete pod -n $NS d05-emb-teste d05-emb-pesos --ignore-not-found

  echo "### 1. aplicar   $(date +%T)"
  kubectl apply --dry-run=server -f $MAN || { echo "ABORTA: dry-run falhou"; exit 1; }
  kubectl apply -f $MAN
  PLUGS=d05-key-auth,d05-rate-limit
  kubectl get kongplugin d05-prometheus -n $NS >/dev/null 2>&1 && PLUGS=$PLUGS,d05-prometheus
  kubectl annotate ingress embeddings-bge-m3 -n $NS konghq.com/plugins=$PLUGS --overwrite

  echo "### 2. arranque   $(date +%T)"
  kubectl rollout status deploy/embeddings-bge-m3 -n $NS --timeout=600s
  kubectl get pods -n $NS -l app=embeddings -o wide

  echo "### 3. log do TEI e imagem"
  P=$(kubectl get pods -n $NS -l app=embeddings -o jsonpath='{.items[0].metadata.name}')
  kubectl logs -n $NS $P 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | cut -c1-300 | tail -15
  kubectl get pod -n $NS $P -o jsonpath='imageID: {.status.containerStatuses[0].imageID}{"\n"}'

  echo "### 4. rota no Kong   $(date +%T)"
  sleep 20
  kubectl get ingress embeddings-bge-m3 -n $NS
  kubectl get ingress embeddings-bge-m3 -n $NS \
    -o jsonpath='plugins: {.metadata.annotations.konghq\.com/plugins}{"\n"}'
  kubectl get events -n $NS --sort-by=.lastTimestamp | grep -iE 'embeddings|kong' | tail -8 \
    | cut -c1-250

  echo "### 5. pelo Kong, de 01 (esperado: 401 sem chave; 403 IP com chave)   $(date +%T)"
  URL="https://$KIP/vllm/v1/embeddings"
  printf '%s' '{"model":"BAAI/bge-m3","input":"Qual é a capital do Brasil?"}' > d05-emb-corpo.json
  echo "sem chave: $(curl -sk -o /dev/null -w '%{http_code}' -X POST "$URL" \
    -H 'Content-Type: application/json' --data @d05-emb-corpo.json)"
  ( umask 077; . ./d05-chave-estacao.env
    printf 'apikey: %s\nAuthorization: Bearer %s\n' "$CHAVE_KONG" "$CHAVE_VLLM" > d05-emb-h.txt )
  R=$(curl -sk -w ' HTTP %{http_code}' -X POST "$URL" -H @d05-emb-h.txt \
    -H 'Content-Type: application/json' --data @d05-emb-corpo.json)
  echo "com a chave de estacao: $R" | cut -c1-200

  echo "### 6. direto no pod, sem Kong (esperado: 401 sem Authorization; 200 com ela)   $(date +%T)"
  kubectl port-forward -n $NS deploy/embeddings-bge-m3 18080:8080 >/dev/null 2>&1 & PF=$!
  for i in $(seq 1 15); do
    curl -s -o /dev/null http://127.0.0.1:18080/ && break; sleep 2
  done
  echo "sem Authorization: $(curl -s -o /dev/null -w '%{http_code}' -X POST \
    http://127.0.0.1:18080/v1/embeddings -H 'Content-Type: application/json' \
    --data @d05-emb-corpo.json)"
  grep '^Authorization' d05-emb-h.txt > d05-emb-h2.txt
  curl -s -o d05-emb-resp.json -w 'com Authorization: HTTP %{http_code} %{time_total}s\n' -X POST \
    http://127.0.0.1:18080/v1/embeddings -H @d05-emb-h2.txt \
    -H 'Content-Type: application/json' --data @d05-emb-corpo.json
  python3 -c "import json; d = json.load(open('d05-emb-resp.json'))
print('dim', len(d['data'][0]['embedding']), d.get('usage'))" 2>&1 | tail -1
  kill $PF 2>/dev/null
  rm -f d05-emb-h.txt d05-emb-h2.txt d05-emb-corpo.json d05-emb-resp.json

  echo "### 7. estado final"
  kubectl get deploy,svc,networkpolicy,ingress -n $NS -l decisao=d-05 | cut -c1-150
  kubectl top pod -n $NS -l app=embeddings 2>&1 | tail -2
  echo "== fim $(date -Is)"
} 2>&1 | tee embeddings-e2-$(hostname -s)-$(date +%F-%H%M).log
```

**Resultado (2026-11-12 16:06, [log](../logs-analysis/embeddings-e2-sabdiia01-2026-11-12-1606.log)): tudo como esperado.** Os 4 objetos `created` (o *dry-run* também);
*pod* `1/1` em `sabdiia02` 70 s depois, aquecimento de 56 s (19:06:09 → 19:07:05 UTC) e uma falha da `startupProbe`
no meio dele, como previsto; log sem `Invalid hostname` e pesos montados só leitura sem erro; imagem
`sha256:2538ea1c9640d3763b15af668039d24172d063b42337b0c27796fc2be180c78d`. Rota com `d05-key-auth,d05-rate-limit,d05-prometheus`.
Pelo Kong, de 01: `401` sem chave e `403 IP address not allowed: 10.244.179.64` com a chave de `estacao` (a lista
por consumidor vale na rota nova). Direto no *pod*: `401` sem `Authorization`, `200` com ela em 0,115 s, dimensão
1024. Em repouso: 28m de CPU e 10.782 Mi. Falta o E2-cliente (caminho real, do notebook).

**Pronto se:**
- seções 2 e 3: *pod* `Ready` e log sem `Invalid hostname`;
- seção 5: `401` e `403`;
- seção 6: `401` e `200`, com `dim 1024`.

Depois, rode o E2-cliente.

### E2-cliente — Teste pelo Kong (notebook, Git Bash, pela VPN)

Este é o caminho real: notebook (`wsantos`, `172.16.254.0/24`) → Kong → TEI. As chaves vêm do arquivo do ator e não aparecem na tela. O `base_url` é o mesmo do chat. Esperado: `HTTP 200` e 2 vetores.

O bloco grava a resposta em `~` (a pasta do usuário): o Git Bash pode abrir em `/`, que é `C:\Program Files\Git`,
sem permissão de escrita, e foi isso que derrubou a 1ª tentativa (`FileNotFoundError: 'emb-resp.json'`, 2026-11-12):
o `curl -s` não conseguiu gravar e calou o erro. Agora `-sS` mostra erros do `curl`, e o `\r` de um `.env` editado
no Windows é retirado antes de ler. A 2ª tentativa chegou ao TEI e levou `HTTP 400` `Failed to parse the request body
as JSON: input[0]: invalid unicode code point`: o terminal do Windows mandou o "é" colado fora de UTF-8 `[inferência]`.
Os acentos agora vão como escapes JSON (`\u00e9`), que só usam ASCII. Aplicação de verdade (SDK) manda UTF-8.

```bash
set -a; . <(tr -d '\r' < ~/.vllm-estudo/d05-chave-wsantos.env); set +a
echo "BASE_URL=$BASE_URL  chave Kong: ${#CHAVE_KONG} caracteres  chave vLLM: ${#CHAVE_VLLM} caracteres"
F=~/emb-resp.json; rm -f "$F"
curl -sSk "$BASE_URL/embeddings" \
  -H "apikey: $CHAVE_KONG" \
  -H "Authorization: Bearer $CHAVE_VLLM" \
  -H "Content-Type: application/json" \
  -d '{"model": "BAAI/bge-m3", "input": ["Qual \u00e9 a capital do Brasil?", "Bras\u00edlia \u00e9 a capital."]}' \
  -o "$F" -w 'HTTP %{http_code}  total %{time_total}s\n'
python -c "import json, sys; d = json.load(open(sys.argv[1], encoding='utf-8'))
print(len(d['data']), 'vetores, dim', len(d['data'][0]['embedding']), d.get('usage'))
" "$F" 2>&1 || head -c 300 "$F"
```

**Resultado (2026-11-12, [saída colada](../logs-analysis/embeddings-e2-cliente-wsantosdell-2026-11-12.txt)): `HTTP 200` em 0,21 s, 2 vetores de 1024, 16 *tokens*.** O caminho
real funciona: notebook → Kong (chave e IP do `wsantos`) → TEI (chave do vLLM).

No SDK da OpenAI: `client.embeddings.create(model="BAAI/bge-m3", input=[...])`, com o mesmo `base_url` e as mesmas chaves do chat: `apikey` em `default_headers` e a chave do vLLM como `api_key`.

### E2-app — Teste pela aplicação (notebook, Git Bash, em `C:\www\vllm-app`)

`test/teste-embeddings.js` usa o AI SDK (`embed`, `embedMany`, `cosineSimilarity`), como a aplicação. Ele testa:
- segurança: sem a chave do Kong → `401`; sem a do vLLM → `401` do TEI;
- uma pergunta: dimensão 1024 e norma 1;
- recuperação: 4 perguntas contra 6 trechos;
- texto longo;
- limite de lote: o TEI aceita até 32 textos por chamada, e o AI SDK manda até 2.048 numa só, então a aplicação tem de dividir. O script mostra como, em `embedEmLotes`.

O log vai para `logs-analysis/embeddings-cliente-<máquina>-<data>.log`.

```bash
NODE_TLS_REJECT_UNAUTHORIZED=0 node test/teste-embeddings.js
```

**Resultado (2026-11-12 16:41, [log](../logs-analysis/embeddings-cliente-wsantosdell-2026-11-12-1641.log)): 12/12 OK.**
- Segurança: `401` do Kong (`No API key found in request`) e `401` do TEI.
- Uma pergunta: 0,140 s pelo Kong, dimensão 1024, norma 1,0000.
- Recuperação: as 4 perguntas acharam o trecho certo em 1º lugar, com folga. A similaridade do certo ficou entre 0,517 e 0,619; a do 2º colocado, entre 0,301 e 0,384.
- Texto longo: 683 *tokens* em 1,741 s (392 *tokens*/s, como no E1).
- Lotes: 32 textos passam (1,37 s). Com 33, o TEI responde `422 batch size 33 > maximum allowed batch size 32`. Com `embedEmLotes`, 40 textos passam em 1,77 s.

### E2-desfazer (servidor `sabdiia01`, bash)

Tira o serviço e a rota. Os pesos ficam em `sabdiia02`; para tirá-los, use o E1-desfazer. O chat não é afetado.

```bash
cd /home/utec/vllm-estudo && kubectl delete -f d05-embeddings.yaml --ignore-not-found \
  2>&1 | tee embeddings-e2-desfazer-$(hostname -s)-$(date +%F-%H%M).log
```
