# Runbook — P-05: `Qwen2.5-14B-Instruct` FP16 em 01 + 02 pelo Ray (*pipeline parallel* 2)

> **Histórico (2026-11-07):** o Ray foi eliminado do *cluster* e dos *hosts* (D-07,
> [remover-ray.md](remover-ray.md)). Este *runbook* fica como registro das medições; não rode.

**Pergunta:** o teto de 114-195 *tok*/s da onda 1 com 32 usuários vem do GPTQ ou do tamanho do modelo?
O P-05 roda o **mesmo 14B do P-01** (`T-003`, GPTQ Int8, 1 GPU), agora em FP16. Os pesos em FP16
(27,51 GiB) não deixam espaço para *KV cache* numa V100S, por isso o teste precisa de 2 GPUs.
**Decisão que destrava:** se vale testar os outros GPTQ pelo Ray (P-06, P-07) e se FP16 pelo Ray é caminho
para produção (D-04, PD-19, PD-31).

**Duas variáveis mudam em relação ao P-01:** a precisão (GPTQ Int8 → FP16) e o arranjo (1 GPU → Ray PP 2).
O custo do Ray já foi medido à parte: o 7B FP16 rendeu 22-25 % menos em PP 2 que em 1 GPU (`T-002` ×
`T-001`, AC-23). Esse desconto entra na leitura do resultado. Tudo o mais repete o `T-002`: a `v0.19.1`, o
Ray `2.48.0`, a rede, as *flags* e a carga.

**O que muda em relação ao `T-002`, fora da medida:**
- **Cache em `/`, não em `/home`.** No fim da onda 1, o `/home` de `sabdiia01` tinha **33 G livres**
  ([log do P-04](../logs-analysis/P-04-sabdiia01-2026-10-30-1050.log), 11:28), e este modelo ocupa ~30 GB.
  O cache vai para `/var/lib/vllm-estudo/hf-cache` nos dois nós (`/` com 534-580 G livres em 2026-10-28).
  Nada é apagado.
- **Os dois nós baixam o modelo inteiro**, só `.safetensors`, `.json` e arquivos do *tokenizer*. Cada *pod*
  confere antes se há 60 G livres.

O Ray é o do estudo, criado em `vllm-estudo` e **apagado no fim**. Nada em `vllms` é alterado, parado ou
editado.

