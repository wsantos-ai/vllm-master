# Runbook — Inventário do ambiente

**Quando rodar:** antes do primeiro arranque do vLLM, e de novo a cada mudança de driver, versão do K8s,
*device plugin* ou nó. A saída preenche §2 (Ficha do ambiente) do [estudo de caso](../ESTUDO-DE-CASO.md).

**Expectativa escrita antes (preencha):** ______________________________________

**Onde ficam os logs.** Todo bloco começa com
`mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo`, e o `tee` grava ali, no nó em que o
bloco rodou. Os Blocos 1 a 1d e 3 rodam onde houver `kubectl`; o Bloco 2 roda em cada um dos 3 nós, e
cada nó fica com o seu log. Logs anteriores a 2026-09-29 ficaram em `/home/utec/` (Bloco 1c, em
`sabdiia03`).

**Traga o `.log`**, em vez de copiar a tela do terminal: a cópia de tela vem em RTF, com o eco dos
comandos e caracteres de controle (aconteceu no Bloco 1c).

Estação Windows, PowerShell. Traz os logs dos 3 nós para `logs-analysis/`; um nó sem a pasta só dá
erro naquele `scp`:

```powershell
foreach ($ip in "192.168.50.151", "192.168.50.152", "192.168.50.150") {
  scp "root@${ip}:/home/utec/vllm-estudo/*.log" "C:\www\vllm-master\logs-analysis\"
}
```

**Cole cada bloco inteiro, de uma vez, do `mkdir` até o `tee`.** Colado em pedaços, o bash executa as
linhas soltas, não grava o log e termina com `syntax error near unexpected token '}'` (aconteceu no
Bloco 1b em 2026-09-28).

| Bloco | Estado |
|---|---|
| 1 — *cluster* | executado 2026-09-28 |
| 1b — ocupação de GPU e `vllms` | executado 2026-09-28 (sem a primeira seção) |
| 1c — logs das implantações existentes | executado 2026-09-29 |
| 1d — acesso do *token* HF | executado 2026-09-29: *token* inválido |
| 2 — cada nó | executado 2026-09-29 nos 3 nós |
| 2b — imagens e espaço em `/` | executado 2026-09-29 (`crictl` ausente em 01 e 02) |
| 2c — imagens de 01/02 e limiares do *kubelet* | executado 2026-09-29 |
| 3 — GPU no *pod* | executado 2026-09-29 11:38: OK, 1 V100S no *pod* (antes, 3 falhas por *placeholder*) |

---

## Bloco 1 — Visão do *cluster* (servidor, bash, máquina com `kubectl`)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### kubectl version";            kubectl version
  echo "### nodes";                      kubectl get nodes -o wide
  echo "### GPUs alocáveis por nó";      kubectl get nodes -o custom-columns='NODE:.metadata.name,GPU_ALLOC:.status.allocatable.nvidia\.com/gpu,GPU_CAP:.status.capacity.nvidia\.com/gpu'
  echo "### pods NVIDIA / GPU";          kubectl get pods -A -o wide | grep -iE 'nvidia|gpu'
  echo "### runtimeclasses";             kubectl get runtimeclass
  echo "### storageclasses";             kubectl get storageclass
  echo "### PVs";                        kubectl get pv
} 2>&1 | tee inventario-cluster-$(date +%F-%H%M).log
```

O que olhar:

- Coluna `CONTAINER-RUNTIME` de `get nodes` (`containerd://` ou `docker://`).
- `GPU_ALLOC` vazio (`<none>`): o K8s não enxerga as GPUs; falta *device plugin* ou GPU Operator.
- *Pods* de `nvidia-device-plugin` ou do `gpu-operator`.

