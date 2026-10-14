# Comandos úteis — glossário

Comandos usados neste estudo, agrupados pela pergunta que respondem. Cada um tem a máquina e o *shell*
onde roda e se já foi executado neste ambiente (`[executado AAAA-MM-DD]`) ou só preparado
(`[não executado]`). Todos são de **leitura**, salvo aviso. Procedimentos completos, com gravação de
log, estão em [runbooks/inventario-do-ambiente.md](runbooks/inventario-do-ambiente.md).

Convenção do Kubernetes usada abaixo: `-A` = todos os *namespaces*; `-n vllms` = só o *namespace*
`vllms`; `-o wide` = colunas extras (nó, IP); `deploy/<nome>` = "o *pod* atual deste *deployment*",
que não quebra quando o nome do *pod* muda.

---

## 1. O *cluster* e os nós

Servidor, bash, qualquer nó com `kubectl`.

```bash
# versão do cliente e do servidor Kubernetes                         [executado 2026-09-28]
kubectl version

# nós: papel, IP, SO, kernel, runtime de contêiner                    [executado 2026-09-28]
kubectl get nodes -o wide

# taints de cada nó (o que impede pods de agendar ali)                [executado 2026-09-28]
kubectl describe nodes | grep -E '^Name:|^Taints:'

# CPU, memória e GPU já reservadas por nó (ver "Qual GPU está livre?") [executado 2026-10-02]
kubectl describe nodes | grep -E '^Name:|^  (cpu|memory|nvidia\.com/gpu) +[0-9]'
```

## 2. GPUs

```bash
# quantas GPUs cada nó oferece ao Kubernetes                          [executado 2026-09-28]
kubectl get nodes -o custom-columns='NODE:.metadata.name,GPU_ALLOC:.status.allocatable.nvidia\.com/gpu,GPU_CAP:.status.capacity.nvidia\.com/gpu'

# modelo, memória, compute capability, driver e CUDA (labels do GFD)  [executado 2026-09-28]
kubectl describe nodes | grep -E '^Name:|nvidia\.com/(gpu|cuda|mig)'

# quais pods reservam GPU, em que nó                                  [não executado]
kubectl get pods -A -o custom-columns='NS:.metadata.namespace,POD:.metadata.name,NODE:.spec.nodeName,PHASE:.status.phase,GPU:.spec.containers[*].resources.limits.nvidia\.com/gpu' | grep -v '<none>'

# componentes do NVIDIA GPU Operator                                  [executado 2026-09-28]
kubectl get pods -A -o wide | grep -iE 'nvidia|gpu'

# RuntimeClasses (como a GPU chega ao contêiner)                      [executado 2026-09-28]
kubectl get runtimeclass
```

No próprio nó, sem Kubernetes (servidor, bash, em cada nó):

```bash
# estado da GPU e processos que a usam (ECC, persistence, memória)    [executado 2026-09-29]
nvidia-smi

# resumo em CSV: modelo, memória, compute capability, PCIe atual/máx  [executado 2026-09-29]
nvidia-smi --query-gpu=name,memory.total,compute_cap,pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max,power.limit --format=csv
```

### Qual GPU está livre?

São duas perguntas, e as respostas podem divergir: uma GPU **reservada** por um *pod* fica indisponível
para o Kubernetes mesmo que esteja parada (caso de `sabdiia01`).

```bash
# 1. RESERVADA no Kubernetes? (servidor, bash, qualquer nó)           [executado 2026-10-02]
#    colunas: Requests e Limits. "0 0" = livre; "1 1" = reservada
kubectl describe nodes | grep -E '^Name:|^  (cpu|memory|nvidia\.com/gpu) +[0-9]'

#    quem reservou: pods com GPU, e em que nó                         [não executado]
kubectl get pods -A -o custom-columns='NS:.metadata.namespace,POD:.metadata.name,NODE:.spec.nodeName,PHASE:.status.phase,GPU:.spec.containers[*].resources.limits.nvidia\.com/gpu' | grep -v '<none>'

# 2. EM USO de fato? (servidor, bash, no próprio nó)                  [não executado nesta forma]
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
```

Saída do primeiro comando em 2026-10-02 (igual à de 2026-09-28):