> **Executado em 2026-11-03, 15:44-16:13 ([log](../logs-analysis/P-05-ray-pp2-sabdiia01-2026-11-03-1544.log)), com
> `vllms` pausado ([pausar-vllms.md](pausar-vllms.md)).** Subiu em 12 min. c=1: 21,4 *tok*/s e TPOT 45,7 ms;
> c=32: 319,4 *tok*/s; *KV cache* 144.816 *tokens*. A expectativa acertou o arranque, os pesos, o *KV cache* e
> o c=1, mas ficou abaixo no c=32 (200-300). Pela tabela "Como ler o c=32", o teto do P-01 vem do `gptq_gemm`:
> [AC-26](../ESTUDO-DE-CASO.md#ac-26).

## Antes de rodar

1. **Combine com o administrador** o uso das GPUs de 01 e 02 por ~1h30 `[estimativa]`.
2. **Bloco 0** de [teste-protocolo-modelos.md](teste-protocolo-modelos.md) em 01 e 02: `VEREDITO ... PRONTO` nos dois.
3. **Bloco 1** do mesmo runbook, **de novo**, em `sabdiia01`. O `teste-protocolo.sh` usado na onda 1 não
   pedia E2EL. O bloco abaixo aborta se o script for o antigo.
4. **Bloco A** abaixo, em `sabdiia02`: confere a imagem e o disco de 02 e baixa a imagem, se faltar.
5. Nada em `vllm-estudo`: o bloco aborta se achar algum *pod* lá.

## Expectativa (escrita antes)

- **Arranque:** 15-30 min `[estimativa]`. ~30 GB baixados em cada nó ao mesmo tempo (na onda 1, 16 GB
  baixaram e subiram em ~5 min), mais a instalação do Ray (~2 min) e a carga do modelo.
- **Pesos:** `Model loading took` aparece **duas vezes**, ~13,8 GiB em cada GPU `[cálculo: 27,51 GiB ÷ 2;
  a *embedding* fica na 1ª etapa e o `lm_head` na 2ª, 1,45 GiB cada]`.
- ***KV cache*:** ~140 mil *tokens* (~17× de 8.192), contra 61.440 do P-01. `[cálculo: cada GPU guarda 24
  das 48 camadas, a 98.304 B/*token*, metade dos 196.608 B/*token* medidos no T-003 (11,25 GiB ÷ 61.440);
  livre por GPU ≈ 28,8 − 13,8 − 1,9 GiB de ativações, como no T-003]`.
- **c=1:** TPOT p50 ~45 ms, ~22 *tok*/s, **metade do P-01** (19,5 ms; 48,7 *tok*/s) `[hipótese]`. Cada
  *token* lê o dobro de pesos do 7B FP16 (~2 × 20,3 ms), mais os ~6 ms que a divisão custou no `T-002`.
- **c=32:** 200-300 *tok*/s `[hipótese]`, pela proporção de pesos sobre o `T-002`: 510,6 × 14,25 ÷ 27,51
  ≈ 265. Por usuário, ~8 *tok*/s, abaixo do piso proposto de 10.
- **Sanidade:** correta `[hipótese]`. O Qwen2.5 em FP16 (publicado em BF16) já foi validado no 7B, mas
  não no 14B.

**Como ler o c=32** `[hipótese]`:

| Resultado | Leitura |
|---|---|
| bem acima de 195 (≥ 250) | O teto do P-01 vem do `gptq_gemm`. FP16 é o caminho para concorrência, e os GPTQ pelo Ray (P-06, P-07) devem repetir o teto: baixa prioridade |
| perto de 195 ou abaixo | O teto vem do tamanho do modelo e do Ray, não só do GPTQ. Descontados os 22-25 % do Ray, o 14B FP16 em 1 GPU daria ~250, o que a V100S não comporta |
| c=1 ≥ 30 *tok*/s | A divisão custou menos que no 7B: anote e compare o TPOT com o `T-002` |

## Bloco A — Preparo de `sabdiia02` (servidor `sabdiia02`, bash; aborta em outro nó)

Só lê, a não ser que a imagem falte: nesse caso, baixa com `ctr` (**ALTERA o nó: +~30 G em `/`**,
~6,5 min em 2026-10-29, AC-24).

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)"
  [ "$(hostname -s)" = sabdiia02 ] || { echo "ABORTA: este bloco é para sabdiia02"; exit 1; }

  echo "### 1. disco: o cache do P-05 fica em /var/lib/vllm-estudo/hf-cache"
  MT=$(df --output=target /var/lib | tail -1); echo "/var/lib está montado em: $MT"
  [ "$MT" = / ] || { echo "ABORTA: /var/lib não está em /"; exit 1; }
  df -h / /home
  L=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
  [ "$L" -ge 100 ] || { echo "ABORTA: / com só ${L} G livres"; exit 1; }

  echo "### 2. imagem v0.19.1 no containerd"
  if ctr -n k8s.io images ls -q | grep -qx 'docker.io/vllm/vllm-openai:v0.19.1'; then
    echo "imagem já presente"
  else
    echo "imagem ausente: baixando com ctr   $(date +%T)"
    ctr -n k8s.io images pull docker.io/vllm/vllm-openai:v0.19.1 2>&1 | tail -5
    echo "saída do ctr: ${PIPESTATUS[0]}   $(date +%T)"
    df -h /
  fi
  ctr -n k8s.io images ls | awk 'NR==1 || /vllm-openai/' | cut -c1-160

  echo "### 3. GPU e acesso à internet (o Ray e o modelo são baixados ao iniciar)"
  nvidia-smi --query-gpu=memory.used,utilization.gpu,temperature.gpu --format=csv
  P=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader); echo "processos na GPU: ${P:-(nenhum)}"
  echo "PyPI: HTTP $(curl -s -o /dev/null -w '%{http_code}' -m 15 https://pypi.org/simple/ray/)"
  echo "Hugging Face: HTTP $(curl -s -o /dev/null -w '%{http_code}' -m 15 https://huggingface.co/api/models/Qwen/Qwen2.5-14B-Instruct)"
  echo "== fim $(date -Is)"
} 2>&1 | tee p05-preparo-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** `/var/lib está montado em: /`, a linha `docker.io/vllm/vllm-openai:v0.19.1` aparece na
seção 2, `processos na GPU: (nenhum)` e os dois `HTTP 200`.

