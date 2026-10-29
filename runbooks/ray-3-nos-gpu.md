# Runbook — Ray com as 3 GPUs (`sabdiia01` + `02` + `03`) e vLLM `v0.19.1`

**Para quem:** o administrador do *cluster*. É o mesmo arranjo que subiu e mediu em 2026-10-29 com 2 nós
(B-004, [runbook](teste-ray-pp2-qwen25-7b.md), [AC-23](../ESTUDO-DE-CASO.md#ac-23)), estendido a 3 nós.
O resultado esperado são 3 *pods* com 1 V100S cada, um *cluster* Ray com `3.0 GPU` e um `vllm serve`
dividido nas 3 GPUs.

**O que já foi provado e o que é novo:**

| Item | Situação |
|---|---|
| *Pod* com `nvidia.com/gpu: 1` recebe 1 V100S, sem `runtimeClassName` | `[confirmado]` 2026-09-29 (AC-10) |
| Imagem `vllm/vllm-openai:v0.19.1` + `ray[cgraph,default]==2.48.0` + `cupy-cuda12x==13.6.0`, `hostNetwork`, 01 + 02 | `[confirmado]` 2026-10-29 (B-004): Ray com `2.0 GPU`, vLLM servindo, 0 falhas |
| Entrar com o **3º nó** (`sabdiia03`) e `--pipeline-parallel-size 3` | `[não executado]` |
| *Deployments* (reinício automático) no lugar de *Pods* soltos | `[não executado]`. O B-004 usou `Pod` com `restartPolicy: Never` |

## Por que os *pods* do Ray atuais não veem a GPU

Lido em `vllms` em 2026-10-29, 14:31-14:34 ([log 1](../logs-analysis/vllm-on-8265-sabdiia01-2026-10-29-1431.log),
[log 2](../logs-analysis/vllm-llama31-api-sabdiia01-2026-10-29-1434.log)):

| # | O que está assim | Efeito | Correção neste runbook |
|---|---|---|---|
| 1 | `ray-head` e `ray-worker` com `resources={}` | O *device plugin* do GPU Operator só entrega GPU a contêiner que pede `nvidia.com/gpu` em `resources` (AC-10). Sem isso, o contêiner não tem `/dev/nvidia*` e o Ray mostra só CPU (`0.0/96.0 CPU`, nenhuma GPU em `/api/cluster_status`) | `nvidia.com/gpu: 1` em `requests` e `limits` de cada *pod* |
| 2 | Imagem `rayproject/ray:2.49.2-py311` | *Tag* sem sufixo de plataforma "aliases to `-cpu` tagged images", que são Ubuntu, sem CUDA [F-039] | Imagem `vllm/vllm-openai:v0.19.1` (CUDA 12.9.1, `sm_70` incluído, [F-036]) |
| 3 | A imagem do Ray não tem vLLM | No executor Ray, cada nó roda um pedaço do vLLM: **todos** os nós precisam da mesma versão do vLLM e do Ray | Mesma imagem nos 3, com o mesmo Ray instalado ao iniciar |
| 4 | `vllm-llama31` com 3 réplicas, cada uma com `nvidia.com/gpu: 1` (às 14:31, `Running` em 01 e 02, com 30.992 MiB na GPU de 01) | Cada nó tem **1** GPU. Enquanto outro *pod* reservá-la, o *pod* do Ray daquele nó fica `Pending` | O Bloco B lista quem segura cada GPU e para. A GPU precisa ser liberada antes |
| 5 | `sabdiia03`: `FailedCreatePodSandBox` (`name ... is reserved`, `context deadline exceeded`) em `ray-worker` e `vllm-llama31` | Nenhum *pod* nasce em 03, com ou sem GPU | O Bloco B testa 03 com um *pod* mínimo antes do Ray. Se falhar, o problema está no containerd de 03, não no Ray |
| 6 | MTU de `bond0.500` = 9000 em 03 e 1500 em 01/02 (2026-10-28) | Risco `[hipótese]` de pacote grande se perder entre 03 e os outros durante a troca entre GPUs | O Bloco A mede: `ping` de 1472 *bytes* sem fragmentar entre os 3. O ideal é igualar o MTU |

## Desenho

| Item | Valor | Por quê |
|---|---|---|
| *Namespace* | `vllm-ray` (novo) | Não se mistura com `vllms` (*Service* `ray-head`, rótulos `app=ray-head`) nem com `vllm-estudo` |
| *Head* | *Deployment* `ray-head`, `sabdiia01` (`192.168.50.151`): Ray *head* com 1 GPU + `vllm serve` | O servidor sobe pelo manifesto; `kubectl exec -it` morre com a sessão (AC-19) |
| *Workers* | *Deployments* `ray-worker-02` (`192.168.50.152`) e `ray-worker-03` (`192.168.50.150`), 1 GPU cada | Um por nó, com o IP do nó fixo (o Ray e o vLLM precisam do IP de cada nó) |
| Reinício | `strategy: Recreate`, `replicas: 1` | Nunca dois *pods* do mesmo nó disputando a única GPU |
| Rede | `hostNetwork: true`; `NCCL_SOCKET_IFNAME`/`GLOO_SOCKET_IFNAME` = `bond0.500`; `VLLM_HOST_IP` = IP do nó | `bond0.500` tem o IP do nó nos 3. O vLLM **não** copia `VLLM_HOST_IP` para os *workers*, então cada *pod* declara o seu; copia `NCCL_*` e `HF_*` [F-038] |
| Ray | `ray[cgraph,default]==2.48.0` + `cupy-cuda12x==13.6.0`, instalados ao iniciar (precisa de PyPI) | A imagem do vLLM não traz Ray [F-036]; versões fixadas nos testes da `v0.19.1` [F-038]. Sem `cgraph` o executor recusa subir |
| Modelo de validação | `Qwen/Qwen2.5-7B-Instruct` FP16, aberto, sem *token* | Já está no cache de 01 e 02 e foi o modelo do B-004. Em 03 o *pod* baixa ~15 GB |
| Cache | `hostPath` `/home/utec/vllm-estudo/hf-cache`, `HF_HOME=/hf-cache` | Cada nó lê do disco local; reaproveita o que o B-004 já baixou |
| Exposição | API em `192.168.50.151:8000` e *Service* `ClusterIP` `vllm-ray-api:8000`; painel do Ray em `192.168.50.151:8265`; GCS em `:6379`. **Sem autenticação** | Risco assumido na rede interna. Para fechar: `--api-key` lido de um `Secret`, criado fora do repositório |

## Expectativa (escrita antes)

- **Bloco B:** os 3 *pods* `gpu-check-*` saem `Succeeded` com `1 Tesla V100S-PCIE-32GB`. Se 03 falhar
  com `FailedCreatePodSandBox`, o Ray não vai subir lá até o containerd de 03 ser corrigido.
- **Bloco C:** arranque em 20-60 min `[estimativa]`, a maior parte sendo o modelo baixado em 03. O log do
  *head* traz `GPU-CHECK` com 3 linhas (uma por nó). `ray status` mostra `0.0/3.0 GPU` antes do vLLM e
  `3.0/3.0 GPU` depois.
- **Desempenho:** o 7B em 3 GPUs deve render **menos** que numa GPU só, como o 7B em 2 GPUs rendeu 22-25 %
  menos (AC-23) `[hipótese]`. O Ray serve para juntar memória para um modelo que não cabe em 32 GB, não
  para acelerar.

---

## Bloco A — **cada um dos 3 nós**, bash, como `root` (baixa a imagem e confere o nó)

Não usa `kubectl`, então roda também em `sabdiia03`. **Altera o nó:** baixa a imagem (~30 G em `/`) se ela
ainda não estiver lá. O *pull* pelo *kubelet* cai pelo limite de 5 min do containerd
(`image_pull_progress_timeout`); pelo `ctr`, levou 6 min 30 s em 02 (AC-24).

```bash
mkdir -p /home/utec/vllm-estudo/hf-cache && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)"
  echo "### 1. GPU: processos, memória, estrangulamento"
  nvidia-smi --query-gpu=name,memory.used,temperature.gpu,clocks.sm --format=csv
  A=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader)
  [ -z "$A" ] && echo "GPU livre (nenhum processo)" || echo "ATENÇÃO, GPU em uso: $A"
  nvidia-smi -q -d PERFORMANCE | grep -E 'SW Thermal Slowdown|HW Slowdown'
  echo "### 2. disco"
  df -h / /home
  echo "### 3. imagem vllm/vllm-openai:v0.19.1 no containerd"
  if ctr -n k8s.io images ls -q | grep -qx 'docker.io/vllm/vllm-openai:v0.19.1'; then
    echo "já está no nó"
  else
    echo "baixando pelo ctr   início $(date +%T)"
    time ctr -n k8s.io images pull docker.io/vllm/vllm-openai:v0.19.1 > /dev/null
    echo "ctr saiu com $?   fim $(date +%T)"
  fi
  ctr -n k8s.io images ls -q | grep vllm-openai
  echo "### 4. rede: MTU e ping de 1472 bytes sem fragmentar aos outros nós"
  echo "MTU bond0.500 = $(cat /sys/class/net/bond0.500/mtu)"
  for ip in 192.168.50.150 192.168.50.151 192.168.50.152; do
    ping -c 2 -W 1 -M do -s 1472 $ip > /dev/null && echo "$ip 1472 OK" || echo "$ip 1472 FALHA"
  done
  echo "### 5. PyPI (o Ray é instalado ao iniciar o pod)"
  echo "PyPI: HTTP $(curl -s -o /dev/null -w '%{http_code}' -m 15 https://pypi.org/simple/ray/)"
  echo "### 6. portas que o Ray e o vLLM usam no nó (hostNetwork)"
  ss -ltnp | grep -E ':(6379|8000|8265|10001)\b' || echo "6379/8000/8265/10001 livres"
  echo "### 7. containerd: sandboxes presos (problema visto em 03)"
  systemctl is-active containerd
  journalctl -u containerd --since "-2h" --no-pager | grep -E 'failed to reserve sandbox name|DeadlineExceeded' | tail -5
} 2>&1 | tee ray3-bloco-a-$(hostname -s)-$(date +%F-%H%M).log
```

**Para seguir, cada nó precisa de:**
- GPU livre (seção 1);
- a imagem listada (seção 3);
- `1472 OK` para os 3 IPs (seção 4);
- `PyPI: HTTP 200` (seção 5);
- as 4 portas livres (seção 6).

Se a seção 7 mostrar `failed to reserve sandbox name` em 03, resolva isso antes. É o containerd de 03, e o
Ray não sobe lá enquanto for assim.

## Bloco B — `sabdiia01`, bash (GPU livre no Kubernetes e um *pod* de teste por nó)

Cria e apaga 3 *pods* `gpu-check-*` em `vllm-ray`, cada um com `nvidia.com/gpu: 1`, que só listam
`/dev/nvidia*` e pedem ao PyTorch da imagem o nome da GPU. Prova separadamente que **cada nó entrega a GPU a um *pod***, sem o Ray no meio.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  echo "### 1. GPU alocável e reservada por nó (Allocated resources: pedido / limite)"
  kubectl get nodes -o custom-columns='NO:.metadata.name,GPU_ALOCAVEL:.status.allocatable.nvidia\.com/gpu'
  kubectl describe nodes sabdiia01 sabdiia02 sabdiia03 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  echo "### 2. quem segura GPU (pods ativos com nvidia.com/gpu)"
  OCUP=$(kubectl get pods -A --field-selector=status.phase!=Succeeded,status.phase!=Failed \
    -o jsonpath='{range .items[*]}{.spec.nodeName}{" "}{.metadata.namespace}/{.metadata.name}{" "}{.spec.containers[*].resources.limits.nvidia\.com/gpu}{"\n"}{end}' | awk 'NF==3')
  [ -z "$OCUP" ] && echo "nenhum pod com GPU" || { echo "$OCUP"; echo "ABORTA: libere as GPUs acima antes (cada nó tem 1 GPU)"; exit 1; }
  echo "### 3. GPU Operator"
  kubectl get pods -n gpu-operator -o wide | grep -E 'NAME|device-plugin|container-toolkit|driver|validator'
  echo "### 4. pod de teste com 1 GPU em cada nó   $(date +%T)"
  kubectl create namespace vllm-ray --dry-run=client -o yaml | kubectl apply -f -
  for n in sabdiia01 sabdiia02 sabdiia03; do
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata: {name: gpu-check-$n, namespace: vllm-ray}
spec:
  nodeSelector: {kubernetes.io/hostname: $n}
  restartPolicy: Never
  containers:
  - name: c
    image: vllm/vllm-openai:v0.19.1
    command: ["bash", "-c", "ls /dev/nvidia*; nvidia-smi -L 2>/dev/null; python3 -c 'import torch; print(torch.cuda.device_count(), torch.cuda.get_device_name(0))'"]
    resources: {limits: {nvidia.com/gpu: 1}}
EOF
  done
  for i in $(seq 1 30); do
    F=$(kubectl get pods -n vllm-ray -o jsonpath='{range .items[*]}{.status.phase}{"\n"}{end}' | grep -cE 'Succeeded|Failed')
    [ "$F" = 3 ] && break; sleep 10
  done
  kubectl get pods -n vllm-ray -o wide
  for n in sabdiia01 sabdiia02 sabdiia03; do
    echo "## gpu-check-$n"; kubectl logs -n vllm-ray gpu-check-$n 2>&1
    kubectl get pod -n vllm-ray gpu-check-$n -o jsonpath='{.status.phase}{"\n"}' | grep -q Succeeded || kubectl describe pod -n vllm-ray gpu-check-$n | grep -A12 '^Events:'
  done
  echo "### 5. apaga os pods de teste"
  kubectl delete pod -n vllm-ray gpu-check-sabdiia01 gpu-check-sabdiia02 gpu-check-sabdiia03 --ignore-not-found --wait=true
} 2>&1 | tee ray3-bloco-b-$(hostname -s)-$(date +%F-%H%M).log
```

**Para seguir:** os 3 `gpu-check-*` precisam sair `Succeeded` com a linha `1 Tesla V100S-PCIE-32GB` (1 GPU
visível). Sem GPU, o PyTorch falha e o *pod* sai `Failed`.
Se um deles ficar `Pending` ou falhar, os `Events` mostram o motivo:

| Mensagem | Significa |
|---|---|
| `Insufficient nvidia.com/gpu` | A GPU do nó está reservada por outro *pod* (seção 2) ou o *device plugin* não a anuncia (seção 1 com `0` ou vazio) |
| `FailedCreatePodSandBox` | containerd do nó, não GPU (ver Bloco A, seção 7) |
| `ErrImagePull` / `context canceled` | A imagem não foi baixada pelo `ctr` (Bloco A, seção 3) |

## Bloco C — `sabdiia01`, bash (sobe o Ray com 3 GPUs e o vLLM)

Grava `ray-3-nos-v0191.yaml`, aplica e acompanha até a API responder (até 60 min). **Não apaga nada no
fim:** o serviço fica no ar. Para remover, use o bloco de remoção abaixo.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  OCUP=$(kubectl get pods -A --field-selector=status.phase!=Succeeded,status.phase!=Failed \
    -o jsonpath='{range .items[*]}{.spec.nodeName}{" "}{.metadata.namespace}/{.metadata.name}{" "}{.spec.containers[*].resources.limits.nvidia\.com/gpu}{"\n"}{end}' | awk 'NF==3')
  [ -z "$OCUP" ] || { echo "$OCUP"; echo "ABORTA: GPU reservada por outro pod"; exit 1; }
  ss -ltn | grep -E ':(6379|8000|8265|10001)\b' && { echo "ABORTA: porta 6379/8000/8265/10001 ocupada em 01"; exit 1; }

  echo "### 1. manifesto   $(date +%T)"
  kubectl create namespace vllm-ray --dry-run=client -o yaml | kubectl apply -f -
  cat > ray-3-nos-v0191.yaml <<'EOF'
# Ray + vLLM v0.19.1 nas 3 V100S (1 por nó). Head + vllm serve em sabdiia01; workers em 02 e 03.
# Base: B-004 (2026-10-29, 01 + 02, confirmado). 3º nó e Deployments: não executados antes deste arquivo.
# Exposição: hostNetwork; API 192.168.50.151:8000 e Service ClusterIP vllm-ray-api; painel :8265; GCS :6379.
# Sem --api-key (risco assumido na rede interna).
apiVersion: apps/v1
kind: Deployment
metadata: {name: ray-worker-02, namespace: vllm-ray, labels: {app: vllm-ray}}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector: {matchLabels: {app: vllm-ray, papel: worker-02}}
  template:
    metadata: {labels: {app: vllm-ray, papel: worker-02}}
    spec:
      nodeSelector: {kubernetes.io/hostname: sabdiia02}
      hostNetwork: true
      containers:
      - name: ray
        image: vllm/vllm-openai:v0.19.1
        imagePullPolicy: IfNotPresent
        command: ["/bin/bash", "-c"]
        args:
        - |
          set -e
          python3 -c "import ray" 2>/dev/null || uv pip install --system "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0" || python3 -m pip install "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0"
          python3 -c "import ray, cupy; print('ray', ray.__version__, 'cupy', cupy.__version__)"
          HF_HUB_OFFLINE=0 python3 -c "from huggingface_hub import snapshot_download as s; print('pesos em', s('Qwen/Qwen2.5-7B-Instruct'))" || echo "aviso: sem rede para conferir o cache; segue com o cache local"
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
apiVersion: apps/v1
kind: Deployment
metadata: {name: ray-worker-03, namespace: vllm-ray, labels: {app: vllm-ray}}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector: {matchLabels: {app: vllm-ray, papel: worker-03}}
  template:
    metadata: {labels: {app: vllm-ray, papel: worker-03}}
    spec:
      nodeSelector: {kubernetes.io/hostname: sabdiia03}
      hostNetwork: true
      containers:
      - name: ray
        image: vllm/vllm-openai:v0.19.1
        imagePullPolicy: IfNotPresent
        command: ["/bin/bash", "-c"]
        args:
        - |
          set -e
          python3 -c "import ray" 2>/dev/null || uv pip install --system "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0" || python3 -m pip install "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0"
          python3 -c "import ray, cupy; print('ray', ray.__version__, 'cupy', cupy.__version__)"
          HF_HUB_OFFLINE=0 python3 -c "from huggingface_hub import snapshot_download as s; print('pesos em', s('Qwen/Qwen2.5-7B-Instruct'))" || echo "aviso: sem rede para conferir o cache; segue com o cache local"
          until timeout 3 bash -c '</dev/tcp/192.168.50.151/6379'; do echo "aguardando o head..."; sleep 5; done
          exec ray start --address=192.168.50.151:6379 --node-ip-address=192.168.50.150 --num-gpus=1 --object-store-memory=4000000000 --block
        env:
        - {name: HF_HOME, value: /hf-cache}
        - {name: HF_HUB_OFFLINE, value: "1"}
        - {name: VLLM_HOST_IP, value: "192.168.50.150"}
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
apiVersion: apps/v1
kind: Deployment
metadata: {name: ray-head, namespace: vllm-ray, labels: {app: vllm-ray}}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector: {matchLabels: {app: vllm-ray, papel: head}}
  template:
    metadata: {labels: {app: vllm-ray, papel: head}}
    spec:
      nodeSelector: {kubernetes.io/hostname: sabdiia01}
      hostNetwork: true
      containers:
      - name: vllm
        image: vllm/vllm-openai:v0.19.1
        imagePullPolicy: IfNotPresent
        command: ["/bin/bash", "-c"]
        args:
        - |
          set -e
          python3 -c "import ray" 2>/dev/null || uv pip install --system "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0" || python3 -m pip install "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0"
          python3 -c "import ray, cupy; print('ray', ray.__version__, 'cupy', cupy.__version__)"
          HF_HUB_OFFLINE=0 python3 -c "from huggingface_hub import snapshot_download as s; print('pesos em', s('Qwen/Qwen2.5-7B-Instruct'))" || echo "aviso: sem rede para conferir o cache; segue com o cache local"
          ray start --head --node-ip-address=192.168.50.151 --port=6379 --dashboard-host=0.0.0.0 --num-gpus=1 --object-store-memory=4000000000
          echo "aguardando 3 GPUs no Ray..."
          until python3 -c "import ray, sys; ray.init(address='auto', logging_level='ERROR'); sys.exit(0 if ray.cluster_resources().get('GPU', 0) >= 3 else 1)" 2>/dev/null; do sleep 10; done
          ray status
          python3 - <<'PY'
          import ray
          ray.init(address="auto", logging_level="ERROR")
          @ray.remote(num_gpus=1)
          def gpu():
              import socket, torch
              return socket.gethostname(), torch.cuda.get_device_name(0), torch.cuda.mem_get_info()[1] // 2**20
          for h, nome, mib in ray.get([gpu.options(scheduling_strategy="SPREAD").remote() for _ in range(3)], timeout=300):
              print(f"GPU-CHECK {h} {nome} {mib} MiB")
          PY
          echo "3 GPUs no Ray; subindo o vLLM"
          exec vllm serve Qwen/Qwen2.5-7B-Instruct \
            --pipeline-parallel-size 3 --distributed-executor-backend ray \
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
---
apiVersion: v1
kind: Service
metadata: {name: vllm-ray-api, namespace: vllm-ray}
spec:
  type: ClusterIP
  selector: {app: vllm-ray, papel: head}
  ports:
  - {name: http, port: 8000, targetPort: 8000}
EOF
  kubectl apply -f ray-3-nos-v0191.yaml

  echo "### 2. aguardando a API (até 60 min)   $(date +%T)"
  T0=$(date +%s); PRONTO=0
  while [ $(( $(date +%s) - T0 )) -lt 3600 ]; do
    kubectl get pods -n vllm-ray -l app=vllm-ray --no-headers -o custom-columns='P:.metadata.name,F:.status.phase,R:.status.containerStatuses[0].ready,N:.status.containerStatuses[0].restartCount' | tr '\n' ' '; echo
    [ "$(kubectl get pods -n vllm-ray -l papel=head -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null)" = true ] && { PRONTO=1; break; }
    echo "$(date +%T) head: $(kubectl logs -n vllm-ray deploy/ray-head --tail=1 2>/dev/null | cut -c1-160)"
    sleep 60
  done
  echo "pronto=$PRONTO depois de $(( ($(date +%s) - T0) / 60 )) min"
  kubectl get pods -n vllm-ray -o wide; kubectl get endpoints -n vllm-ray

  if [ $PRONTO = 1 ]; then
    echo "### 3. Ray e GPUs"
    kubectl logs -n vllm-ray deploy/ray-head | grep GPU-CHECK
    kubectl exec -n vllm-ray deploy/ray-head -- ray status
    echo "### 4. API"
    curl -s -m 10 http://192.168.50.151:8000/v1/models; echo
    curl -s -m 120 http://192.168.50.151:8000/v1/chat/completions -H 'Content-Type: application/json' \
      -d '{"model":"Qwen/Qwen2.5-7B-Instruct","messages":[{"role":"user","content":"Qual é a capital do Brasil? Responda em uma palavra."}],"max_tokens":16,"temperature":0}'; echo
  else
    echo "### 3. FALHOU A SUBIDA: eventos"
    for p in $(kubectl get pods -n vllm-ray -o name); do echo "## $p"; kubectl describe -n vllm-ray $p | grep -A12 '^Events:'; done
  fi

  echo "### 5. logs completos em arquivo próprio; aqui, o arranque e o fim"
  for d in ray-worker-02 ray-worker-03 ray-head; do
    LP=$d-$(date +%F-%H%M).log
    kubectl logs -n vllm-ray deploy/$d > $LP 2>&1
    echo "## $d ($(wc -l < $LP) linhas em $LP): arranque"
    grep -vE 'GET /health|POST /v1/|GET /metrics|loggers.py' $LP | head -250
    echo "## $d: fim"; tail -20 $LP
  done
  echo "== fim $(date -Is)"
} 2>&1 | tee ray3-bloco-c-$(hostname -s)-$(date +%F-%H%M).log
```

**Não interrompa com Ctrl+C.** Os *pods* continuam sozinhos; só o acompanhamento para. Para ver de novo:
`kubectl get pods -n vllm-ray -o wide` e `kubectl logs -n vllm-ray deploy/ray-head --tail=50`.

## O que olhar

| Onde | Esperado | Se não |
|---|---|---|
| Seção 2 | `pronto=1` | Ver seção 3 (eventos) e seção 5 (logs) |
| Seção 3, `GPU-CHECK` | 3 linhas: `sabdiia01`, `sabdiia02`, `sabdiia03`, cada uma `Tesla V100S-PCIE-32GB` | Linha faltando: aquele nó entrou no Ray sem GPU |
| Seção 3, `ray status` | 3 nós, `3.0/3.0 GPU` (o vLLM ocupa as 3) | `0.0/N GPU` = os *pods* não pediram GPU (problema 1 da tabela inicial) |
| Seção 4 | `/v1/models` lista `Qwen/Qwen2.5-7B-Instruct`; o *chat* responde "Brasília" | Sem resposta com `pronto=1`: confira as portas no nó (Bloco A, seção 6) |

**Falhas prováveis e o que significam** (procure na seção 5):

| Mensagem | Causa provável | O que fazer |
|---|---|---|
| `pip`/`uv` com erro de rede no início | O nó não alcança o PyPI | Liberar o acesso, ou gerar uma imagem derivada com o Ray já instalado |
| `Ray Compiled Graph is not installed` / `cupy is not installed but required` | `ray[cgraph]` ou `cupy` não instalou | Ver a linha `ray ... cupy ...` no início do log do *pod* |
| *Head* parado em `aguardando 3 GPUs no Ray...` | Um *worker* não entrou no Ray (6379 bloqueada, *pod* não nasceu, sem GPU) | `kubectl exec -n vllm-ray deploy/ray-head -- ray status`; log do *worker* parado |
| `_wait_until_pg_ready` citando `VLLM_HOST_IP` | O IP que o vLLM vê difere do IP do Ray | Conferir `VLLM_HOST_IP` contra `--node-ip-address` em cada *Deployment* |
| `NCCL` com `timeout`, `Connection refused` ou `unhandled system error`, só quando entra 03 | Rede de 03 (MTU 9000 × 1500) `[hipótese]` | Igualar o MTU; ou repetir só com 01 + 02 e `--pipeline-parallel-size 2` (provado no B-004) |
| `FA2 is only supported on devices with compute capability >= 8` | Aviso, não erro: a V100S usa `TRITON_ATTN` (AC-13) | Nada |

## Trocar o modelo

Edite no *Deployment* `ray-head`:
- o nome do modelo no `snapshot_download` dos 3 *Deployments* e no `vllm serve`;
- se o modelo for fechado, adicione `HF_TOKEN` vindo de um `Secret`, criado fora de qualquer repositório.

Antes de escolher, confira três regras:

- **Modelo que cabe em 1 GPU (32 GB), por exemplo o `deepseek-coder-33B-instruct-GPTQ` (30.992 MiB em 01 às
  14:31):** 3 réplicas independentes de 1 GPU rendem mais que o Ray. Dividir o 7B em 2 nós custou 22-25 % de
  vazão (AC-23).
- **GPTQ de 4 bits na V100S** usa o *kernel* `gptq_gemm`, que a própria `v0.19.1` marca como defeituoso
  (AC-15). Confira a qualidade da resposta, não só a velocidade.
- **Sem BF16 na V100S:** sempre `--dtype float16`.

## Remoção (servidor, bash, `sabdiia01`)

Apaga só o que este runbook criou e libera as 3 GPUs. O cache em `/home/utec/vllm-estudo/hf-cache` fica.

```bash
cd /home/utec/vllm-estudo
{
  kubectl delete -f ray-3-nos-v0191.yaml --ignore-not-found --wait=true
  kubectl get pods -n vllm-ray
  kubectl describe nodes sabdiia01 sabdiia02 sabdiia03 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
} 2>&1 | tee ray3-remocao-$(hostname -s)-$(date +%F-%H%M).log
```

## Logs

Traga para a estação (PowerShell) os `ray3-*.log` e os `ray-head-*`/`ray-worker-*.log` dos 3 nós:

```powershell
foreach ($ip in "192.168.50.151","192.168.50.152","192.168.50.150") {
  scp "root@${ip}:/home/utec/vllm-estudo/ray*.log" "C:\www\vllm-master\logs-analysis\"
}
scp "root@192.168.50.151:/home/utec/vllm-estudo/ray-3-nos-v0191.yaml" "C:\www\vllm-master\logs-analysis\"
```