```
Name:               sabdiia01
  cpu                5395m (16%)   12500m (39%)
  memory             33518Mi (4%)  73488Mi (9%)
  nvidia.com/gpu     1             1
Name:               sabdiia02
  cpu                1435m (4%)   2 (6%)
  memory             1248Mi (0%)  5108Mi (0%)
  nvidia.com/gpu     0            0
Name:               sabdiia03
  cpu                5135m (16%)   8 (25%)
  memory             17078Mi (2%)  33950Mi (4%)
  nvidia.com/gpu     1             1
```

| Nó | Reservada | Por quem | Uso real (`nvidia-smi`, 2026-09-29) | Conclusão |
|---|---|---|---|---|
| `sabdiia01` | sim até 12:50; **não** depois | `vllm-llama31-8b`, desligado com `--replicas=0` às 12:50 | 0 MiB | **livre** desde 2026-10-02 12:50 |
| `sabdiia02` | **não** | — | 0 MiB | **livre** |
| `sabdiia03` | sim | `vllm-deepseek-33b` | 28.598 MiB | em uso (AC-05) |

As linhas de `cpu` e `memory` mostram o que já está reservado em cada nó, em valor e em percentual do
total (32 vCPU e ~755 GiB): `sabdiia02` tem 4 % de CPU e menos de 1 % de memória comprometidos.

### A GPU está estrangulando por temperatura?

Servidor, bash, no próprio nó. Rode **durante a carga**: parada, a GPU não mostra o problema (AC-17).

```bash
# temperatura, potência, clock atual × máximo e uso, a cada 2 s (Ctrl+C para)   [executado 2026-10-14, sabdiia01]
nvidia-smi --query-gpu=timestamp,temperature.gpu,power.draw,clocks.sm,clocks.max.sm,utilization.gpu,pstate --format=csv -l 2

# por que o clock está reduzido: procure "SW Thermal Slowdown : Active"         [executado 2026-10-14, sabdiia01]
nvidia-smi -q -d PERFORMANCE

# a partir de que temperatura a GPU reduz o clock                               [não executado]
nvidia-smi -q -d TEMPERATURE

# a cota de CPU do pod está pausando o processo? (nr_throttled, throttled_usec) [executado 2026-10-14]
kubectl exec -n vllm-estudo vllm-conc -- cat /sys/fs/cgroup/cpu.stat
```

## 2b. O *host*: CPU, memória, disco, rede

Servidor, bash, em cada nó.