## Bloco B — Ray em 01 + 02, protocolo e limpeza (servidor `sabdiia01`, bash; aborta em outro nó)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  plano P-05"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  [ -x teste-protocolo.sh ] || { echo "ABORTA: falta teste-protocolo.sh (Bloco 1 de runbooks/teste-protocolo-modelos.md)"; exit 1; }
  grep -q e2el teste-protocolo.sh || { echo "ABORTA: teste-protocolo.sh antigo, sem E2EL: rode de novo o Bloco 1 de runbooks/teste-protocolo-modelos.md"; exit 1; }

  echo "### 1. pré-condições"
  kubectl describe nodes sabdiia01 sabdiia02 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  R=$(kubectl describe nodes sabdiia01 sabdiia02 | awk '/^  nvidia\.com\/gpu +[0-9]/{s+=$2} END{print s+0}')
  [ "$R" = 0 ] || { echo "ABORTA: GPU de 01 ou 02 reservada no Kubernetes"; exit 1; }
  A=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader)
  [ -z "$A" ] || { echo "ABORTA: processo na GPU de 01 fora do Kubernetes: $A"; exit 1; }
  nvidia-smi -q -d PERFORMANCE | grep -iE 'Thermal Slowdown +: Active' && { echo "ABORTA: GPU de 01 estrangulando antes do teste"; exit 1; }
  kubectl get pods -n vllms --no-headers 2>/dev/null | grep -E 'ray|vllm' && { echo "ABORTA: há pods do Ray/vLLM em vllms (administrador)"; exit 1; }
  kubectl get pods -n vllm-estudo --no-headers 2>/dev/null | grep . && { echo "ABORTA: há pods em vllm-estudo; apague-os antes"; exit 1; }
  ss -ltn | grep -E ':(6379|8000|10001)\b' && { echo "ABORTA: porta 6379/8000/10001 já ocupada em 01"; exit 1; }
  ctr -n k8s.io images ls -q | grep -qx 'docker.io/vllm/vllm-openai:v0.19.1' || { echo "ABORTA: imagem v0.19.1 ausente em 01: ctr -n k8s.io images pull docker.io/vllm/vllm-openai:v0.19.1"; exit 1; }
  MT=$(df --output=target /var/lib | tail -1); echo "/var/lib está montado em: $MT"
  [ "$MT" = / ] || { echo "ABORTA: /var/lib não está em /"; exit 1; }
  df -h / /home
  L=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
  [ "$L" -ge 100 ] || { echo "ABORTA: / de 01 com só ${L} G livres"; exit 1; }
  C=$(curl -s -o /dev/null -w '%{http_code}' -m 15 https://pypi.org/simple/ray/); echo "PyPI a partir de 01: HTTP $C"
  [ "$C" = 200 ] || { echo "ABORTA: 01 não alcança o PyPI (o Ray é instalado ao iniciar)"; exit 1; }
  echo "Hugging Face a partir de 01: HTTP $(curl -s -o /dev/null -w '%{http_code}' -m 15 https://huggingface.co/api/models/Qwen/Qwen2.5-14B-Instruct)"
  ping -c 2 -W 1 -M do -s 1472 192.168.50.152 >/dev/null || { echo "ABORTA: ping de 1472 bytes sem fragmentar a 02 falha"; exit 1; }
  echo "MTU bond0.500 em 01: $(cat /sys/class/net/bond0.500/mtu)"

  echo "### 2. manifesto e criação dos pods   $(date +%T)"
  kubectl create namespace vllm-estudo --dry-run=client -o yaml | kubectl apply -f -
  cat > P-05-ray-pp2.yaml <<'EOF'
# Plano de testes P-05: Qwen/Qwen2.5-14B-Instruct FP16, Ray do estudo (vllm-estudo), PP 2: head em sabdiia01, worker em sabdiia02.
# vLLM v0.19.1, Ray 2.48.0, protocolo comum. Pods de teste (restartPolicy Never), apagados no fim do bloco.
# hostNetwork: API em 192.168.50.151:8000 e GCS do Ray em :6379, sem autenticação, só durante o teste.
# Cache do Hugging Face em /var/lib/vllm-estudo/hf-cache (disco /), porque o /home de 01 tinha 33 G livres.
apiVersion: v1
kind: Pod
metadata:
  name: ray-pp2-worker
  namespace: vllm-estudo
  labels: {app: ray-pp2, plano: P-05}
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
      L=$(df -BG --output=avail /hf-cache | tail -1 | tr -dc 0-9); echo "livre em /hf-cache: ${L} G"
      [ "$L" -ge 60 ] || { echo "ABORTA: /hf-cache com só ${L} G livres (o modelo ocupa ~30 G)"; exit 1; }
      python3 -c "import ray" 2>/dev/null || uv pip install --system "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0" || python3 -m pip install "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0"
      python3 -c "import ray, cupy; print('ray', ray.__version__, 'cupy', cupy.__version__)"
      HF_HUB_OFFLINE=0 python3 -c "from huggingface_hub import snapshot_download as s; print('pesos em', s('Qwen/Qwen2.5-14B-Instruct', allow_patterns=['*.safetensors','*.json','*.model','*.txt','*.tiktoken','*.py']))"
      du -sh /hf-cache/hub/models--Qwen--Qwen2.5-14B-Instruct
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
    hostPath: {path: /var/lib/vllm-estudo/hf-cache, type: DirectoryOrCreate}
  - name: shm
    emptyDir: {medium: Memory, sizeLimit: 16Gi}
---
apiVersion: v1
kind: Pod
metadata:
  name: ray-pp2-head
  namespace: vllm-estudo
  labels: {app: ray-pp2, plano: P-05}
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
      L=$(df -BG --output=avail /hf-cache | tail -1 | tr -dc 0-9); echo "livre em /hf-cache: ${L} G"
      [ "$L" -ge 60 ] || { echo "ABORTA: /hf-cache com só ${L} G livres (o modelo ocupa ~30 G)"; exit 1; }
      python3 -c "import ray" 2>/dev/null || uv pip install --system "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0" || python3 -m pip install "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0"
      python3 -c "import ray, cupy; print('ray', ray.__version__, 'cupy', cupy.__version__)"
      HF_HUB_OFFLINE=0 python3 -c "from huggingface_hub import snapshot_download as s; print('pesos em', s('Qwen/Qwen2.5-14B-Instruct', allow_patterns=['*.safetensors','*.json','*.model','*.txt','*.tiktoken','*.py']))"
      du -sh /hf-cache/hub/models--Qwen--Qwen2.5-14B-Instruct
      ray start --head --node-ip-address=192.168.50.151 --port=6379 --num-gpus=1 --object-store-memory=4000000000
      echo "aguardando 2 GPUs no Ray..."
      until python3 -c "import ray, sys; ray.init(address='auto', logging_level='ERROR'); sys.exit(0 if ray.cluster_resources().get('GPU', 0) >= 2 else 1)" 2>/dev/null; do sleep 10; done
      ray status
      echo "2 GPUs no Ray; subindo o vLLM"
      exec vllm serve Qwen/Qwen2.5-14B-Instruct \
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
    hostPath: {path: /var/lib/vllm-estudo/hf-cache, type: DirectoryOrCreate}
  - name: shm
    emptyDir: {medium: Memory, sizeLimit: 16Gi}
EOF
  kubectl apply -f P-05-ray-pp2.yaml

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
    echo "### 5. protocolo   $(date +%T)"
    bash teste-protocolo.sh vllm-estudo pod/ray-pp2-head pod/ray-pp2-worker
  else
    echo "### 4. FALHOU A SUBIDA: eventos dos pods"
    kubectl describe pod -n vllm-estudo ray-pp2-head ray-pp2-worker | grep -A15 '^Events:'
  fi

  echo "### 6. logs completos dos dois pods em arquivo próprio; aqui, o arranque e o fim"
  for p in ray-pp2-worker ray-pp2-head; do
    LP=P-05-$p-$(date +%F-%H%M).log
    kubectl logs -n vllm-estudo $p > $LP 2>&1
    echo "## $p ($(wc -l < $LP) linhas em $LP): arranque"
    grep -vE 'GET /health|POST /v1/|GET /metrics|loggers.py' $LP | head -250
    echo "## $p: fim"; tail -20 $LP
  done

  echo "### 7. limpeza: apaga os dois pods e libera as GPUs   $(date +%T)"
  kubectl delete pod -n vllm-estudo ray-pp2-head ray-pp2-worker --wait=true --timeout=180s
  kubectl describe nodes sabdiia01 sabdiia02 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  df -h /
  echo "== fim $(date -Is)"
} 2>&1 | tee P-05-ray-pp2-$(hostname -s)-$(date +%F-%H%M).log
```

**Não interrompa com Ctrl+C.** Os *pods* continuam e seguram as GPUs. Se precisar parar:

```bash
# servidor sabdiia01 ou sabdiia02, bash
kubectl delete pod -n vllm-estudo ray-pp2-head ray-pp2-worker --ignore-not-found
kubectl describe nodes sabdiia01 sabdiia02 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
```

## Trazer os logs (estação, PowerShell)

```powershell
scp "root@192.168.50.151:/home/utec/vllm-estudo/P-05-*.log" "C:\www\vllm-master\logs-analysis\"
scp "root@192.168.50.151:/home/utec/vllm-estudo/P-05-ray-pp2.yaml" "C:\www\vllm-master\logs-analysis\"
scp "root@192.168.50.152:/home/utec/vllm-estudo/p05-preparo-*.log" "C:\www\vllm-master\logs-analysis\"
scp -r "root@192.168.50.151:/home/utec/vllm-estudo/testes" "C:\www\vllm-master\logs-analysis\"
```

## O que olhar

| Onde | O que | Leitura |
|---|---|---|
| Seção 1 | `/var/lib está montado em: /` e `HTTP 200` no Hugging Face | Cache no disco grande; 01 alcança o Hub |
| Seção 3 | `pronto=1` | Subiu. Com `pronto=0`, veja a seção 6 |
| Seção 4 | `ray status`: 2 nós, `2.0/2.0 GPU` | Os dois nós entraram no Ray |
| Seção 5 → `### 2` | `Model loading took` **duas vezes** (~13,8 GiB cada), `GPU KV cache size` | Compare com 61.440 *tokens* do P-01 e com a expectativa (~140 mil) |
| Seção 5 → `### 4` | `RESPOSTA:` | Tem de dizer Brasília, em frase coerente |
| Seção 5 → `### 9` | linhas da Tabela 3, agora com E2EL | Compare com o P-01 (`T-003`): c=1 48,7 *tok*/s; c=32 194,6. Leitura do c=32 na tabela da Expectativa |
| Seção 5 → `### 7` e `### 8` | estrangulamento de 01 **e** de 02 | Ativo = o número é da refrigeração |

