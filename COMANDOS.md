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

São duas perguntas, e as respostas podem divergir nos dois sentidos: uma GPU **reservada** por um *pod*
fica indisponível para o Kubernetes mesmo que esteja parada (`sabdiia01`, 2026-10-02); e uma GPU usada
**fora do Kubernetes** aparece como livre (`0 0`) estando ocupada (Ray em `sabdiia01` e `sabdiia02`,
2026-10-27, AC-19). **Só está livre a GPU que passa nas duas:** `0 0` e lista vazia em
`--query-compute-apps`.

```bash
# 1. RESERVADA no Kubernetes? (servidor, bash, qualquer nó)           [executado 2026-10-02]
#    colunas: Requests e Limits. "0 0" = livre; "1 1" = reservada
kubectl describe nodes | grep -E '^Name:|^  (cpu|memory|nvidia\.com/gpu) +[0-9]'

#    quem reservou: pods com GPU, e em que nó                         [não executado]
kubectl get pods -A -o custom-columns='NS:.metadata.namespace,POD:.metadata.name,NODE:.spec.nodeName,PHASE:.status.phase,GPU:.spec.containers[*].resources.limits.nvidia\.com/gpu' | grep -v '<none>'

# 2. EM USO de fato? (servidor, bash, no próprio nó)                  [executado 2026-10-27]
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

# a partir de que temperatura a GPU reduz o clock                               [executado 2026-10-15, via Bloco D]
nvidia-smi -q -d TEMPERATURE

# resumo de um CSV gravado com o comando acima (-l 2): temperatura máxima e clock  [não executado]
# mínimo/médio só nas amostras com a GPU em uso; passou se nenhuma amostra < 1400 MHz (Bloco E)
awk -F', ' 'NR>1 && $6+0>=90 {n++; t=$2+0; c=$4+0; if(n==1||t>tmax)tmax=t; if(n==1||c<cmin)cmin=c; s+=c; if(c<1400)baixo++} END {printf "amostras: %d | temp. max: %d C | clock min: %d MHz | clock medio: %.0f MHz | amostras com clock < 1400 MHz: %d\n", n, tmax, cmin, (n?s/n:0), baixo+0}' gpu-amostras.csv

# o que roda no nó e pode aquecer a GPU/chassi (em cada nó)                      [não executado]
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
kubectl get pods -A -o wide --field-selector spec.nodeName=$(hostname -s) | grep -v Completed
uptime; ps -eo pid,pcpu,pmem,etime,comm --sort=-pcpu | head -15
sensors                      # temperaturas das CPUs, se lm_sensors estiver instalado
ipmitool sdr type Fan        # ventoinhas do servidor, se ipmitool estiver instalado

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

# em que sistema de arquivos fica um diretório (/ ou /home?) e quantos G livres  [não executado]
# usado no P-05 para pôr o cache do Hugging Face em / (runbooks/teste-ray-pp2-qwen25-14b-p05.md)
df --output=target /var/lib | tail -1
df -BG --output=avail / | tail -1

# montagens NFS e suas opções (versão, rsize, nconnect)               [executado 2026-09-29]
findmnt -t nfs,nfs4

# bond de rede: modo e velocidade de cada porta                       [executado 2026-09-29]
grep -E 'Bonding Mode|Slave Interface|Speed' /proc/net/bonding/bond0

# bond em detalhe: política de hash e em que agregador está cada porta [executado 2026-10-02, sabdiia01]
# (porta com Aggregator ID diferente do ativo NÃO carrega dados, AC-08)
grep -E 'Bonding Mode|Transmit Hash Policy|MII Status|Slave Interface|Speed|Duplex|Link Failure Count|Aggregator ID' /proc/net/bonding/bond0

# o que a placa e o switch anunciam e o que foi negociado              [executado 2026-10-02, sabdiia01]
ethtool enp65s0f1

# todos os bonds do nó (não só bond0): modo, hash, portas, agregador  [executado 2026-10-28]
for B in /proc/net/bonding/*; do echo "### $B"; grep -E 'Bonding Mode|Transmit Hash Policy|MII Status|Slave Interface|Speed|Duplex|Link Failure Count|Aggregator ID|Number of ports' "$B"; done

# MTU e velocidade somada de cada bond                                [executado 2026-10-28]
for B in /proc/net/bonding/*; do n=$(basename "$B"); echo "$n mtu=$(cat /sys/class/net/$n/mtu) speed=$(cat /sys/class/net/$n/speed 2>&1)"; done

# placas de rede instaladas (1 GbE, 10/40 GbE, InfiniBand)             [executado 2026-10-28]
lspci | grep -iE 'ethernet|network|infiniband'

# interfaces, IPs e rotas em uma tela                                  [executado 2026-10-28]
ip -br link; ip -br addr; ip route

# por qual interface sai o tráfego para o NFS (IPv6)                   [executado 2026-10-28, sabdiia03]
ip -6 route get 2801:80:f8c:302::aa

# MTU de cada interface (VLANs e túnel do Calico incluídos)            [executado 2026-10-28, sabdiia03]
ip -o link | awk '{print $2, $4, $5}'

# RTT a 02 pela rede nova (bond1, IPv6 da VLAN 302)                    [executado 2026-10-28, de sabdiia03: 0,311 ms]
ping -6 -c 100 -i 0.2 -q 2801:80:f8c:302:b8:2a:72d5:2599

# por qual IP o Calico manda o tráfego entre pods de nós diferentes    [executado 2026-10-28]
kubectl get nodes -o custom-columns='NO:.metadata.name,CALICO_IPV4:.metadata.annotations.projectcalico\.org/IPv4Address'

# volumes LVM: tamanho de / e /home depois de redimensionar (root)     [executado 2026-10-28]
vgs; lvs -o lv_name,vg_name,lv_size

# pacotes, erros e descartes de uma porta                              [executado 2026-10-02, sabdiia01]
ip -s link show enp65s0f1

# vazão real de UMA conexão até outro nó, sem instalar nada           [executado 2026-10-02: 98,3 MB/s]
# (perto de 100 MB/s = porta de 1 Gbps; ~11 MB/s = porta de 100 Mbps; pede a senha de root do destino)
dd if=/dev/zero bs=1M count=3000 status=progress | ssh root@192.168.50.152 'cat > /dev/null'

# imagens de contêiner no nó e seu tamanho (crictl só em sabdiia03)  [executado 2026-09-29]
crictl --runtime-endpoint unix:///run/containerd/containerd.sock images

# o mesmo sem crictl, direto no containerd (namespace k8s.io)         [executado 2026-09-29]
ctr -n k8s.io images ls

# baixar uma imagem direto no containerd, fora do kubelet (ALTERA o nó: +~30 G em /)  [executado 2026-10-29, sabdiia02: 6 min 30 s]
# quando o pull do kubelet cai com "failed to extract layer ... context canceled" (AC-24)
ctr -n k8s.io images pull docker.io/vllm/vllm-openai:v0.19.1

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
  # [acrescentado 2026-10-27, executado 2026-10-27 em sabdiia01] o disco de verdade, mesmo com link simbólico ou bind mount
  R=$(containerd config dump | awk -F'"' '/^root *=/{print $2}'); R=${R:-/var/lib/containerd}
  echo "### root aponta para";                  readlink -f "$R"
  echo "### em que disco está";                 findmnt -T "$R" -o TARGET,SOURCE,FSTYPE; df -h "$R"
  echo "### disco das imagens visto pelo kubelet"; kubectl get --raw "/api/v1/nodes/$(hostname -s)/proxy/stats/summary" | grep -A4 '"imageFs"'
} 2>&1 | tee containerd-config-$(hostname -s)-$(date +%F-%H%M).log
```