```bash
# CPU: modelo, sockets, núcleos, NUMA                                 [executado 2026-09-29]
lscpu | grep -E 'Model name|Socket|Core|Thread|NUMA node'

# quais extensões vetoriais a CPU tem (AVX2 ausente aqui)             [executado 2026-09-29]
grep -owE 'avx|avx2|avx512f|fma|f16c' /proc/cpuinfo | sort | uniq -c

# memória e swap                                                      [executado 2026-09-29]
free -h

# espaço por sistema de arquivos; discos e se são rotacionais         [executado 2026-09-29]
df -h
lsblk -o NAME,SIZE,ROTA,TYPE,MOUNTPOINT

# montagens NFS e suas opções (versão, rsize, nconnect)               [executado 2026-09-29]
findmnt -t nfs,nfs4

# bond de rede: modo e velocidade de cada porta                       [executado 2026-09-29]
grep -E 'Bonding Mode|Slave Interface|Speed' /proc/net/bonding/bond0

# bond em detalhe: política de hash e em que agregador está cada porta [executado 2026-10-02, sabdiia01]
# (porta com Aggregator ID diferente do ativo NÃO carrega dados, AC-08)
grep -E 'Bonding Mode|Transmit Hash Policy|MII Status|Slave Interface|Speed|Duplex|Link Failure Count|Aggregator ID' /proc/net/bonding/bond0

# o que a placa e o switch anunciam e o que foi negociado              [executado 2026-10-02, sabdiia01]
ethtool enp65s0f1

# pacotes, erros e descartes de uma porta                              [executado 2026-10-02, sabdiia01]
ip -s link show enp65s0f1

# vazão real de UMA conexão até outro nó, sem instalar nada           [executado 2026-10-02: 98,3 MB/s]
# (perto de 100 MB/s = porta de 1 Gbps; ~11 MB/s = porta de 100 Mbps; pede a senha de root do destino)
dd if=/dev/zero bs=1M count=3000 status=progress | ssh root@192.168.50.152 'cat > /dev/null'

# imagens de contêiner no nó e seu tamanho (crictl só em sabdiia03)  [executado 2026-09-29]
crictl --runtime-endpoint unix:///run/containerd/containerd.sock images

# o mesmo sem crictl, direto no containerd (namespace k8s.io)         [executado 2026-09-29]
ctr -n k8s.io images ls

# remover uma imagem do nó e LIBERAR o espaço (ALTERA o nó)          [executado 2026-10-02, sabdiia01: liberou 27 G]
# o containerd guarda 3 referências por imagem (tag, digest e sha256:<id>); é preciso apagar as 3.
# Pare antes os pods que usam a imagem. Meça com "df -h /" antes e depois.
D=$(ctr -n k8s.io images ls | awk '$1=="docker.io/vllm/vllm-openai:v0.12.0"{print $3}')
ctr -n k8s.io images ls | awk -v d="$D" '$3==d{print $1}' | xargs -r ctr -n k8s.io images rm --sync

# NÃO FAÇA ASSIM: remover só pelo nome apaga 2 das 3 referências     [executado 2026-09-29, sabdiia02]
# e não libera espaço (AC-09)
ctr -n k8s.io images rm docker.io/vllm/vllm-openai:v0.6.4

# onde o containerd gasta disco: conteúdo comprimido × desempacotado  [executado 2026-09-29]
du -sh /var/lib/containerd/*

# leases do containerd (o que impede o GC de apagar conteúdo)         [executado 2026-09-29]
ctr -n k8s.io leases ls

# quanto o containerd ocupa em disco                                  [executado 2026-09-29]
du -sh /var/lib/containerd

# configuração EM VIGOR do kubelet de um nó (inclui padrões)          [executado 2026-09-29]
kubectl get --raw "/api/v1/nodes/sabdiia02/proxy/configz"
```

### Onde o containerd guarda as imagens (configuração em vigor)

Servidor, bash, em cada nó. Só leitura. O caminho vem da chave `root` (padrão `/var/lib/containerd`
quando a chave não está escrita). O `config dump` mostra a configuração final, já mesclada com
`imports` e com o que o NVIDIA Container Toolkit acrescentou; ler só o `config.toml` pode enganar.
Contexto: [AC-09](ESTUDO-DE-CASO.md#ac-09) e PD-15.  `[executado 2026-10-02 nos 3 nós: configuração idêntica]`

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### host";                              hostname
  echo "### configuração efetiva (mesclada)";   containerd config dump | grep -nE '^(root|state|imports|version)|root_path|snapshotter ='
  echo "### arquivos de configuração";          ls -l /etc/containerd/ /etc/containerd/conf.d/ 2>/dev/null
  echo "### root no arquivo principal";         grep -nE '^\s*(root|state|imports)\s*=' /etc/containerd/config.toml
} 2>&1 | tee containerd-config-$(hostname -s)-$(date +%F-%H%M).log
```

O que cada linha responde: `root` = onde ficam imagens, camadas e metadados; `state` = estado volátil
(`/run/containerd`); `imports` = outros arquivos que entram na configuração; `root_path` = se o
diretório das camadas desempacotadas (`overlayfs`) foi separado do `root`.

## 3. *Pods*: o que roda e onde

`kubectl get pods` lista ***pods* de um *namespace***, não nós. Um nó só aparece na coluna `NODE` se
houver *pod* daquele *namespace* rodando nele. Neste *cluster* o vLLM está em dois *namespaces*:

| *Namespace* | O que tem | Em que nó (2026-10-02) |
|---|---|---|
| `vllms` | produção, do administrador: `vllm-deepseek-33b`, `open-webui`, e o `vllm-llama31-8b` desligado (`0/0`, sem *pod*) | `sabdiia03` e `sabdiia02` |
| `vllm-estudo` | *pods* de teste deste estudo: `vllm-teste`, `vllm-qwen38` | `sabdiia01` |

Por isso `kubectl get pods -n vllms -o wide` não mostra `sabdiia01`: o único *pod* de `vllms` que rodava
lá foi desligado em 2026-10-02.

```bash
# pods de produção, com nó e IP                                       [executado 2026-10-02]
kubectl get pods -n vllms -o wide