**Falhas prováveis** (seção 6):

| Mensagem | Causa provável | O que fazer |
|---|---|---|
| `ABORTA: /hf-cache com só ... G livres` | `/` do nó mais cheio que em 2026-10-28 | Ver `df -h /` do nó; não apague nada sem combinar |
| erro de rede no `snapshot_download` | O nó não alcança o Hugging Face | Ver a linha `HTTP` (esperado 200) |
| `ErrImagePull` / `context canceled` no *worker* | Imagem ausente em 02 | Bloco A (AC-24) |
| `CUDA out of memory` / `No available memory for the cache blocks` | Etapas desiguais: uma GPU com mais camadas | Anote o `Model loading took` de cada GPU e traga o log |
| Mensagens de `NCCL`, `VLLM_HOST_IP` ou Compiled Graph | Mesmas do `T-002` | Tabela de falhas de [teste-ray-pp2-qwen25-7b.md](teste-ray-pp2-qwen25-7b.md) |

## Depois

1. Registre como `T-007` nas Tabelas 1-3 do registro (arranjo "Ray PP 2: 1 GPU em `sabdiia01` + 1 em
   `sabdiia02` (`ray 2.48.0`)") e anote `T-007` na coluna **Teste** do P-05 (seção 9).
2. O resultado do c=32 decide a ordem do resto da onda 2 (tabela "Como ler o c=32").
3. O modelo fica em `/var/lib/vllm-estudo/hf-cache` de 01 e de 02 (~30 GB em cada).