## Bloco 1b — Ocupação de GPU e o *namespace* `vllms` (servidor, bash, máquina com `kubectl`)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### consumidores de GPU (todos os namespaces)"
  kubectl get pods -A -o custom-columns='NS:.metadata.namespace,POD:.metadata.name,NODE:.spec.nodeName,PHASE:.status.phase,GPU:.spec.containers[*].resources.limits.nvidia\.com/gpu' | grep -v '<none>'
  echo "### labels GPU dos nós (GFD)";   kubectl describe nodes | grep -E '^Name:|nvidia\.com/(gpu|cuda|mig)'
  echo "### taints";                     kubectl describe nodes | grep -E '^Name:|^Taints:'
  echo "### recursos alocados por nó";   kubectl describe nodes | grep -E '^Name:|^  (cpu|memory|nvidia\.com/gpu) +[0-9]'
  echo "### namespace vllms";            kubectl get all,pvc,cm,ingress -n vllms -o wide
  echo "### secrets vllms (só nomes)";   kubectl get secret -n vllms
  echo "### manifestos vllms";           kubectl get deploy,statefulset,svc -n vllms -o yaml
} 2>&1 | tee inventario-vllms-$(date +%F-%H%M).log
```

**Antes de copiar este log para o repositório**, procure *tokens* no YAML (`grep -iE 'token|key|secret'`):
`env` com valor literal vaza segredo. Troque o valor por `<REMOVIDO>`.

## Bloco 1c — Logs das implantações existentes (servidor, bash, máquina com `kubectl`)

Motivo: PD-09 (por que a `v0.12.0` cai) e PD-10 (linha de base do que já roda). Só leitura: não reinicia
nem altera nada.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### llama31-8b: log da última execução que caiu"
  kubectl logs -n vllms deploy/vllm-llama31-8b --previous --tail=300
  echo "### llama31-8b: estado do contêiner e eventos"
  kubectl describe pod -n vllms -l app=vllm-llama31-8b | sed -n '/^Containers:/,$p'
  echo "### deepseek-33b: última queda (18 reinícios)"
  kubectl logs -n vllms deploy/vllm-deepseek-33b --previous --tail=80
  echo "### deepseek-33b: arranque, até o servidor subir"
  kubectl logs -n vllms deploy/vllm-deepseek-33b | sed -n '1,/Uvicorn running/p' | head -400
  echo "### deepseek-33b: modelos e versão"
  curl -s --max-time 10 http://192.168.50.160:8001/v1/models; echo
  curl -s --max-time 10 http://192.168.50.160:8001/version; echo
  echo "### deepseek-33b: métricas do vLLM"
  curl -s --max-time 10 http://192.168.50.160:8001/metrics | grep -E '^vllm:' | head -80
} 2>&1 | tee inventario-vllms-logs-$(date +%F-%H%M).log
```

**Antes de copiar o log**, confira se ele traz *prompts* de usuários (versões antigas do vLLM registram
as requisições no log). Se trouxer, apague essas linhas.

O que olhar:

- `llama31-8b`: a última exceção antes de sair. Mensagem sobre *compute capability*, *kernel*, CUDA ou
  `sm_70` responde PD-03; erro de acesso ao modelo (*gated*) ou de memória é outra história.
- `deepseek-33b`: no arranque, a memória dos *weights*, os blocos de *KV cache* e o *backend* de
  *attention* escolhido.

## Bloco 1d — O *token* HF tem acesso a modelos *gated*? (servidor, bash, máquina com `kubectl`)

Motivo: PD-12 / [AC-07](../ESTUDO-DE-CASO.md#ac-07). **Roda um `exec` dentro do *pod* do deepseek**
(reaproveita o `HF_TOKEN` que já está lá). Não reinicia nem altera o *pod*, mas grava cerca de 1 KB
(`config.json`) no PVC `hf-cache`. Rode só se estiver de acordo com isso.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### usuário do token";
  kubectl exec -n vllms deploy/vllm-deepseek-33b -- python3 -c "from huggingface_hub import whoami; print(whoami()['name'])"
  echo "### acesso ao repositório gated da Meta";
  kubectl exec -n vllms deploy/vllm-deepseek-33b -- python3 -c "from huggingface_hub import hf_hub_download; print(hf_hub_download('meta-llama/Llama-3.1-8B-Instruct', 'config.json'))"
} 2>&1 | tee inventario-hf-token-$(date +%F-%H%M).log
```

Esperado: o nome da conta, e depois um caminho de arquivo (acesso OK) ou `GatedRepoError`. Se
`whoami` já falhar com `401`, o *token* é inválido; se `whoami` passar e o *download* falhar, a conta
não aceitou a licença do modelo.

## Bloco 2 — Cada nó (servidor, bash, em **cada um** dos 3 nós)

Já se sabe pelo Kubernetes: 32 vCPU, ~755 GiB de RAM, 1 V100S, *driver* 580.173.02. Este bloco busca o
que o Kubernetes não mostra.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### host";          hostname; uname -r
  echo "### CPU";           lscpu | grep -E 'Model name|Socket|Core|Thread|NUMA node'
  echo "### CPU flags";     grep -owE 'avx|avx2|avx512f|fma|f16c' /proc/cpuinfo | sort | uniq -c
  echo "### RAM";           free -h
  echo "### disco";         df -h; lsblk -o NAME,SIZE,ROTA,TYPE,MOUNTPOINT
  echo "### NFS montado";   findmnt -t nfs,nfs4
  echo "### GPU";           nvidia-smi
  echo "### GPU (csv)";     nvidia-smi --query-gpu=name,memory.total,compute_cap,pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max,power.limit --format=csv
  echo "### bond";          grep -E 'Bonding Mode|Slave Interface|Speed' /proc/net/bonding/bond0
  echo "### versões";       containerd --version; nvidia-ctk --version; docker version
} 2>&1 | tee inventario-no-$(hostname -s)-$(date +%F-%H%M).log
```

O que olhar:

