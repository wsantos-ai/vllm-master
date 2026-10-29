# Runbook — Ray próprio em 01 + 02: `Qwen2.5-7B-Instruct` com *pipeline parallel* 2 (B-004)

**Pergunta:** dividir um modelo entre dois nós pelo Ray ajuda ou atrapalha nesta rede? Muda **uma
variável** em relação ao `T-001` (B-001c): o mesmo `Qwen/Qwen2.5-7B-Instruct` FP16, a mesma `v0.19.1`, as
mesmas flags e a mesma carga, agora em 2 GPUs (`sabdiia01` + `sabdiia02`), com
`--pipeline-parallel-size 2 --distributed-executor-backend ray`. **Decisão que destrava:** Ray com modelo
dividido entre nós (PD-31) contra réplicas de 1 GPU por nó (D-04).

**O que este teste NÃO usa:** o Ray do administrador. É um *cluster* Ray nosso, em `vllm-estudo`, criado
pelo bloco e **apagado no fim**. Nada em `vllms` é lido para alterar, parado ou editado.

**Antes de rodar:**

1. **Combine com o administrador** o uso das GPUs de 01 e 02 por ~1h30 `[estimativa]`. Se ele subir o Ray
   dele nesse período, um dos dois fica sem GPU (o Kubernetes não deixa os dois pegarem a mesma GPU) e as
   portas 6379/8000 de 01 se chocam.
2. Rode o **Bloco 0** de [teste-protocolo-modelos.md](teste-protocolo-modelos.md) em 01 e 02 (`VEREDITO ...
   PRONTO` nos dois) e o **Bloco 1** em 01 (grava `teste-protocolo.sh`).
3. Nada em `vllm-estudo`: se o *pod* `vllm-conc` existir, ele segura a GPU de 01. O bloco aborta se achar
   qualquer *pod* lá.

## Desenho

| Item | Valor | Por quê |
|---|---|---|
| *Head* | *pod* `ray-pp2-head`, `sabdiia01` (`192.168.50.151`): Ray *head* + `vllm serve` | O servidor sobe pelo manifesto, não por `kubectl exec -it` (que morreu com a sessão no Ray do administrador, AC-19) |
| *Worker* | *pod* `ray-pp2-worker`, `sabdiia02` (`192.168.50.152`) | 01 e 02 têm o mesmo MTU (1500); 03 fica de fora até o MTU ser igualado |
| Rede | `hostNetwork: true`; `NCCL_SOCKET_IFNAME`/`GLOO_SOCKET_IFNAME` = `bond0.500`; `VLLM_HOST_IP` = IP do nó | Os *pods* de 01 estão sem DNS (PD-28); `bond0.500` é a interface com o IP do nó. O vLLM não copia `VLLM_HOST_IP` para os *workers* (`WORKER_SPECIFIC_ENV_VARS`) e copia `NCCL_*` e `HF_*` [F-038] |
| Ray | `ray[cgraph,default]==2.48.0` + `cupy-cuda12x==13.6.0`, instalados ao iniciar | A imagem não traz Ray [F-034]; são as versões fixadas em `requirements/test.txt` da `v0.19.1` [F-038]. O executor recusa subir sem Compiled Graph |
| Modelo | `Qwen/Qwen2.5-7B-Instruct`, aberto (sem *token*) | Comparação direta com o `T-001` |
| Cache | `hostPath` `/home/utec/vllm-estudo/hf-cache` em cada nó, `HF_HOME=/hf-cache` | Cada nó lê do disco local a sua metade das camadas. Em 01 o modelo já está lá; em 02 o *pod* baixa ~15 GB antes de entrar no Ray, e eles ficam em `/home` de 02 (77 G livres em 2026-10-28) |
| Servidor | as flags do `T-001` + `--pipeline-parallel-size 2 --distributed-executor-backend ray` | Uma variável por vez |
| Exposição | API em `192.168.50.151:8000` e GCS do Ray em `:6379`, **sem autenticação**, só durante o teste | Risco assumido: ~1h na rede interna. O painel do Ray fica em `localhost` (padrão do `ray start`) |
| Gerador | `teste-protocolo.sh` dentro do *head* | Igual ao `T-001` (gerador no contêiner do servidor) |