# pods de teste do estudo                                             [não executado]
kubectl get pods -n vllm-estudo -o wide

# tudo de vLLM, nos dois namespaces                                   [não executado]
kubectl get pods -A -o wide | grep -E 'NAMESPACE|vllm'

# tudo o que roda num nó, em qualquer namespace                       [não executado]
kubectl get pods -A -o wide --field-selector spec.nodeName=sabdiia01

# deployments de produção: mostra os desligados (0/0), que não têm pod [executado 2026-10-02, via Passo 2]
kubectl get deploy -n vllms

# todos os pods de todos os namespaces                                [executado 2026-09-29]
kubectl get pods -A

# quais namespaces existem                                            [não executado]
kubectl get namespaces

# só os nomes                                                         [não executado]
kubectl get pods -n vllms -o name

# que imagem cada pod roda (distingue vLLM de outras coisas)          [não executado]
kubectl get pods -n vllms -o custom-columns='POD:.metadata.name,IMAGEM:.spec.containers[*].image,NO:.spec.nodeName'

# tudo de um namespace: pods, deployments, services, PVCs             [executado 2026-09-28]
kubectl get all,pvc,cm,ingress -n vllms -o wide

# manifestos completos (args do vLLM, probes, volumes, Service)       [executado 2026-09-28]
kubectl get deploy,statefulset,svc -n vllms -o yaml

# Secrets: só os nomes, nunca o conteúdo                              [executado 2026-09-28]
kubectl get secret -n vllms
```

Leitura rápida do `STATUS`: `Running` = no ar; `CrashLoopBackOff` = o contêiner cai e o Kubernetes
tenta de novo com espera crescente; `CreateContainerConfigError` = falta algo que o manifesto pede
(Secret, ConfigMap). A coluna `RESTARTS` conta as quedas.

## 4. Por que um *pod* não sobe

```bash
# log da ÚLTIMA execução que caiu (a causa costuma estar aqui)        [executado 2026-09-29]
kubectl logs -n vllms deploy/vllm-llama31-8b --previous --tail=300

# estado do contêiner, código de saída e eventos                      [executado 2026-09-29]
kubectl describe pod -n vllms -l app=vllm-llama31-8b | sed -n '/^Containers:/,$p'

# log da execução atual                                               [não executado nesta forma]
kubectl logs -n vllms deploy/vllm-deepseek-33b --tail=80
```

Lição do caso: leia `--previous` antes de culpar a GPU ou a versão
([AC-07](ESTUDO-DE-CASO.md#ac-07)).

## 5. A API do vLLM

Servidor, bash. `192.168.50.160:8001` é o `Service` do deepseek (sem autenticação,
[AC-06](ESTUDO-DE-CASO.md#ac-06)).

```bash
# modelos servidos e contexto máximo                                  [executado 2026-09-29]
curl -s --max-time 10 http://192.168.50.160:8001/v1/models

# geração em formato de chat (produção: sem teste de carga)           [não executado]
curl -s http://192.168.50.160:8001/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"TheBloke/deepseek-coder-33B-instruct-GPTQ","messages":[{"role":"user","content":"Olá"}],"max_tokens":50,"temperature":0}'

# pod sem Service: túnel no terminal 1, requisição no terminal 2      [não executado]
# (localhost:18000 só existe na máquina onde o port-forward roda)
kubectl port-forward -n vllm-estudo pod/vllm-teste 18000:8000
curl -s http://localhost:18000/v1/models

# chat com o raciocínio DESLIGADO (modelos Qwen3.x)                   [executado 2026-10-14, Qwen3.8-27B]
curl -s http://localhost:18000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen3.8-27B","messages":[{"role":"user","content":"Olá"}],"max_tokens":100,"temperature":0,"chat_template_kwargs":{"enable_thinking":false}}'