O que cada linha responde: `root` = onde ficam imagens, camadas e metadados; `state` = estado volátil
(`/run/containerd`); `imports` = outros arquivos que entram na configuração; `root_path` = se o
diretório das camadas desempacotadas (`overlayfs`) foi separado do `root`.

**Para mudar o local** (não é leitura: para o containerd do nó): procedimento completo, com reversão, em
[runbooks/mover-containerd-para-home.md](runbooks/mover-containerd-para-home.md). `[não executado]`

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

### Pausar e restaurar `vllms` (só com o acordo do administrador)

Servidor, bash, 01 ou 02. **ALTERA o *cluster***: tira do ar a produção e o Ray do administrador. O
procedimento completo, com cópia de segurança e restauração, está em
[runbooks/pausar-vllms.md](runbooks/pausar-vllms.md).

```bash
# Deployment/StatefulSet a 0 réplicas (volta com --replicas=<n antigo>)          [não executado]
kubectl scale -n vllms deployment/vllm-server --replicas=0

# DaemonSet sem pods: nodeSelector que nenhum nó tem (volta removendo a chave)   [não executado]
kubectl patch -n vllms daemonset/<nome> -p '{"spec":{"template":{"spec":{"nodeSelector":{"vllm-estudo/pausado":"true"}}}}}'
kubectl patch -n vllms daemonset/<nome> --type=json -p '[{"op":"remove","path":"/spec/template/spec/nodeSelector/vllm-estudo~1pausado"}]'

# quem é o dono de cada pod (Deployment via ReplicaSet, DaemonSet, ou nenhum)   [não executado]
kubectl get pods -n vllms -o custom-columns='POD:.metadata.name,DONO:.metadata.ownerReferences[0].kind'
```

## 4. Por que um *pod* não sobe

```bash
# log da ÚLTIMA execução que caiu (a causa costuma estar aqui)        [executado 2026-09-29]
kubectl logs -n vllms deploy/vllm-llama31-8b --previous --tail=300

# estado do contêiner, código de saída e eventos                      [executado 2026-09-29]
kubectl describe pod -n vllms -l app=vllm-llama31-8b | sed -n '/^Containers:/,$p'

# log da execução atual                                               [não executado nesta forma]
kubectl logs -n vllms deploy/vllm-deepseek-33b --tail=80

# log da queda anterior de CADA pod com o mesmo prefixo (deploy/ pega só um) [executado 2026-10-28]
for p in $(kubectl get pods -n vllms -o name | grep ray-worker); do echo "### $p"; kubectl logs -n vllms "$p" --previous --tail=40 2>&1; done

# quantas GPUs cada pod pede (vazio = não pede; o Kubernetes não sabe que usa GPU) [executado 2026-10-28]
kubectl get pods -n vllms -o custom-columns='POD:.metadata.name,NO:.spec.nodeName,GPU:.spec.containers[*].resources.limits.nvidia\.com/gpu'

# GPUs reservadas por nó, segundo o Kubernetes                        [executado 2026-10-28]
kubectl describe nodes | grep -E '^Name:|nvidia.com/gpu'
```