- `avx2` ausente: registre. Pode afetar componentes que rodam em CPU `[hipótese]`.
- PCIe: `gen`/`width` máximos. A geração atual cai com a GPU ociosa, então compare os valores máximos.
- Disco local não rotacional com espaço livre: candidato a cache de modelos (PD-04).
- `bond0`: velocidade dos *links* (PD-07).
- Comando ausente (`command not found`) também é dado.

## Bloco 2b — Imagens e espaço em `/` (servidor, bash, em **cada um** dos 3 nós)

Motivo: PD-14 / [AC-09](../ESTUDO-DE-CASO.md#ac-09). `/` tem só 20-28 G livres e guarda as imagens do
containerd. Rode antes de baixar qualquer imagem nova do vLLM. Só leitura.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### host";                 hostname
  echo "### espaço em /";          df -h /
  echo "### diretório do containerd"; du -sh /var/lib/containerd 2>/dev/null
  echo "### imagens no nó";        crictl --runtime-endpoint unix:///run/containerd/containerd.sock images 2>/dev/null || ctr -n k8s.io images ls
  echo "### limiares do kubelet";  grep -iE 'evictionHard|imageGC|nodefs|imagefs' /var/lib/kubelet/config.yaml || echo "(nenhum limiar no config.yaml: valem os padrões)"
} 2>&1 | tee imagens-no-$(hostname -s)-$(date +%F-%H%M).log
```

O que olhar: o tamanho das imagens `vllm/vllm-openai` já baixadas, e quanto sobra em `/` depois de
somar uma imagem nova do mesmo porte. `crictl` só existe em `sabdiia03`; nos outros o bloco usa `ctr`.

Executado em 2026-09-29 na versão anterior (sem a alternativa `ctr`). Complemento no Bloco 2c.

## Bloco 2c — Imagens de 01/02 e limiares efetivos do *kubelet* (servidor, bash, em **cada um** dos 3 nós)

Motivo: PD-14. Só leitura. O `configz` pede ao *kubelet* do próprio nó a configuração **em vigor**,
com os padrões incluídos, algo que o `config.yaml` não mostra.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### host";                         hostname
  echo "### imagens de vLLM e Open WebUI"; ctr -n k8s.io images ls | awk 'NR==1 || /vllm|open-webui/'
  echo "### número de imagens no nó";      ctr -n k8s.io images ls -q | wc -l
  echo "### kubelet em vigor: GC de imagens e expulsão"
  kubectl get --raw "/api/v1/nodes/$(hostname -s)/proxy/configz" | tr ',{}' '\n\n\n' | grep -iE 'imageGC|imageMinimumGCAge|imagefs|nodefs|memory.available'
} 2>&1 | tee imagens-kubelet-$(hostname -s)-$(date +%F-%H%M).log
```

O que olhar: `imageGCHighThresholdPercent` (ocupação de `/` em que o *kubelet* começa a apagar imagens
sem uso) e `imagefs.available`/`nodefs.available` em `evictionHard` (espaço livre abaixo do qual ele
expulsa *pods*). Com `/` de 70 G, converta os percentuais em GB e compare com o livre de cada nó.

## Bloco 3 — A GPU chega ao *pod*? (servidor, bash, máquina com `kubectl`)

Roda em `sabdiia02`, o único nó com GPU livre. Imagem `nvidia/cuda:12.4.1-base-ubuntu22.04` (CUDA 12.4
≤ 13.0 do *driver*; *tag* conferida no Docker Hub em 2026-09-29, [F-001](../FONTES.md)). A imagem *base*
não traz `nvidia-smi`: ele vem do *driver* do *host*, injetado pelo *container toolkit*. Nada a
preencher. Cria um *pod* no *namespace* `default` e o apaga no fim.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  kubectl delete pod teste-gpu --ignore-not-found
  kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: teste-gpu
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: sabdiia02
  containers:
  - name: cuda
    image: nvidia/cuda:12.4.1-base-ubuntu22.04
    command: ["nvidia-smi"]
    resources:
      limits:
        nvidia.com/gpu: 1
EOF
  echo "### aguardando o pod terminar"
  kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/teste-gpu --timeout=300s
  echo "### saída do nvidia-smi dentro do pod";  kubectl logs teste-gpu
  echo "### estado e eventos (diagnóstico)";      kubectl describe pod teste-gpu | sed -n '/^Containers:/,$p'
  kubectl delete pod teste-gpu
} 2>&1 | tee teste-gpu-pod-$(date +%F-%H%M).log
```

Esperado: `nvidia-smi` dentro do *pod* mostra **uma** V100S. Se mostrar outra coisa, é achado.

Execuções de 2026-09-29 (10:49, 11:14, 11:31) falharam com `InvalidImageName`: o bloco da época pedia
para preencher `CUDA_IMAGE` e trazia o *placeholder* `PREENCHA-nvidia/cuda:<tag-base>`, que não é um nome
de imagem válido. O log só registrava a saída do `kubectl logs`, sem o nome da imagem usado.