> **Executado em 2026-10-29, 10:39-11:24 ([log](../logs-analysis/B-004-ray-pp2-qwen25-7b-sabdiia01-2026-10-29-1039.log)).**
> Subiu em 34 min (o *pull* da imagem em 02 precisou do `ctr`, [AC-24](../ESTUDO-DE-CASO.md#ac-24)). c=1: 36,7
> *tok*/s e TPOT 26,6 ms; c=32: 510,6 *tok*/s; *KV cache* 762.928 *tokens*. A expectativa abaixo errou no c=1
> (+31 %, não ~5 %) e no c=32 (abaixo de 1 GPU, não acima): [AC-23](../ESTUDO-DE-CASO.md#ac-23). Antes de
> repetir em outro nó, baixe a imagem com `ctr -n k8s.io images pull` (AC-24).

## Expectativa (escrita antes)

- **Arranque:** 20-60 min na primeira vez `[estimativa]`: *pull* da `v0.19.1` (~30 G) nos dois nós, Ray
  instalado, ~15 GB baixados em 02, carga do modelo.
- ***KV cache*:** perto do dobro do `T-001` (246.016 *tokens*). Cada GPU guarda só as camadas dela, e sobra
  mais memória para o contexto `[hipótese]`.
- **c=1:** TPOT p50 um pouco acima dos 20,3 ms do `T-001`, até ~5 % (AC-21: cada *token* passa uma vez
  pela rede) `[hipótese]`.
- **c=32:** vazão acima dos 680 *tok*/s do `T-001` e abaixo de 1.360 (2 réplicas de 1 GPU) `[hipótese]`.
- **Se o c=1 sair muito pior** (TPOT ≥ 30 ms), o custo da rede é maior que o calculado no AC-21.

## Bloco — servidor `sabdiia01`, bash (aborta em outro nó)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  [ -x teste-protocolo.sh ] || { echo "ABORTA: falta teste-protocolo.sh (Bloco 1 de runbooks/teste-protocolo-modelos.md)"; exit 1; }

  echo "### 1. pré-condições"
  kubectl describe nodes sabdiia01 sabdiia02 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  R=$(kubectl describe nodes sabdiia01 sabdiia02 | awk '/^  nvidia\.com\/gpu +[0-9]/{s+=$2} END{print s+0}')
  [ "$R" = 0 ] || { echo "ABORTA: GPU de 01 ou 02 reservada no Kubernetes"; exit 1; }
  A=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader)
  [ -z "$A" ] || { echo "ABORTA: processo na GPU de 01 fora do Kubernetes: $A"; exit 1; }
  kubectl get pods -n vllms --no-headers 2>/dev/null | grep -E 'ray|vllm' && { echo "ABORTA: há pods do Ray/vLLM em vllms (administrador)"; exit 1; }
  kubectl get pods -n vllm-estudo --no-headers 2>/dev/null | grep . && { echo "ABORTA: há pods em vllm-estudo; apague-os antes (ex.: vllm-conc segura a GPU de 01)"; exit 1; }
  ss -ltn | grep -E ':(6379|8000|10001)\b' && { echo "ABORTA: porta 6379/8000/10001 já ocupada em 01"; exit 1; }
  C=$(curl -s -o /dev/null -w '%{http_code}' -m 15 https://pypi.org/simple/ray/); echo "PyPI a partir de 01: HTTP $C"
  [ "$C" = 200 ] || { echo "ABORTA: 01 não alcança o PyPI (o Ray é instalado ao iniciar)"; exit 1; }
  ping -c 2 -W 1 -M do -s 1472 192.168.50.152 >/dev/null || { echo "ABORTA: ping de 1472 bytes sem fragmentar a 02 falha"; exit 1; }
  echo "MTU bond0.500 em 01: $(cat /sys/class/net/bond0.500/mtu)"
  df -h / /home

  echo "### 2. manifesto e criação dos pods   $(date +%T)"
  kubectl create namespace vllm-estudo --dry-run=client -o yaml | kubectl apply -f -
  cat > ray-pp2-qwen25-7b.yaml <<'EOF'
# Ray próprio do estudo (vllm-estudo): head em sabdiia01, worker em sabdiia02, PP 2.
# Pods de teste (restartPolicy Never), apagados no fim do bloco. Sem Service e sem autenticação.
apiVersion: v1
kind: Pod
metadata:
  name: ray-pp2-worker
  namespace: vllm-estudo
  labels: {app: ray-pp2}
spec:
  nodeSelector: {kubernetes.io/hostname: sabdiia02}
  hostNetwork: true
  restartPolicy: Never
  containers:
  - name: ray
    image: vllm/vllm-openai:v0.19.1
    command: ["/bin/bash", "-c"]
    args:
    - |
      set -e
      python3 -c "import ray" 2>/dev/null || uv pip install --system "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0" || python3 -m pip install "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0"
      python3 -c "import ray, cupy; print('ray', ray.__version__, 'cupy', cupy.__version__)"
      HF_HUB_OFFLINE=0 python3 -c "from huggingface_hub import snapshot_download as s; print('pesos em', s('Qwen/Qwen2.5-7B-Instruct'))"
      until timeout 3 bash -c '</dev/tcp/192.168.50.151/6379'; do echo "aguardando o head..."; sleep 5; done
      exec ray start --address=192.168.50.151:6379 --node-ip-address=192.168.50.152 --num-gpus=1 --object-store-memory=4000000000 --block
    env:
    - {name: HF_HOME, value: /hf-cache}
    - {name: HF_HUB_OFFLINE, value: "1"}
    - {name: VLLM_HOST_IP, value: "192.168.50.152"}
    - {name: NCCL_SOCKET_IFNAME, value: bond0.500}
    - {name: GLOO_SOCKET_IFNAME, value: bond0.500}
    resources:
      requests: {cpu: "8", memory: 32Gi, nvidia.com/gpu: 1}
      limits: {cpu: "16", memory: 64Gi, nvidia.com/gpu: 1}
    volumeMounts:
    - {name: hf-cache, mountPath: /hf-cache}
    - {name: shm, mountPath: /dev/shm}
  volumes:
  - name: hf-cache
    hostPath: {path: /home/utec/vllm-estudo/hf-cache, type: DirectoryOrCreate}
  - name: shm
    emptyDir: {medium: Memory, sizeLimit: 16Gi}
---
apiVersion: v1
kind: Pod
metadata:
  name: ray-pp2-head
  namespace: vllm-estudo
  labels: {app: ray-pp2}
spec:
  nodeSelector: {kubernetes.io/hostname: sabdiia01}
  hostNetwork: true
  restartPolicy: Never
  containers:
  - name: vllm
    image: vllm/vllm-openai:v0.19.1
    command: ["/bin/bash", "-c"]
    args:
    - |
      set -e
      python3 -c "import ray" 2>/dev/null || uv pip install --system "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0" || python3 -m pip install "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0"
      python3 -c "import ray, cupy; print('ray', ray.__version__, 'cupy', cupy.__version__)"
      HF_HUB_OFFLINE=0 python3 -c "from huggingface_hub import snapshot_download as s; print('pesos em', s('Qwen/Qwen2.5-7B-Instruct'))" || echo "aviso: sem rede para conferir o cache; segue com o cache local"
      ray start --head --node-ip-address=192.168.50.151 --port=6379 --num-gpus=1 --object-store-memory=4000000000
      echo "aguardando 2 GPUs no Ray..."
      until python3 -c "import ray, sys; ray.init(address='auto', logging_level='ERROR'); sys.exit(0 if ray.cluster_resources().get('GPU', 0) >= 2 else 1)" 2>/dev/null; do sleep 10; done
      ray status
      echo "2 GPUs no Ray; subindo o vLLM"
      exec vllm serve Qwen/Qwen2.5-7B-Instruct \
        --pipeline-parallel-size 2 --distributed-executor-backend ray \
        --dtype float16 --max-model-len 8192 --gpu-memory-utilization 0.90 \
        --generation-config vllm --host 0.0.0.0 --port 8000
    env:
    - {name: HF_HOME, value: /hf-cache}
    - {name: HF_HUB_OFFLINE, value: "1"}
    - {name: VLLM_HOST_IP, value: "192.168.50.151"}
    - {name: NCCL_SOCKET_IFNAME, value: bond0.500}
    - {name: GLOO_SOCKET_IFNAME, value: bond0.500}
    readinessProbe:
      httpGet: {path: /health, port: 8000}
      periodSeconds: 10
    resources:
      requests: {cpu: "8", memory: 32Gi, nvidia.com/gpu: 1}
      limits: {cpu: "16", memory: 64Gi, nvidia.com/gpu: 1}
    volumeMounts:
    - {name: hf-cache, mountPath: /hf-cache}
    - {name: shm, mountPath: /dev/shm}
  volumes:
  - name: hf-cache
    hostPath: {path: /home/utec/vllm-estudo/hf-cache, type: DirectoryOrCreate}
  - name: shm
    emptyDir: {medium: Memory, sizeLimit: 16Gi}
EOF
  kubectl apply -f ray-pp2-qwen25-7b.yaml

  echo "### 3. aguardando o servidor (até 60 min)   $(date +%T)"
  T0=$(date +%s); PRONTO=0
  while [ $(( $(date +%s) - T0 )) -lt 3600 ]; do
    H=$(kubectl get pod -n vllm-estudo ray-pp2-head -o jsonpath='{.status.phase}/{.status.containerStatuses[0].ready}' 2>/dev/null)
    W=$(kubectl get pod -n vllm-estudo ray-pp2-worker -o jsonpath='{.status.phase}' 2>/dev/null)
    [ "$H" = "Running/true" ] && { PRONTO=1; break; }
    case "$H $W" in *Failed*|*Succeeded*) echo "um dos pods terminou: head=$H worker=$W"; break;; esac
    echo "$(date +%T) head=$H worker=$W | head: $(kubectl logs -n vllm-estudo ray-pp2-head --tail=1 2>/dev/null | cut -c1-140) | worker: $(kubectl logs -n vllm-estudo ray-pp2-worker --tail=1 2>/dev/null | cut -c1-140)"
    sleep 60
  done
  echo "pronto=$PRONTO depois de $(( ($(date +%s) - T0) / 60 )) min"
  kubectl get pods -n vllm-estudo -o wide

  if [ $PRONTO = 1 ]; then
    echo "### 4. cluster Ray"
    kubectl exec -n vllm-estudo ray-pp2-head -- ray status
    echo "### 5. protocolo (mesmo do T-001)   $(date +%T)"
    bash teste-protocolo.sh vllm-estudo pod/ray-pp2-head pod/ray-pp2-worker
  else
    echo "### 4. FALHOU A SUBIDA: eventos dos pods"
    kubectl describe pod -n vllm-estudo ray-pp2-head ray-pp2-worker | grep -A15 '^Events:'
  fi

  echo "### 6. logs completos dos dois pods em arquivo próprio; aqui, o arranque e o fim"
  for p in ray-pp2-worker ray-pp2-head; do
    LP=$p-$(date +%F-%H%M).log
    kubectl logs -n vllm-estudo $p > $LP 2>&1
    echo "## $p ($(wc -l < $LP) linhas em $LP): arranque"
    grep -vE 'GET /health|POST /v1/|GET /metrics|loggers.py' $LP | head -250
    echo "## $p: fim"; tail -20 $LP
  done

  echo "### 7. limpeza: apaga os dois pods e libera as GPUs   $(date +%T)"
  kubectl delete pod -n vllm-estudo ray-pp2-head ray-pp2-worker --wait=true --timeout=180s
  kubectl describe nodes sabdiia01 sabdiia02 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  echo "== fim $(date -Is)"
} 2>&1 | tee B-004-ray-pp2-qwen25-7b-$(hostname -s)-$(date +%F-%H%M).log
```

Traga para `logs-analysis/` o `.log`, a pasta `testes/<data>-Qwen_Qwen2.5-7B-Instruct/` e o
`ray-pp2-qwen25-7b.yaml` (comando de `scp` no topo de [teste-protocolo-modelos.md](teste-protocolo-modelos.md)).

**Não interrompa com Ctrl+C.** Os *pods* continuam e seguram as GPUs. Se precisar parar, rode a limpeza abaixo.

## Limpeza manual (servidor, bash, 01 ou 02)

Só se o bloco for interrompido antes da seção 7.

```bash
kubectl delete pod -n vllm-estudo ray-pp2-head ray-pp2-worker --ignore-not-found
kubectl describe nodes sabdiia01 sabdiia02 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
```

## O que olhar

| Onde | O que | Leitura |
|---|---|---|
| Seção 3 | `pronto=1` | Subiu. `pronto=0` = veja a seção 6 |
| Seção 4 | `ray status`: 2 nós, `2.0/2.0 GPU` | Os dois nós entraram no Ray |
| Seção 5 → `### 2` | `Model loading took` aparece **duas vezes** (uma por GPU), `GPU KV cache size` | Cada GPU carregou metade das camadas; compare o *KV cache* com 246.016 |
| Seção 5 → `### 9` | linhas da Tabela 3 do registro | Compare com o `T-001`: c=1 47,0 *tok*/s e TPOT 20,3 ms; c=32 680,4 *tok*/s |
| Seção 5 → `### 7` e `### 8` | estrangulamento e temperatura **de 02** | Primeira carga longa na GPU de 02 (AC-17 só cobre 01). Se estrangular, o número é da refrigeração de 02 |

**Falhas prováveis na subida e o que significam** (procure na seção 6):

| Mensagem | Causa provável | O que fazer |
|---|---|---|
| `pip` ou `uv` com erro de rede, *worker* `Failed` logo no início | 02 não alcança o PyPI | Pedir acesso ao administrador, ou uma imagem derivada com o Ray |
| `Ray Compiled Graph is not installed` | O `ray[cgraph]` não instalou | Ver a linha `ray ... cupy ...` no início do log |
| `cupy is not installed but required` | O `cupy` não instalou | Idem |
| *Head* parado em `aguardando 2 GPUs no Ray...` | O *worker* não entrou no Ray (porta 6379, *firewall*) | `ray status` no *head*; no log do *worker*, a linha do `ray start` |
| Mensagem de `_wait_until_pg_ready` citando `VLLM_HOST_IP` | O IP que o vLLM vê não bate com o do Ray | Conferir o `VLLM_HOST_IP` de cada *pod* contra o `--node-ip-address` |
| `NCCL` com `timeout`, `Connection refused` ou `unhandled system error` | Comunicação entre GPUs pela rede | Comparar com o erro do Ray do administrador; testar `NCCL_DEBUG=INFO` numa segunda rodada |
| `CUDA out of memory` | Memória | Improvável com 7B em 2 GPUs; anote e mande para a análise |

## Depois

- Registre como `T-002` no [registro de testes](https://git.abdi.com.br/ia-abdi/vllm/vllm-config/-/blob/main/docs/registro-de-testes.md):
  arranjo "Ray PP 2 (01 + 02)". O resto da configuração é igual ao `T-001`.
- Se subiu e mediu: o manifesto vai para `configs/` com o cabeçalho de ambiente, e o resultado vira achado
  (PD-31). Se a subida falhou, o log já é a evidência que faltou no Ray do administrador. Leve-o a ele.
- Os ~15 GB do modelo ficam em `/home/utec/vllm-estudo/hf-cache` de 02 e servem para uma réplica de 1 GPU
  em 02.