Lição do caso: leia `--previous` antes de culpar a GPU ou a versão
([AC-07](ESTUDO-DE-CASO.md#ac-07)).

## 5. A API do vLLM

Servidor, bash. `192.168.50.160:8001` era o `Service` do deepseek (sem autenticação,
[AC-06](ESTUDO-DE-CASO.md#ac-06)). **Desde 2026-10-29, `192.168.50.160` é o `Service` `ray-head`
(6379/8265/10001) e a `:8001` não responde.** A `:8265` é o painel do Ray: `/v1/models` lá dá `404`.

```bash
# a porta é o painel do Ray ou a API do vLLM? (8265 responde /api/..., nunca /v1/models)   [executado 2026-10-29]
curl -s -m 10 -w '\n[HTTP %{http_code}]\n' http://192.168.50.160:8265/api/version
curl -s -m 10 -w '\n[HTTP %{http_code}]\n' http://192.168.50.160:8265/api/serve/applications/   # "applications": {} = nada publicado pelo Ray Serve

# o Service tem pod por trás? (<none> = seletor não casa com nenhum pod)   [executado 2026-10-29]
kubectl get endpoints -n vllms

# o pod recebe a GPU? pod mínimo com nvidia.com/gpu: 1 em cada nó   [não executado; Bloco B de runbooks/ray-3-nos-gpu.md]

# testar um modelo em 1 GPU no protocolo comum: sobe, mede, guarda os logs e apaga o pod   [não executado; runbooks/plano-onda-1.md]
cd /home/utec/vllm-estudo && bash teste-1gpu.sh P-01 Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8 2>&1 | tee P-01-$(hostname -s)-$(date +%F-%H%M).log

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

# preempções acumuladas (falta de KV cache); compare antes e depois   [não executado]
# da carga. Nome da métrica conferido no código da v0.19.1 (vllm/v1/metrics/loggers.py)
curl -s --max-time 10 http://127.0.0.1:8000/metrics | grep '^vllm:num_preemptions_total'
```

Rede entre nós: o MTU deixa passar pacote grande? Servidor, bash, em cada nó. `-M do` proíbe
fragmentar; 1472 *bytes* de dados = MTU 1500, 8972 = MTU 9000. `[não executado]`

```bash
for ip in 192.168.50.150 192.168.50.151 192.168.50.152; do
  for s in 1472 8972; do ping -c 2 -W 1 -M do -s $s $ip >/dev/null 2>&1 && echo "$ip $s passa" || echo "$ip $s FALHA"; done
done
```

Teste de um modelo no protocolo comum (512 → 256, `temperature 0`, c=1/16/32), com as linhas do
registro já montadas: [runbooks/teste-protocolo-modelos.md](runbooks/teste-protocolo-modelos.md).

Estação Windows, PowerShell (o `curl` do PowerShell complica as aspas do JSON):  `[não executado]`

```powershell
$corpo = @{ model = "TheBloke/deepseek-coder-33B-instruct-GPTQ"; messages = @(@{ role = "user"; content = "Olá" }); max_tokens = 50; temperature = 0 } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "http://192.168.50.160:8001/v1/chat/completions" -Method Post -ContentType "application/json" -Body $corpo
```

### O que o `vllm-server` do administrador roda? (só leitura)

Servidor, bash, `sabdiia01` ou `sabdiia02`. Chave e *tokens* mascarados. A seção 2 usa `|` como separador:
um texto com espaço dentro do *jsonpath* chegou partido ao servidor em 2026-11-07 (§9 do estudo).

```bash
# modelo, flags, volumes, exposição e quem aplica o manifesto        [executado 2026-11-07, seções 1, 3, 4, 5]
kubectl get deploy vllm-server -n vllms -o jsonpath='{.spec.replicas}{"\n"}{.spec.template.spec.containers[0].args}{"\n"}' | sed -E 's/(--api-key[= "]+)[^ ",]+/\1***/g'
kubectl get deploy vllm-server -n vllms -o jsonpath='{range .spec.template.spec.containers[0].env[*]}{.name}={.value}|{.valueFrom.secretKeyRef.name}{"\n"}{end}' | sed -E 's/^([A-Z_]*(TOKEN|KEY|SECRET|PASS)[A-Z_]*=)[^|]+/\1***/'   # [não executado]
kubectl get deploy vllm-server -n vllms -o jsonpath='{range .spec.template.spec.volumes[*]}{.name}={.persistentVolumeClaim.claimName}{"\n"}{end}'
kubectl get svc,ingress,networkpolicy -n vllms -o wide
kubectl get deploy vllm-server -n vllms -o jsonpath='{range .metadata.managedFields[*]}{.manager} {.operation} {.time}{"\n"}{end}'
```

### Acesso das aplicações pelo Kong (D-05)

O `scp` do notebook para `/home/utec/vllm-estudo/` dá `Permission denied`? Em 01, depois de `sudo -i`, rode o
bloco de permissão do E0 em [runbooks/acesso-aplicacoes-d05.md](runbooks/acesso-aplicacoes-d05.md) (ACL só
para o seu usuário: `setfacl -m "u:$SUDO_USER:rwx" /home/utec/vllm-estudo`). `[executado 2026-11-07]`

Desde 2026-11-06 no *namespace* `vllms` (D-06), recursos com o rótulo `decisao=d-05`. Procedimento completo, com chaves e log: [runbooks/acesso-aplicacoes-d05.md](runbooks/acesso-aplicacoes-d05.md).
Na `v0.19.1`, o `--api-key` só protege `/v1`: `/invocations` gera texto sem chave ([AC-32](ESTUDO-DE-CASO.md#ac-32)).

Servidor, bash, `sabdiia01` ou `sabdiia02`:

```bash
# o proxy do Kong: IP do MetalLB, externalTrafficPolicy e portas        [não executado]
kubectl get svc -n kong -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.name}{"  IP="}{.status.loadBalancer.ingress[0].ip}{"  externalTrafficPolicy="}{.spec.externalTrafficPolicy}{"  portas="}{.spec.ports[*].port}{"\n"}{end}'

# rotas que já passam pelo Kong e plugins globais                      [não executado]
kubectl get ingress -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"  caminhos="}{.spec.rules[*].http.paths[*].path}{"\n"}{end}'
kubectl get kongclusterplugins

# as 3 réplicas, uma por nó                                          [não executado]
kubectl get pods -n vllms -l app=vllm-server -o wide

# consumidores (um por ator) e IPs liberados na rota                    [não executado]
kubectl get kongconsumer -n vllms -l decisao=d-05
kubectl get kongplugin d05-ip-restriction -n vllms -o jsonpath='{.config.allow}{"
"}'

# trocar a chave de um ator (ex.: dev-1): apaga o Secret dele e roda o Bloco C, que cria outra   [não executado]
# (ALTERA: a chave antiga para de valer na hora; entregue o novo d05-chave-dev-1.env)
kubectl delete secret kong-cred-dev-1 -n vllms

# o controlador do Kong aceitou a rota e os plugins? (procure TranslationFailed / ApplyFailed)   [não executado]
kubectl get events -n vllms --sort-by=.lastTimestamp | tail -15

# chamada pelo Kong com os cabeçalhos num arquivo (a chave não vai para a linha de comando nem para o log)   [não executado]
# usa a chave do consumidor "estacao" (arquivo do Bloco C) e o d05-corpo.json dos Blocos G1/C; o arquivo de cabeçalhos é apagado no fim
cd /home/utec/vllm-estudo && ( umask 077; . ./d05-chave-estacao.env; printf 'apikey: %s\nAuthorization: Bearer %s\n' "$CHAVE_KONG" "$CHAVE_VLLM" > d05-h.txt
  curl -sk -X POST -H @d05-h.txt -H 'Content-Type: application/json' --data-binary @d05-corpo.json "$BASE_URL/chat/completions"; echo; rm -f d05-h.txt )
```

Estação, PowerShell (o IP é o da seção 2 do Bloco K0):

```powershell
# a estação alcança a porta 443 do Kong? (mostra também o IP de origem)   [não executado]
$ip = Read-Host "IP do proxy do Kong"
Test-NetConnection $ip -Port 443 | Select-Object ComputerName, RemotePort, SourceAddress, TcpTestSucceeded
```

O teste do SSE pelo Kong (primeiro *byte* contra total, `curl.exe -N -w "%{time_starttransfer} %{time_total}"`)
está na seção 2 do Bloco E1 do runbook, que monta os arquivos de cabeçalho.

### Chamar o vLLM pelo Kong a partir do notebook (consumidor `wsantos`)

Estação (notebook), PowerShell 7. Traz o arquivo de chave (fica fora do repositório) e faz uma pergunta.
`-SkipCertificateCheck`: o Kong usa certificado autoassinado (PD-34). `[não executado]`

```powershell
$d = "$env:USERPROFILE\.vllm-estudo"; New-Item -ItemType Directory -Force $d | Out-Null
scp "utec@192.168.50.151:/home/utec/vllm-estudo/d05-chave-wsantos.env" "$d\"
$c = Get-Content "$d\d05-chave-wsantos.env" -Raw | ConvertFrom-StringData
$h = @{ apikey = $c.CHAVE_KONG; Authorization = "Bearer $($c.CHAVE_VLLM)" }
$m = @(@{ role = "user"; content = "Qual é a capital do Brasil?" })
$b = @{ model = $c.MODELO; messages = $m; max_tokens = 100; temperature = 0 } |
  ConvertTo-Json -Depth 5
$r = Invoke-RestMethod "$($c.BASE_URL)/chat/completions" -Method Post -Headers $h `
  -ContentType "application/json; charset=utf-8" -Body $b -SkipCertificateCheck
$r.choices[0].message.content
```

Python, com o pacote `openai` (`pip install openai`); o mesmo arquivo de chave. `verify=False` só para teste. `[não executado]`

```python
import os, httpx
from openai import OpenAI
c = dict(l.strip().split("=", 1) for l in open(os.path.expanduser(
    "~/.vllm-estudo/d05-chave-wsantos.env")) if "=" in l)
cli = OpenAI(base_url=c["BASE_URL"], api_key=c["CHAVE_VLLM"],
             default_headers={"apikey": c["CHAVE_KONG"]},
             http_client=httpx.Client(verify=False))
r = cli.chat.completions.create(model=c["MODELO"], max_tokens=100, temperature=0,
    messages=[{"role": "user", "content": "Qual é a capital do Brasil?"}])
print(r.choices[0].message.content)
```

### Que certificado o Kong apresenta, e o Node.js aceita? (PD-34)

Estação (notebook), Git Bash, em `C:\www\vllm-app` (com `.env` e `server.js`). Sem `subjectAltName` com o IP, o
Node recusa mesmo confiando no certificado. `[executado: 2026-11-09]`, com o script anterior (`run-vllm.js`,
`generateText`, erro em `Last error:`) ([log](logs-analysis/kong-tls-node-wsantosdell-2026-11-09-0941.log)). O
`server.js` usa `streamText` e escreve o erro como `Erro:`; com ele, o bloco abaixo foi executado em 2026-11-09 e deu o
mesmo `Hostname/IP does not match certificate's altnames` (saída vista no terminal, sem log).

```bash
cd /c/www/vllm-app
echo | openssl s_client -connect 192.168.50.161:443 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
echo | openssl s_client -connect 192.168.50.161:443 2>/dev/null | openssl x509 > kong.pem
NODE_EXTRA_CA_CERTS=kong.pem node server.js "teste" 2>&1 | grep -m1 -E "^Erro:"
```

### O Nemo mistura inglês na resposta? (system prompt × temperatura)

Estação (notebook), Git Bash, em `C:\www\vllm-app` (script `test/teste-idioma.js`, com o `.env` do consumidor
`wsantos`). Rode da raiz da aplicação, não de dentro de `test/`: o script lê o `.env` e o `node_modules` da pasta atual.
"Quem é Demis Hassabis?" 10 vezes em 4 configurações (A sem nada, B `temperature 0.3`, C `system` + 0.3, D só
`system`), em sequência; grava `logs-analysis/idioma-nemo-<host>-<data>.log`. 40 chamadas em ~5 min.
`[executado: 2026-11-09]` ([log](logs-analysis/idioma-nemo-wsantosdell-2026-11-09-1129.log), AC-34)

```bash
cd /c/www/vllm-app
NODE_TLS_REJECT_UNAUTHORIZED=0 node test/teste-idioma.js
```

### O Nemo resiste a *prompt injection*? (PD-37)

Estação (notebook), Git Bash, em `C:\www\vllm-app` (script `test/teste-injecao.js`, `.env` do `wsantos`), da raiz da
aplicação. Empresa fictícia com 2 documentos; 22 casos (diretos, vazamento do identificador, fora dos documentos,
indiretos num documento, controle) × N=3 em 4 configurações (A sem regras, B regras no `system`, C documentos
delimitados, D 2ª mensagem de sistema como a do `ai-prompt-decorator`); `temperature 0.3`, até 300 *tokens*. Grava
`logs-analysis/injecao-nemo-<host>-<data>.log`. 264 chamadas, ~7 min (2026-11-09). `N=1` faz uma rodada curta;
`SO=C` roda só uma configuração. `[executado: 2026-11-09]` ([log](logs-analysis/injecao-nemo-wsantosdell-2026-11-09-1505.log), AC-35)

```bash
cd /c/www/vllm-app
NODE_TLS_REJECT_UNAUTHORIZED=0 node test/teste-injecao.js
```

### O `ai-prompt-guard` do Kong barraria os ataques? (PD-37)

Estação (notebook), Git Bash, em `C:\www\vllm-app`. Sem rede e sem `.env`: aplica as expressões do *plugin* às
mensagens do teste de injeção (`test/injecao-casos.js`) e tira as respostas do log mais recente dele (ou de `LOG=<arquivo>`).
Grava `logs-analysis/guard-sim-<host>-<data>.log`. `[executado: 2026-11-09]` ([log](logs-analysis/guard-sim-wsantosdell-2026-11-09-1809.log), AC-36)

```bash
cd /c/www/vllm-app
node test/simula-prompt-guard.js
```

### Os *plugins* de IA do Kong funcionam na rota? (Bloco H, PD-37)

Estação (notebook), Git Bash, em `C:\www\vllm-app`, depois do Bloco H de
[runbooks/acesso-aplicacoes-d05.md](runbooks/acesso-aplicacoes-d05.md). `test/teste-kong-ia.js` chama a rota direto
(`fetch`) em 7 casos: pergunta normal (200), ataque grosseiro (400 do `ai-prompt-guard`), mensagem de sistema do Kong
na resposta, *streaming*, corpo de ~19 KB (acima dos 8 KiB padrão), conversa com ferramenta (assistente com `content`
nulo) e mensagem do usuário em partes (400, limite do *guard*). Grava `logs-analysis/kong-ia-<host>-<data>.log`. A 2ª
linha repete a configuração C do AC-35 pela rota com os *plugins*; o 400 do Kong conta como "bloqueado".
`[executado: 2026-11-09]` com os *plugins* ([log](logs-analysis/kong-ia-wsantosdell-2026-11-09-1833.log): *streaming* quebrado, AC-37) e sem eles ([log](logs-analysis/kong-ia-wsantosdell-2026-11-09-1846.log))

```bash
cd /c/www/vllm-app
NODE_TLS_REJECT_UNAUTHORIZED=0 node test/teste-kong-ia.js
NODE_TLS_REJECT_UNAUTHORIZED=0 SO=C ROTA="Bloco H: decorator + guard G1" node test/teste-injecao.js
```

### Que *plugins* o Kong instalado tem? (PD-37)

Servidor `sabdiia01`, bash com `kubectl`. Confere a edição do Kong e se os *plugins* de IA de [F-049] estão no
*gateway* em uso: os arquivos dos *plugins* no contêiner, a pasta `enterprise_edition` (só existe na edição paga) e
`KONG_PLUGINS` (que *plugins* o Kong carrega; ausente = `bundled`, todos os embutidos). Só lê, não muda nada.
`[executado: 2026-11-09]` ([log](logs-analysis/kong-plugins-sabdiia01-2026-11-09-1803.log): `3.9.4` de código aberto, *plugins* `ai-*` presentes, `KONG_DATABASE=off`). 1ª versão, com `curl` na API de administração, `[executado: 2026-11-09]`
([log](logs-analysis/kong-plugins-sabdiia01-2026-11-09-1800.log)): contêiner `proxy`, imagem `kong:3.9`,
`kong version` = `3.9.4`; a imagem não tem `curl` (`sh: 1: curl: not found`).

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ P=$(kubectl get pod -n kong -o name | grep gateway | head -1); echo "pod: $P"
  kubectl exec -n kong $P -c proxy -- kong version
  echo "--- env do contêiner proxy (KONG_PLUGINS, KONG_DATABASE)"
  kubectl get $P -n kong \
    -o jsonpath='{range .spec.containers[?(@.name=="proxy")].env[*]}{.name}={.value}{"\n"}{end}' \
    | grep -E '^KONG_(PLUGINS|DATABASE)=' || echo "nenhuma das duas definida"
  echo "--- arquivos dos plugins no contêiner"
  kubectl exec -n kong $P -c proxy -- sh -c \
    'D=$(find / -type d -path "*/kong/plugins" 2>/dev/null | head -1); echo "pasta: $D";
     ls -d "$(dirname $D)/enterprise_edition" 2>/dev/null || echo "sem enterprise_edition";
     ls "$D" | grep -E "^(ai-|request-size|pre-function)"'
} 2>&1 | tee kong-plugins-$(hostname -s)-$(date +%F-%H%M).log
```

### Que observabilidade o *cluster* já tem? (PD-38)

Servidor `sabdiia01` (ou `sabdiia02`; o `kubectl` falha em 03), bash com `kubectl`. Só lê, não muda nada. Confere o que
está de pé em `monitoring` (kube-prometheus e Grafana, vistos em 2026-09-28 e 2026-10-27), o que o Prometheus escolhe
coletar (seletores de `ServiceMonitor`/`PodMonitor`), os *jobs* que ele coleta hoje e se a GPU (DCGM) está entre eles,
a porta de status do Kong e se ela já serve `/metrics`, e as `NetworkPolicy` de `vllms` e `monitoring`. As consultas ao
Prometheus e ao Kong passam pelo *proxy* da API do Kubernetes (`kubectl get --raw`), porque as imagens não têm `curl`.
`[executado: 2026-11-10]` ([log](logs-analysis/observabilidade-sabdiia01-2026-11-10-1537.log)): tudo `Running`, Grafana em `LoadBalancer` `192.168.50.162:80`, sem PVC em `monitoring`; **nenhum *job* de GPU, Kong ou vLLM** no Prometheus; a porta 8100 do Kong já serve `/metrics`. A etapa 4 saiu vazia (o `grep` procurava o recuo de um objeto, mas a saída é uma lista); está refeita na 2ª parte, abaixo.

O que espero ver `[hipótese]`: Prometheus, Alertmanager e Grafana `Running`; `ServiceMonitor` do `dcgm-exporter` e
*job* dele em `up`; nenhum *job* do vLLM (a `NetworkPolicy` `vllm-server-so-kong` só deixa entrar o `kong`); porta de
status do Kong sem `/metrics` (404), porque não há *plugin* `prometheus`; seletor de `ServiceMonitor` exigindo o
rótulo `release: monitoring` (padrão do *chart* kube-prometheus-stack).

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  PD-38: inventário de observabilidade (só leitura)"
  echo "--- 1. monitoring: pods, serviços, ingress, discos"
  kubectl get pods,svc,ingress,pvc -n monitoring -o wide
  echo "--- 2. releases helm"
  helm list -A 2>&1 | grep -Ei '^NAME|monitor|prometheus|grafana|kong|gpu' || true
  echo "--- 3. CRDs do Prometheus Operator e objetos de coleta"
  kubectl get crd | grep monitoring.coreos.com
  kubectl get servicemonitors,podmonitors -A
  echo "--- 4. Prometheus: seletores, retenção, disco"
  kubectl get prometheus -n monitoring -o yaml \
    | grep -E -A3 '^  (serviceMonitor|podMonitor)(Namespace)?Selector:|^  retention|^  storage:'
  echo "--- 5. o que o Prometheus coleta hoje (jobs em up) e se vê a GPU"
  S=$(kubectl get svc -n monitoring -o name | grep -- '-prometheus$' | head -1 | cut -d/ -f2)
  echo "svc: $S"
  B="/api/v1/namespaces/monitoring/services/$S:9090/proxy/api/v1/query?query="
  kubectl get --raw "${B}count%20by%20(job)%20(up)" | tr '{' '\n' | grep job
  kubectl get --raw "${B}count(DCGM_FI_DEV_GPU_UTIL)" | tr '{' '\n' | grep value
  echo "--- 6. dcgm-exporter"
  kubectl get pods,svc -n gpu-operator -o wide | grep -Ei '^NAME|dcgm'
  echo "--- 7. Kong: serviços, portas do proxy, status/tracing, plugins globais"
  kubectl get svc -n kong
  P=$(kubectl get pod -n kong -o name | grep gateway | head -1); echo "pod: $P"
  kubectl get $P -n kong -o \
    jsonpath='{range .spec.containers[?(@.name=="proxy")].ports[*]}{.name}={.containerPort} {end}'
  echo
  kubectl get $P -n kong \
    -o jsonpath='{range .spec.containers[?(@.name=="proxy")].env[*]}{.name}={.value}{"\n"}{end}' \
    | grep -E 'STATUS_LISTEN|TRACING' || echo "sem KONG_STATUS_LISTEN nem KONG_TRACING_*"
  kubectl get kongclusterplugins -A 2>&1
  SP=$(kubectl get $P -n kong -o \
    jsonpath='{.spec.containers[?(@.name=="proxy")].ports[?(@.name=="status")].containerPort}')
  echo "porta de status: ${SP:-nenhuma}"
  [ -n "$SP" ] && kubectl get --raw \
    "/api/v1/namespaces/kong/pods/${P#pod/}:$SP/proxy/metrics" 2>&1 | head -5
  echo "--- 8. NetworkPolicy e serviços do vLLM"
  kubectl get networkpolicy -n vllms; kubectl get networkpolicy -n monitoring
  kubectl get svc -n vllms --show-labels
} 2>&1 | tee observabilidade-$(hostname -s)-$(date +%F-%H%M).log
```

### Por que o Prometheus não coleta a GPU? (PD-38, 2ª parte)

Servidor `sabdiia01`, bash com `kubectl`. Só lê. O 1º inventário ([log](logs-analysis/observabilidade-sabdiia01-2026-11-10-1537.log)) mostrou dois
`ServiceMonitor` de GPU (`default/dcgm-exporter-1793243508`, de 12 dias, e `gpu-operator/gpu-operator`) e nenhum *job*
de DCGM no Prometheus. Este confere os seletores do Prometheus, os rótulos dos dois `ServiceMonitor` e do `Service` do
DCGM, os *jobs* da configuração gerada, os alvos com erro, se o *exporter* responde, os discos do Prometheus e do
Grafana e os nomes das métricas que a porta de status do Kong já serve. `[executado: 2026-11-10]` ([log](logs-analysis/observabilidade2-sabdiia01-2026-11-10-1544.log): hipóteses confirmadas, AC-38; o Kong serve 8 métricas do nó)

O que espero ver `[hipótese]`: `serviceMonitorSelector` exigindo `release: monitoring`, rótulo que os dois
`ServiceMonitor` de GPU não têm; nenhum *job* de DCGM na configuração; o *exporter* respondendo `DCGM_FI_DEV_*`;
Prometheus e Grafana em `emptyDir` (não há PVC em `monitoring`); no Kong, só métricas do nó, sem `kong_http_requests`.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{ echo "== $(hostname -s)  $(date -Is)  PD-38 (2): coleta da GPU e discos (só leitura)"
  echo "--- 1. Prometheus: seletores, retenção, disco"
  PR=$(kubectl get prometheus -n monitoring -o name | head -1); echo "$PR"
  kubectl get $PR -n monitoring -o yaml | grep -E -A4 \
    '^  (serviceMonitor|podMonitor)(Namespace)?Selector|^  retention|^  storage'
  echo "--- 2. os dois ServiceMonitor de GPU"
  kubectl get servicemonitor -n default dcgm-exporter-1793243508 -o yaml
  kubectl get servicemonitor -n gpu-operator gpu-operator -o yaml
  echo "--- 3. Service do DCGM (rótulos e porta)"
  kubectl get svc -n gpu-operator nvidia-dcgm-exporter -o yaml | sed '/^status:/,$d'
  echo "--- 4. jobs na configuração gerada e alvos com erro"
  S=monitoring-kube-prometheus-prometheus
  B="/api/v1/namespaces/monitoring/services/$S:9090/proxy/api/v1"
  kubectl get --raw "$B/status/config" | tr '\\' '\n' | grep -o 'job_name: .*' | sort -u
  kubectl get --raw "$B/targets?state=active" | tr ',' '\n' \
    | grep -E '"(scrapePool|health)"' | paste - - | sort | uniq -c
  echo "--- 5. o exporter responde?"
  kubectl get --raw \
    "/api/v1/namespaces/gpu-operator/services/nvidia-dcgm-exporter:9400/proxy/metrics" \
    | grep -E '^DCGM_FI_DEV_(GPU_UTIL|SM_CLOCK|GPU_TEMP|POWER_USAGE)\{' | cut -c1-160
  echo "--- 6. volumes do Prometheus e do Grafana"
  J='{range .spec.template.spec.volumes[*]}{.name}: {.persistentVolumeClaim}{.emptyDir}{"\n"}{end}'
  for O in $(kubectl get statefulset -n monitoring -o name | grep prometheus); do
    echo "$O"; kubectl get $O -n monitoring -o jsonpath="$J"; done
  kubectl get deploy -n monitoring monitoring-grafana -o jsonpath="$J"
  echo "--- 7. métricas que a porta de status do Kong serve (só os nomes)"
  P=$(kubectl get pod -n kong -o name | grep gateway | head -1)
  kubectl get --raw "/api/v1/namespaces/kong/pods/${P#pod/}:8100/proxy/metrics" \
    | grep '^# TYPE' | cut -d' ' -f3 | sort -u
  echo "--- 8. NetworkPolicy no cluster inteiro"
  kubectl get networkpolicy -A
} 2>&1 | tee observabilidade2-$(hostname -s)-$(date +%F-%H%M).log
```

### Ligar GPU, vLLM e Kong ao Prometheus do *cluster* (PD-38)

Servidor `sabdiia01`, bash. Blocos O1 (GPU e vLLM), O2 (Kong) e O-desfazer em [runbooks/observabilidade-d05.md](runbooks/observabilidade-d05.md). Comandos novos: `kubectl apply` de `ServiceMonitor`/`PodMonitor` com `release: monitoring` (AC-38); alvos do Prometheus por `kubectl get --raw .../api/v1/targets?state=active`; nomes de métricas por `.../api/v1/label/__name__/values`. O1 `[executado: 2026-11-10]` ([log](logs-analysis/d05-o1-sabdiia01-2026-11-10-1559.log): GPU sim, vLLM não); O1-diag e O1-limpeza `[executado: 2026-11-10]` (*job* do vLLM criado, conferência cedo demais; `dcgm-exporter` de `default` removido); O1-confere `[executado: 2026-11-10]` ([log](logs-analysis/d05-o1-confere-sabdiia01-2026-11-10-1630.log): vLLM com 3 alvos `up`, AC-39); O2 `[executado: 2026-11-10]` ([log](logs-analysis/d05-o2-sabdiia01-2026-11-10-1634.log): Kong `up`, métricas por requisição); *streaming* OK depois do O2 ([teste](logs-analysis/kong-ia-wsantosdell-2026-11-10-1639.log), AC-40). Disco local do Prometheus: P0 (pasta em 03, `chown 1000:2000`, `chcon -t container_file_t`) e P1 (PV `local` e `helm upgrade monitoring kube-prometheus-stack --version 91.3.0 --reuse-values -f ...`) `[executado: 2026-11-10]`: P0 OK, P1 falhou por conflito com o Freelens ([log](logs-analysis/d05-p1-sabdiia01-2026-11-10-1701.log)). P1-diag (`kubectl diff -f` do `helm get manifest --revision 1`, `--show-managed-fields`, `helm pull --untar`) `[executado: 2026-11-10]` ([log](logs-analysis/d05-p1-diag-sabdiia01-2026-11-10-1707.log), AC-41); P1b `[executado: 2026-11-10]` ([log](logs-analysis/d05-p1b-sabdiia01-2026-11-10-1713.log): revisão 3, disco local em uso).

### Ver o Kong Manager (painel do administrador; só leitura)

O painel (`kong-gateway-manager`, *NodePort* 32492/32616) abre, mas vem sem dados: o `kconfig.js` dele tem
`ADMIN_API_URL` vazio e `ADMIN_API_SSL_PORT` `8444`, e a Admin API (`kong-gateway-admin`, `ClusterIP` *headless*
8444) não sai do *cluster* (2026-11-09: `192.168.50.151:8444` e `.161:8444` sem resposta do notebook).
Túnel sem mudar nada no Kong. **Não edite pelo painel:** o Kong é do administrador, e o
*ingress controller* reescreve o que vem dos `KongConsumer`/`KongPlugin`. `[não executado]`

Servidor `sabdiia01`, bash (deixe aberto):

```bash
kubectl port-forward -n kong svc/kong-gateway-admin 8444:8444
```

Estação (notebook), PowerShell, em outra janela (deixe aberta):

```powershell
ssh -N -L 8444:127.0.0.1:8444 -L 8445:192.168.50.151:32616 utec@192.168.50.151
```

No navegador, abra `https://localhost:8444` uma vez e aceite o certificado (autoassinado); depois abra
`https://localhost:8445`.

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

Para o vLLM instalado num *venv* no *host* (o projeto Ray do administrador), veja a seção 7b.

A *tag* da imagem (caso 3) é só um rótulo; como evidência vale o que o vLLM em execução responde
(caso 1). Estado em 2026-10-02:

| Nó | Imagem no disco | Rodando |
|---|---|---|
| `sabdiia01` | `v0.19.1` (a `v0.12.0` foi removida às 12:53) | **sim**, *pods* de teste em `vllm-estudo` (AC-13) |
| `sabdiia02` | nenhuma registrada (a `v0.6.4` saiu do registro, as camadas ficaram, AC-09) | não |
| `sabdiia03` | `v0.6.4` | **sim**, o deepseek |

### Teste de qualidade (*tool calling* + resposta, sem o banco)

Procedimento completo: [runbooks/teste-qualidade-modelos.md](runbooks/teste-qualidade-modelos.md).
Os arquivos ficam em [`qualidade/`](qualidade/).

```powershell
# com que métodos o servidor aceita login, e se a minha chave é aceita (estação; não pede senha)  [executado 2026-11-04]
ssh -v -o BatchMode=yes root@192.168.50.151 exit 2>&1 | Select-String "Authentications that can continue|Offering|Permission denied"

# copiar com o seu usuário, não root (root recusa a senha por ssh)  [não executado]
$u = Read-Host "Usuário com que você entra no sabdiia01"
scp C:\www\vllm-master\qualidade\qualidade.sh "${u}@192.168.50.151:/tmp/qualidade-copia/"
```

```bash
# o servidor subiu com tool calling? (procure --enable-auto-tool-choice --tool-call-parser hermes) [não executado]
kubectl exec -n vllm-estudo vllm-qual -- sh -c 'for p in /proc/[0-9]*/cmdline; do tr "\0" " " < $p 2>/dev/null | grep -E "vllm serve"; done | sort -u'

# um candidato inteiro: sobe, coleta 50 perguntas, pontua e apaga (servidor sabdiia01)  [não executado]
cd /home/utec/vllm-estudo && bash qualidade/qualidade.sh 7b 2>&1 | tee qualidade-7b-$(hostname -s)-$(date +%F-%H%M).log

# variantes da ferramenta no mesmo servidor: lista fechada de indicadores (enum), com e sem tool_choice "required" [executado 2026-11-06]
cd /home/utec/vllm-estudo && bash qualidade/qualidade.sh nemo "enum enum-required" 2>&1 | tee qualidade-nemo-enum-$(hostname -s)-$(date +%F-%H%M).log

# carga com as perguntas da aplicação (enum-required), 1/8/16/32 usuários, numa GPU (Rodada 3 do runbook) [executado 2026-11-06]
cd /home/utec/vllm-estudo && bash qualidade/qualidade.sh nemo carga 2>&1 | tee qualidade-nemo-carga-$(hostname -s)-$(date +%F-%H%M).log

# Mistral-Nemo: formato Mistral fixado e servido pelo caminho local (runbooks/teste-mistral-nemo.md) [executado 2026-11-05]
cd /home/utec/vllm-estudo && bash qualidade/qualidade.sh nemo 2>&1 | tee qualidade-nemo-$(hostname -s)-$(date +%F-%H%M).log
```

```bash
# servir um modelo Mistral sem depender da rede: caminho local + nome do repo na API (v0.19.1)  [executado 2026-11-05]
# com HF_HUB_OFFLINE=1 e o nome do repo, o "auto" não lista o repositório e cai no formato HF
vllm serve "$P" --served-model-name mistralai/Mistral-Nemo-Instruct-2407 --tokenizer_mode mistral --config_format mistral --load_format mistral --enable-auto-tool-choice --tool-call-parser mistral
```

```powershell
# gerar o gabarito a partir do CSV (estação)                        [executado 2026-11-05]
python C:\www\vllm-master\qualidade\montar-gabarito.py

# coletor e pontuador na estação: -X utf8, senão o Windows grava o JSONL em cp1252  [executado 2026-11-05]
python -X utf8 C:\www\vllm-master\qualidade\coletar-respostas.py C:\www\vllm-master\qualidade\gabarito-qualidade.json --url http://127.0.0.1:18766 --variante enum > respostas.jsonl

# repontuar uma coleta, ou comparar duas (controle Ray x 1 GPU), sem GPU (estação) [executado 2026-11-04, com coletas simuladas]
python C:\www\vllm-master\qualidade\pontuar-respostas.py C:\www\vllm-master\qualidade\gabarito-qualidade.json respostas.jsonl
python C:\www\vllm-master\qualidade\pontuar-respostas.py C:\www\vllm-master\qualidade\gabarito-qualidade.json base.jsonl --comparar outra.jsonl
```

## 6. Hugging Face

Rodam **dentro** do *pod* do deepseek, que tem o `HF_TOKEN`. O segundo grava ~1 KB no PVC `hf-cache`.

```bash
# o token é válido? (imprime só o nome da conta)                      [executado 2026-09-29]
kubectl exec -n vllms deploy/vllm-deepseek-33b -- python3 -c "from huggingface_hub import whoami; print(whoami()['name'])"

# o token acessa um repositório gated?                                [executado 2026-09-29]
kubectl exec -n vllms deploy/vllm-deepseek-33b -- python3 -c "from huggingface_hub import hf_hub_download; print(hf_hub_download('meta-llama/Llama-3.1-8B-Instruct', 'config.json'))"
```

```bash
# que arquivos um repositório tem, com tamanho (estação, bash; sem token se não for gated)  [executado 2026-11-05]
# mostra repositório com os pesos em dois formatos (Mistral: consolidated + partes HF), que dobra o download
curl -sL "https://huggingface.co/api/models/mistralai/Mistral-Nemo-Instruct-2407/tree/main" | python -I -c "import json,sys;[print(f['path'],f.get('size')) for f in json.load(sys.stdin)]"
```

## 7. Armazenamento

```bash
# classes de armazenamento disponíveis                                [executado 2026-09-28]
kubectl get storageclass

# volumes persistentes, tamanho e a quem pertencem                    [executado 2026-09-28]
kubectl get pv
```

## 7a. Ray eliminado (D-07, 2026-11-07)

Procedimento completo, com cópia antes e logs: [runbooks/remover-ray.md](runbooks/remover-ray.md). As
seções 7b e 7c abaixo são histórico.

```bash
# servidor, bash (01 ou 02): sobrou algo do Ray no Kubernetes?           [não executado]
kubectl get pods -A -o wide | grep -iE '(^|[-_/ ])ray([-_:/ ]|$)|rayproject' || echo "nenhum pod com ray"

# servidor, bash (01 ou 02): os pods do ray-worker já saíram? quem segura cada GPU?   [não executado]
kubectl wait --for=delete pod -n vllms -l app=ray-worker --timeout=180s
kubectl get pods -n vllms -o jsonpath='{range .items[*]}{.metadata.name}|{.spec.nodeName}|{.status.phase}|{.status.containerStatuses[0].state.waiting.reason}|reinicios={.status.containerStatuses[0].restartCount}|gpu={.spec.containers[0].resources.limits.nvidia\.com/gpu}{"\n"}{end}'

# cada nó, bash como root: processo ou porta do Ray no host?            [não executado]
pgrep -af 'gcs_server|raylet|ray::|ray/dashboard|default_worker\.py|bin/ray ' || echo "nenhum processo do Ray"
ss -ltnp | grep -E ':(6379|8265|10001)\b' || echo "nenhuma porta do Ray"

# cada nó, bash como root: algo religa o Ray? (systemd e cron)          [não executado]
systemctl list-unit-files --no-pager --no-legend | awk 'tolower($1) ~ /ray/'
for U in $(ls /var/spool/cron/crontabs 2>/dev/null); do crontab -l -u "$U" | grep -nE 'ray|llm_lhama' | sed "s/^/$U: /"; done
```

## 7b. Ray fora do Kubernetes (projeto do administrador)

Servidor, bash, em cada nó. Só leitura. O projeto do administrador (`llm_lhama_prototype`) roda o Ray
**direto no *host***, num *venv* em `/home/utec/llm_lhama_prototype/venv`, como `root` (AC-19); os
contêineres Docker do projeto estão parados. **Não use `docker inspect` sem `-f`, nem `env`:** as
variáveis trazem `HF_TOKEN`.

```bash
# há motor de contêiner fora do Kubernetes?                           [executado 2026-10-27]
for c in docker podman nerdctl; do printf '%s: ' $c; command -v $c || echo ausente; done

# processos do Ray no host                                            [executado 2026-10-27]
ps -eo pid,user,etime,args | grep -E '[r]aylet|[g]cs_server|[r]ay start|[s]erve run' | cut -c1-220

# quem usa a GPU, inclusive fora do Kubernetes (PID do host)          [executado 2026-10-27]
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv

# contêineres e espaço do Docker                                      [executado 2026-10-27]
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker system df

# portas do Ray (6379, 8265), da API (8000), Streamlit (8501), http.server (8080) [executado 2026-10-27]
ss -ltnp | grep -E ':(6379|8265|8000|8501|8080)\b'

# RTT entre nós (custo de rede por passo de tensor/pipeline parallel, PD-31) [executado 2026-10-27]
ping -c 100 -i 0.2 -q 192.168.50.152

# quando Docker/Podman foram instalados (cruzar com a PD-28)          [não executado]
rpm -qa --qf '%{NAME} %{VERSION} %{INSTALLTIME:date}\n' | grep -iE 'docker|podman|moby|containerd'

# política da cadeia FORWARD (o Docker costuma pô-la em DROP)         [não executado]
iptables -S FORWARD | head -3

# versões do vLLM no venv, sem importar nada                                  [executado 2026-10-27]
/home/utec/llm_lhama_prototype/venv/bin/pip show vllm ray torch | grep -E '^(Name|Version):'

# se o pip falhar ("pip: command not found"): versão do vLLM sem depender do pip [não executado]
P=/home/utec/llm_lhama_prototype/venv
echo "== versão pelo nome da pasta de instalação (sem pip)"; ls -d "$P"/lib*/python3*/site-packages/vllm-*.dist-info 2>&1
echo "== versão pelo python do venv"; "$P/bin/python3" -m pip show vllm 2>&1 | grep -E '^(Name|Version):|rror'

# estado do cluster Ray e das aplicações Serve                        [executado 2026-10-27]
/home/utec/llm_lhama_prototype/venv/bin/ray status
/home/utec/llm_lhama_prototype/venv/bin/serve status

# configuração com que o vLLM subiu (paralelismo, modelo, dtype)      [executado 2026-10-27, vazio]
grep -rhoE 'Initializing an LLM engine.{0,600}' /tmp/ray/session_latest/logs 2>/dev/null | tail -2
```

## 7c. Ray dentro do Kubernetes (projeto do administrador, desde 2026-10-28)

Só leitura. `kubectl exec` roda um comando de consulta dentro do contêiner do administrador, sem alterá-lo.
Nunca use `-o yaml` nem `env` aqui: o manifesto pode trazer o *token* do Hugging Face. Mostre só os
**nomes** das variáveis, e passe a saída por `sed` para mascarar `hf_...`.

```bash
# comando, args, nomes das variáveis, volumes e recursos de cada Deployment do Ray [executado 2026-10-28]
kubectl get deploy -n vllms ray-head ray-worker-2 ray-worker-3 -o jsonpath='{range .items[*]}{"### "}{.metadata.name}{"\n command: "}{.spec.template.spec.containers[0].command}{"\n args: "}{.spec.template.spec.containers[0].args}{"\n env (só nomes): "}{.spec.template.spec.containers[0].env[*].name}{"\n mounts: "}{.spec.template.spec.containers[0].volumeMounts[*].mountPath}{"\n volumes: "}{.spec.template.spec.volumes}{"\n hostNetwork: "}{.spec.template.spec.hostNetwork}{"\n resources: "}{.spec.template.spec.containers[0].resources}{"\n"}{end}' | sed -E 's/hf_[A-Za-z0-9]{8,}/hf_***MASCARADO***/g'

# configuração com que o vLLM subiu, no log do pod (modelo, TP, PP, dtype) [executado 2026-10-28]
kubectl logs -n vllms deploy/ray-head --tail=3000 | grep -E 'Initializing an LLM engine|tensor_parallel|pipeline_parallel|Loading model weights took|GPU blocks|Uvicorn running|Error|ERROR' | cut -c1-600 | tail -30

# estado do cluster Ray e das aplicações Serve, de dentro do head      [executado 2026-10-28]
kubectl exec -n vllms deploy/ray-head -- ray status
kubectl exec -n vllms deploy/ray-head -- serve status

# a API do Ray (hostNetwork, porta 8000 no IP do nó) responde, e com que modelo [executado 2026-10-28: recusado]
curl -s -m 10 http://192.168.50.151:8000/v1/models

# copiar arquivos do tokenizer de dentro do head, só lendo (segue os links do cache HF) [não executado]
P=$(kubectl get pods -n vllms -l app=ray-head -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n vllms "$P" -- sh -c 'find /root/.cache/huggingface -path "*Meta-Llama-3.1-8B-Instruct*" -name tokenizer.json'

# curl "não retornou nada": mostrar o erro e o código de saída (7 = recusado, 28 = tempo esgotado) [executado 2026-10-28: recusado]
curl -v -m 10 http://192.168.50.151:8000/v1/models; echo "curl saiu com $?"

# alguém escuta na porta 8000 do nó? (hostNetwork: o pod usa a rede do host) [executado 2026-10-28: recusado]
ss -ltnp | grep -E ':8000 |:8265 |:6379 '

# o servidor da API ainda roda dentro do head?                       [executado 2026-10-28: recusado]
kubectl exec -n vllms deploy/ray-head -- sh -c 'ps -eo pid,etime,args | grep -E "api_server" | grep -v grep | cut -c1-200'

# onde o Ray/vLLM está agora: pods e deployments em qualquer namespace [não executado]
kubectl get pods,deploy -A -o wide 2>&1 | grep -iE 'NAMESPACE|ray|vllm'

# processos do Ray/vLLM no host, com a interface do NCCL/Gloo lida do ambiente do processo (só essas variáveis; root) [não executado]
for p in $(pgrep -f 'api_server|raylet|gcs_server|ray start'); do echo "## $p $(ps -o etime=,user= -p $p) $(tr '\0' ' ' < /proc/$p/cmdline | cut -c1-250)"; tr '\0' '\n' < /proc/$p/environ 2>/dev/null | grep -E '^(NCCL|GLOO)_'; done

# interface que o NCCL e o Gloo usam (só essas duas variáveis; nunca liste o env inteiro) [executado 2026-10-28: Deployments já removidos]
for d in ray-head ray-worker-2 ray-worker-3; do echo "$d: NCCL=$(kubectl get deploy -n vllms $d -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="NCCL_SOCKET_IFNAME")].value}') GLOO=$(kubectl get deploy -n vllms $d -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="GLOO_SOCKET_IFNAME")].value}')"; done

# rede de cada nó vista de dentro do pod do Ray (hostNetwork): interfaces, MTU, estado, IPv4 [não executado]
for d in ray-head ray-worker-2 ray-worker-3; do echo "## $d"; kubectl exec -n vllms deploy/$d -- sh -c 'for i in /sys/class/net/*; do n=$(basename $i); case $n in cali*|lo|docker0|tunl0) continue;; esac; echo "$n mtu=$(cat $i/mtu) $(cat $i/operstate)"; done; echo "IPv4: $(hostname -I)"'; done

# um worker alcança a porta do Ray no head? (sem ping nem nc na imagem) [não executado]
kubectl exec -n vllms deploy/ray-worker-2 -- timeout 3 bash -c '</dev/tcp/192.168.50.151/6379' && echo "02 -> 01:6379 ok"

# erros de NCCL, Gloo e Python nos logs da sessão do Ray, dentro do pod [não executado]
kubectl exec -n vllms deploy/ray-head -- sh -c 'grep -hE "NCCL WARN|NCCL INFO (NET|Bootstrap|Using network)|[Gg]loo|Traceback|Error|timed out|refused" /tmp/ray/session_latest/logs/*.err /tmp/ray/session_latest/logs/*.out 2>/dev/null | cut -c1-300 | tail -60'

# perguntar ao modelo do Ray (chat, resposta inteira, só o texto)    [não executado]
curl -s http://192.168.50.151:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"meta-llama/Meta-Llama-3.1-8B-Instruct","messages":[{"role":"user","content":"Explique em duas frases o que é Kubernetes."}],"max_tokens":200,"temperature":0}' | python3 -c 'import sys,json; r=json.load(sys.stdin); print(r["choices"][0]["message"]["content"]); print(r["usage"])'

# o mesmo em streaming (os pedaços chegam à medida que são gerados)  [não executado]
curl -sN http://192.168.50.151:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"meta-llama/Meta-Llama-3.1-8B-Instruct","messages":[{"role":"user","content":"Conte até dez."}],"max_tokens":100,"stream":true}'

# o servidor respeita ignore_eos? uma requisição de 256 tokens; espere "completion_tokens":256 [não executado]
curl -s -m 180 http://192.168.50.151:8000/v1/completions -H 'Content-Type: application/json' -d '{"model":"meta-llama/Meta-Llama-3.1-8B-Instruct","prompt":"Diga oi.","max_tokens":256,"temperature":0,"ignore_eos":true}' | grep -oE '"usage": *\{[^}]*\}'

# carga contra a API do Ray a partir de um pod sem GPU: ver runbooks/medicao-ray-pp3.md [não executado]

# memória e uso de cada GPU, de dentro de cada pod do Ray              [executado 2026-10-28]
for d in ray-head ray-worker-2 ray-worker-3; do echo "$d: $(kubectl exec -n vllms deploy/$d -- nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader 2>&1)"; done
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
