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

O E1 mostrou que o TEI roda nesta CPU (AC-42). Próximo: `Deployment`, `Service`, `NetworkPolicy` e rota
`/vllm/v1/embeddings` no Kong com as mesmas chaves e IPs do chat (E2, a escrever).

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