# métricas: KV cache, requisições, TTFT, latência por token           [executado 2026-09-29]
curl -s --max-time 10 http://192.168.50.160:8001/metrics | grep -E '^vllm:'
```

Estação Windows, PowerShell (o `curl` do PowerShell complica as aspas do JSON):  `[não executado]`

```powershell
$corpo = @{ model = "TheBloke/deepseek-coder-33B-instruct-GPTQ"; messages = @(@{ role = "user"; content = "Olá" }); max_tokens = 50; temperature = 0 } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "http://192.168.50.160:8001/v1/chat/completions" -Method Post -ContentType "application/json" -Body $corpo
```

### Qual é a versão do vLLM?

Não existe `vllm --version` para rodar no nó: o vLLM não está instalado no sistema, só dentro das
imagens de contêiner. Há três perguntas diferentes, cada uma com seu comando (servidor, bash).

```bash
# 1. versão que está RODANDO: pergunta à própria API                  [executado 2026-09-29]
#    (o deepseek respondeu {"version":"0.6.4"})
curl -s --max-time 10 http://192.168.50.160:8001/version; echo

#    o mesmo, perguntando ao Python dentro do contêiner               [não executado]
kubectl exec -n vllms deploy/vllm-deepseek-33b -- python3 -c "import vllm; print(vllm.__version__)"

#    versões das bibliotecas dentro da imagem em execução             [executado 2026-10-02]
#    (v0.19.1: bitsandbytes 0.49.2, transformers 5.5.4, torch 2.10.0+cu129 / CUDA 12.9)
kubectl exec -n vllm-estudo vllm-teste -- python3 -c "import bitsandbytes, transformers, torch; print('bitsandbytes', bitsandbytes.__version__); print('transformers', transformers.__version__); print('torch', torch.__version__, torch.version.cuda)"

# 2. versão de um pod que NÃO SOBE: primeira linha do log de arranque [executado 2026-09-29, via Bloco 1c]
#    (o llama31-8b mostrou "vLLM API server version 0.12.0")
kubectl logs -n vllms deploy/vllm-llama31-8b --previous | grep -m1 'vLLM API server version'

# 3. versões BAIXADAS num nó: tag da imagem (rodar em cada nó)        [executado 2026-09-29, via Bloco 2c]
ctr -n k8s.io images ls | awk 'NR==1 || /vllm/'
```

A *tag* da imagem (caso 3) é só um rótulo; como evidência vale o que o vLLM em execução responde
(caso 1). Estado em 2026-10-02:

| Nó | Imagem no disco | Rodando |
|---|---|---|
| `sabdiia01` | `v0.19.1` (a `v0.12.0` foi removida às 12:53) | **sim**, *pods* de teste em `vllm-estudo` (AC-13) |
| `sabdiia02` | nenhuma registrada (a `v0.6.4` saiu do registro, as camadas ficaram, AC-09) | não |
| `sabdiia03` | `v0.6.4` | **sim**, o deepseek |

## 6. Hugging Face

Rodam **dentro** do *pod* do deepseek, que tem o `HF_TOKEN`. O segundo grava ~1 KB no PVC `hf-cache`.

```bash
# o token é válido? (imprime só o nome da conta)                      [executado 2026-09-29]
kubectl exec -n vllms deploy/vllm-deepseek-33b -- python3 -c "from huggingface_hub import whoami; print(whoami()['name'])"

# o token acessa um repositório gated?                                [executado 2026-09-29]
kubectl exec -n vllms deploy/vllm-deepseek-33b -- python3 -c "from huggingface_hub import hf_hub_download; print(hf_hub_download('meta-llama/Llama-3.1-8B-Instruct', 'config.json'))"
```

## 7. Armazenamento

```bash
# classes de armazenamento disponíveis                                [executado 2026-09-28]
kubectl get storageclass

# volumes persistentes, tamanho e a quem pertencem                    [executado 2026-09-28]
kubectl get pv
```

## 8. Logs: gravar e trazer para a estação

```bash
# padrão de todo bloco do runbook (servidor, bash)
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ comandos...; } 2>&1 | tee <descricao>-$(date +%F-%H%M).log

# onde estou e quais logs existem (servidor, bash)                    [não executado]
pwd
ls -lt /home/utec/vllm-estudo/*.log
find / -xdev -name 'inventario-*.log' 2>/dev/null
```

Estação Windows, PowerShell: traz os logs dos 3 nós para `logs-analysis/`. `[não executado]`

```powershell
foreach ($ip in "192.168.50.151", "192.168.50.152", "192.168.50.150") {
  scp "root@${ip}:/home/utec/vllm-estudo/*.log" "C:\www\vllm-master\logs-analysis\"
}
```
