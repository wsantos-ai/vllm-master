# vLLM em Kubernetes com Tesla V100S — Estudo de Caso

> Estado (2026-10-14): **a `v0.19.1` roda na V100S** (AC-13). O Qwen3.8-27B em bitsandbytes foi
> descartado: ~3-5 *tokens*/s e nenhum ganho com concorrência (AC-14, AC-16, D-03). **Objetivo do
> estudo, confirmado pelo usuário: servir várias requisições simultâneas.** Próximo: medição de
> concorrência B-001 com `Qwen/Qwen2.5-7B-Instruct` em FP16 (PD-10).

## Resumo

- O *cluster* tem **3 nós Dell R720, cada um com 1 Tesla V100S-PCIE-32GB** (`sm_70`). Não existe nó
  com 2 GPUs, então *tensor parallel* dentro de um nó não é opção ([AC-01](#ac-01), [AC-04](#ac-04)).
- O *runtime* do Kubernetes é **containerd**, não Docker ([AC-02](#ac-02)).
- O CUDA 13 não compila para Volta, e o vLLM passou a ser construído com CUDA 13 na `v0.20.0`. **A
  `v0.19.1` é a última versão cujo Dockerfile inclui `sm_70`** ([AC-11](#ac-11)), **e ela roda de fato na
  V100S**: motor V1, *attention* Triton, *CUDA graphs*, FP16, em CPU sem AVX2 ([AC-13](#ac-13)). AWQ e
  FP8 não rodam.
- Uma imagem recente do vLLM ocupa ~3,4× o tamanho comprimido (30 G para a `v0.19.1`): **cabe uma por
  nó** no `/` de 70 G ([AC-09](#ac-09)).
- **vLLM `v0.6.4` + GPTQ serve um modelo de 33B numa V100S**, com *attention* XFormers e espaço de
  *KV cache* para 43.600 *tokens* ([AC-05](#ac-05)).
- A `v0.12.0` que "cai em *loop*" nunca chegou à GPU: morre com `401` no repositório *gated* da Meta.
  **Ainda não se sabe se a `v0.12.0` roda em `sm_70`** ([AC-07](#ac-07)).
- O serviço atual está num IP de LoadBalancer **sem `--api-key`** ([AC-06](#ac-06)).
- **Dividir um modelo entre dois nós pelo Ray funciona na `v0.19.1`, mas rende menos que uma GPU
  sozinha**: o Qwen2.5-7B em 01 + 02 deu 36,7 e 510,6 *tok*/s (1 e 32 usuários), contra 47,0 e 680,4
  em 1 GPU. Só o *KV cache* cresce (3,1×). Para modelos que cabem em 32 GB, réplicas ([AC-23](#ac-23)).
- A rede entre os nós é 1 GbE por fluxo, o que descarta paralelismo multinó e limita o carregamento
  pelo NFS. `/home` tem 755 G livres por nó para cache local ([AC-08](#ac-08), [AC-09](#ac-09)).

---

## 1. Contexto e pergunta

**Pergunta:** qual é a configuração ótima do vLLM (*inference* de LLMs, API OpenAI-compatível) neste
ambiente, e quanto cada escolha ganha ou custa?

**Restrições que decidem o caso:**

- 1 GPU por nó, 3 nós. `[confirmado, AC-01]`
- Tesla V100S-PCIE-32GB, Volta, *compute capability* 7.0. `[confirmado, AC-04]`
- Volta não tem BF16 nativo nem FP8; o suporte do vLLM a `sm_70` depende da versão. `[não verificado]`
- Já existe uma implantação chamada de produção (`vllm-deepseek-33b`): não mexer nela sem combinar.
  As métricas dela registram **1 requisição desde que subiu**, em 2026-09-18 (§2).

## 2. Ficha do ambiente

Fonte: [runbooks/inventario-do-ambiente.md](runbooks/inventario-do-ambiente.md). Versão da ficha:
**F4** (2026-10-27: Docker, disco e GPUs mudaram; o resto é da F3, 2026-09-29, Blocos 1, 1b e 2). Logs
do Bloco 2:
[sabdiia01](logs-analysis/inventario-no-sabdiia01-2026-09-29-1006.log),
[sabdiia02](logs-analysis/inventario-no-sabdiia02-2026-09-29-1006.log),
[sabdiia03](logs-analysis/inventario-no-sabdiia03-2026-09-29-1004.log). Logs de 2026-10-27:
[01](logs-analysis/ray-docker-inventario-sabdiia01-2026-10-27-1214.log),
[02](logs-analysis/ray-docker-inventario-sabdiia02-2026-10-27-1218.log),
[03](logs-analysis/ray-docker-inventario-sabdiia03-2026-10-27-1218.log).

| Item | Valor | Comando / log |
|---|---|---|
| Kubernetes | **`v1.37.1`** nos 3 *kubelets* em 2026-10-28 (era `v1.37.0` em 2026-09-28; data da troca `[não verificado]`); *kernel* `6.12.0-207.111.5.6.el9uek`, Oracle Linux 9.8. `sabdiia01` voltou `Ready` em 2026-10-28 00:53 e `sabdiia02` em 2026-10-27 19:02 (reinício `[hipótese]`) | `get nodes -o wide`, `describe node` ([01](logs-analysis/estado-disco-rede-sabdiia01-2026-10-28-1419.log), 2026-10-28) · `kubectl version` · [cluster](logs-analysis/inventario-cluster-2026-09-28.txt) |
| Nós | 3 Dell PowerEdge R720: `sabdiia01` (.151), `sabdiia02` (.152), `sabdiia03` (.150) em 192.168.50.0/24; todos `control-plane`, sem *taints* | `get nodes -o wide`, `describe nodes` · [vllms](logs-analysis/inventario-vllms-2026-09-28.txt) |
| SO / *kernel* | Oracle Linux Server 9.8 / `6.12.0-206.104.3.3.el9uek.x86_64` | idem |
| CPU | 2 × Xeon E5-2690 (Sandy Bridge-EP, 2,90 GHz), 8 núcleos por *socket*, HT, 32 *threads*, 2 nós NUMA. **Sem AVX2** (só `avx`) | `lscpu`; *flags* de `/proc/cpuinfo` (Bloco 2) |
| RAM | 755 GiB por nó, sem *swap* ativo | `free -h` |
| CPU livre | *requests* já alocados: 1,4 a 5,4 vCPU por nó; *control plane* pesa pouco | `describe nodes` (Allocated) |
| Disco local | 1 disco `sda` 836,6 G, `ROTA=1` (rotacional, ou volume de RAID que se declara assim `[hipótese]`). **2026-10-28 14:19, os 3 nós iguais: `/` 631 G e `/home` 200 G** (LVM `ol`, sem espaço livre no VG). `/` livre: **580 G (01), 563 G (02), 534 G (03)**; `/home` livre: 99 G (01), 77 G (02), 156 G (03). Imagens (`/var/lib/containerd`) e `etcd` seguem em `/`; o `imageFs` do *kubelet* tem 677,5 GB de capacidade; `DiskPressure False` (AC-09, PD-15 fechada). Histórico, **2026-10-27 14:20:** `/` (70 G) com **39 G livres em `sabdiia01`** (46 %) e 22 G em `sabdiia02` (70 %), depois de chegar a 100 % nos dois às 12:14 e ser limpo pelo administrador; `/var/lib/etcd` fica em `/`. `/home` 761 G com 652 G (01) e 717 G (02) livres às 12:14. **`sabdiia03` foi redimensionado:** `/` 631 G com 537 G livres, `/home` 200 G com 168 G livres. Em 2026-09-29: `/` com 20-28 G livres e `/home` com 755 G nos 3 | `df -h`, `du` (2026-10-27) — AC-09, AC-20 |
| *Runtime* | **`containerd://2.4.2`** nos 3 nós em 2026-10-28 (era `2.3.5` em 2026-09-29; data da troca `[não verificado]`); NVIDIA Container Toolkit `1.20.0` `[não reconferido]`. A regravação da configuração em 2026-10-26 (abaixo) pode ser parte dessa atualização `[hipótese]`. **Docker e Podman instalados nos 3 nós** desde alguma data entre 2026-09-29 (ausentes) e 2026-10-27, fora do Kubernetes; `data-root` do Docker em `/home/utec/docker_data` (01 e 02, 14:20). **2026-10-29: em 01, `v0.19.0`, `v0.19.1` e `v0.5.4`** (quem baixou as duas primeiras `[não verificado]`, provavelmente o administrador); **em 02, `v0.5.4` e `v0.19.1`** (esta por `ctr`, AC-24). Em 2026-10-27 não havia nenhuma `vllm-openai` em 01 e 02. Em 02, `image_pull_progress_timeout = '5m0s'` (AC-24). **Em `sabdiia01`, a configuração do containerd foi regravada em 2026-10-26 18:39**: `99-nvidia.toml` passou de 5124 para 5226 *bytes*, e o `config dump` agora avisa `Ignoring unknown key` para `enable_cdi`, `enable_experimental_restore_via_create` e `cni bin_dir` (nenhum aviso em 2026-10-02). Efeito na entrega de GPU: `[não verificado]`, conferir no próximo arranque de *pod* com GPU em 01 | `command -v`, `docker info`, `ctr images ls` (2026-10-27; imagens reconferidas em 2026-10-29) — AC-20, AC-24 |
| `kubectl` nos nós | funciona em 01 e 02; **em `sabdiia03` falha** (`apiVersion must be specified for oidc to use exec authentication plugin`): rode blocos com `kubectl` em 01 ou 02 | log de 03, 2026-10-27 |
| Gestão de GPU | NVIDIA GPU Operator (*device plugin*, *toolkit*, GFD, NFD, DCGM *exporter*); *driver* `pre-installed` no *host* | *labels* `nvidia.com/gpu.deploy.*` |
| GPU | `Tesla-V100S-PCIE-32GB`, 32768 MiB, `compute 7.0`, família `volta`; sem MIG, sem MPS, `sharing-strategy=none` | *labels* GFD |
| *Driver* / CUDA | `580.173.02` / `13.0` nos 3 nós | *labels* `nvidia.com/cuda.*` |
| RuntimeClasses | `nvidia`, `nvidia-cdi`, `nvidia-legacy` | `get runtimeclass` |
| GPU no *host* | PCIe Gen3, largura máx. x16 nos 3; **`sabdiia03` negociou x8** com a GPU em uso. ECC ligado em 01 e 02, **desligado em 03**. *Persistence mode* **desligado em 01**, ligado em 02 e 03. Limite de potência 250 W | `nvidia-smi`, `--query-gpu` (Bloco 2) |
| Armazenamento | só `nfs-storage` (`nfs.csi.k8s.io`, `Retain`, RWX). Servidor `[2801:80:f8c:302::aa]:/SABDIIAK8S_NFS01` (IPv6), NFS 4.1, `rsize=wsize=65536`, sem `nconnect`. Exportação de 500 G com **17 G usados** (todos os PVCs somados) | `get storageclass`, `get pv`; `findmnt`, `df` (Bloco 2) |
| Rede | **Dois *bonds* desde 2026-10-28**, ambos 802.3ad com `Transmit Hash Policy: layer2`. **`bond0`** (6 × 1 GbE): VLAN `bond0.500`, IP do nó (`192.168.50.150/151/152`), rota *default* e **IP que o Calico usa para os *pods***; em `sabdiia01`, `enp65s0f1` segue a 100 Mbps fora do agregado (5 portas ativas, `speed=5000`). **`bond1`** (novo, 4 × 10 GbE, placas BCM57810 e Intel 82599ES): só a VLAN `bond1.302`, **só IPv6** (`2801:80:f8c:302::/64`, mesma rede do servidor NFS); `speed=40000` em 01 e 02, **`20000` em 03** (duas portas em outro agregador). MTU 1500, exceto **`bond0`/`bond0.500` de 03 com 9000 e o Calico de 03 com 8980**. **17:12: nova VLAN `bond1.20` nos 3 nós, `UP`, sem nenhum endereço** (nem IPv4, nem IPv6 de *link*), MTU 1500; as portas físicas do `bond1` estão com 9000 e o `bond1` com 1500. RTT 03 → 02: 0,311 ms (`bond1`) × 0,348 ms (`bond0`) | `/proc/net/bonding/*`, `ip -br addr`, `ip route`, anotação `projectcalico.org/IPv4Address` (2026-10-28) — AC-08 |
| Rede / borda | Calico; MetalLB (pool `pool-publico`); Kong no *namespace* `kong` | *pods* e anotações |
| Observabilidade | kube-prometheus (Prometheus, Alertmanager), `dcgm-exporter`, `metrics-server` | *pods* em `monitoring` e `gpu-operator` |

### Ocupação das GPUs e o *namespace* `vllms` (2026-10-27)

As GPUs de 01 e 02 estavam **ocupadas às 12:14 e vazias às 14:20**, sempre com `0 0` no Kubernetes: o Ray do
administrador roda fora dele e liga e desliga sem aviso (AC-19). Confira as duas perguntas de "Qual GPU
está livre?" imediatamente antes de usar qualquer uma.

| Nó | GPU às 12:14-12:18 (`nvidia-smi`) | GPU às 14:20 | Ocupante |
|---|---|---|---|
| `sabdiia01` | **8.162 MiB**, `python3` (PID 579011), 0 % de uso | sem processo | *head* do Ray do administrador (*venv* no *host*, `root`), ainda no ar às 14:20 com a GPU registrada no Ray (`0.0/1.0 GPU`). `vllm-llama31-8b` segue com `--replicas=0` desde 2026-10-02 `[não reconferido]` |
| `sabdiia02` | **8.162 MiB**, `ray::RayWorkerWrapper.execute_method`, 0 % de uso | sem processo; Ray parado | *worker* do Ray às 12:18; fora do *cluster* Ray às 14:22 |
| `sabdiia03` | 27.882 MiB, `/usr/bin/python3` | `[não lido]` | `vllm-deepseek-33b` (`v0.6.4`, GPTQ), `Running` há 26 h, 0 reinícios, IP `192.168.50.160:8001`. `open-webui` em `CreateContainerConfigError` |

**2026-10-28 14:19-14:21: as 3 GPUs com 0 MiB e nenhum processo, inclusive a de `sabdiia03`**, onde o
deepseek de produção ocupava 27.882 MiB na véspera. Estado do *pod* `vllm-deepseek-33b`: `[não verificado]`
(o `kubectl` de 03 falha por OIDC e o bloco de 01 não listou `vllms`). Os nós reiniciaram na manutenção
`[hipótese]`; um *pod* do vLLM leva minutos para recarregar o modelo, e pode estar subindo ou parado.

**2026-10-28 15:00 (`sabdiia01`): o *namespace* `vllms` não lista mais o `vllm-deepseek-33b`** (nem
`vllm-llama31-8b`, nem `open-webui`). Só há o **Ray do administrador, agora dentro do Kubernetes**: três
*Deployments* simples (não KubeRay), imagem `vllm/vllm-openai:v0.5.4`, criados às ~14:50
([log](logs-analysis/producao-rede-nova-sabdiia01-2026-10-28-1500.log)). Se o *Deployment* do deepseek foi
apagado ou escalado a 0, e se os *pods* do Ray pedem `nvidia.com/gpu`: respondido às 15:11 (AC-19):
deepseek e llama em `0/0`, e os três *pods* do Ray com 1 GPU cada.

```
ray-head-85bcdd9859-p65sd    1/1   Running   0               10m   sabdiia01
ray-worker-5b5488995-gjcgb   1/1   Running   2 (69s ago)     10m   sabdiia03
ray-worker-5b5488995-qpl84   0/1   Error     2 (4m32s ago)   10m   sabdiia02
Warning   BackOff   Back-off restarting failed container vllm-worker in pod ray-worker-...
```

**2026-10-29 10:35-10:36: GPUs de 01 e 02 livres** (`0 0` no Kubernetes, 0 MiB, nenhum processo) e
**`vllms` sem nenhum *pod***: o Ray do administrador saiu em 2026-10-28 17:10, e o deepseek e o llama
seguem em `0/0`. Em 03, `0 0` no Kubernetes; `nvidia-smi` não lido. A B-004 usou 01 e 02 de 10:39 a
11:24 e os liberou ([01](logs-analysis/pronto-para-teste-sabdiia01-2026-10-29-1035.log),
[02](logs-analysis/pronto-para-teste-sabdiia02-2026-10-29-1036.log)).

Em 2026-09-29, o `/metrics` do deepseek registrava `request_success_total` = **1** desde 09-18 (75
*tokens* de entrada, 158 de saída).

Os logs de `kubectl logs` do deepseek começam em 09-27: o arranque foi perdido na rotação de logs do
*kubelet* `[hipótese]`. **Guarde o log de arranque de todo *pod* novo logo que ele subir.**

## 3. O caminho

| Data | Evento | Achado |
|---|---|---|
| 2026-09-28 | Início do estudo; estrutura do repositório criada | — |
| 2026-09-28 | Inventário do *cluster* (Bloco 1) | AC-01, AC-02, AC-03 |
| 2026-09-28 | Inventário de GPUs, nós e `vllms` (Bloco 1b) | AC-04, AC-05, AC-06 |
| 2026-09-29 | Logs e métricas das implantações existentes (Bloco 1c) | AC-05 (ampliado), AC-07 |
| 2026-09-29 | Inventário de cada nó (Bloco 2) | AC-08, AC-09 |
| 2026-09-29 | Imagens e espaço em `/` (Bloco 2b) | AC-09 (ampliado) |
| 2026-09-29 | Limiares do *kubelet* e imagens por nó (Bloco 2c) | AC-09 (folga por nó) |
| 2026-09-29 | GPU entregue a um *pod* em `sabdiia02` (Bloco 3). **Fim do inventário** | AC-10 |
| 2026-09-29 | Pesquisa de versão: Dockerfiles, código e *release notes* do vLLM e do CUDA | AC-11, D-01 (provisória) |
| 2026-09-29 | Validação do *token* HF (Bloco 1d) | AC-07 (causa confirmada) |
| 2026-10-02 | Análise do modelo pedido, `Qwen/Qwen3.8-27B` (fontes, sem execução) | AC-12, PD-16 |
| 2026-10-02 | Diagnóstico do *bond* de `sabdiia01` e vazão medida (98,3 MB/s) | AC-08 (corrigido) |
| 2026-10-02 | `vllm-llama31-8b` desligado (`--replicas=0`); GPU de `sabdiia01` liberada para o primeiro arranque | §2 |
| 2026-10-02 | Imagem `v0.12.0` removida de `sabdiia01` pelo *digest*: 27 G liberados | AC-09 (medido), D-02 |
| 2026-10-02 | **Primeiro arranque da `v0.19.1` na V100S**: `Ready`, Triton, *CUDA graphs*, geração OK | AC-13, D-01 confirmada, §6 |
| 2026-10-02 | `Qwen/Qwen3.8-27B` com bitsandbytes, tentativa 1: carrega (18,06 GiB), cai por OOM no *profiling* de *CUDA graphs* | AC-14 |
| 2026-10-02 | Tentativa 2, com `--enforce-eager`: **`Ready`**, *KV cache* de 20.384 *tokens*, geração a ~3 *tokens*/s | AC-14, PD-16 fechada, PD-18 |
| 2026-10-13 | Usuário descarta o Qwen3.8-27B por velocidade; pesquisa de substitutos em GPTQ | D-03, AC-15, PD-18 fechada, PD-19 |
| 2026-10-14 | Concorrência 1/4/8 no Qwen3.8-27B: vazão total parada em ~4 *tokens*/s | AC-16 |
| 2026-10-14 | Usuário define o objetivo: vLLM para várias requisições simultâneas; `vllm-qwen38` apagado; runbook B-001 preparado | PD-10 (redefinida) |
| 2026-10-14 | Arranque do `Qwen/Qwen2.5-7B-Instruct` FP16 para a B-001: `Ready` em 4 min, *KV cache* de 246.016 *tokens*, *CUDA graphs* capturados | PD-10 |
| 2026-10-14 | **B-001**: vazão total escala 13× de 1 a 64 requisições (10 → 130 *tok*/s), sem preempção; valores absolutos sob suspeita de estrangulamento | [B-001](medicoes/B-001-concorrencia-qwen25-7b-fp16.md), PD-23 |
| 2026-10-14 | **Diagnóstico B-001b**: a GPU de `sabdiia01` estrangula por temperatura (82 °C, *clock* a ~400 MHz); a CPU não é a causa. B-001 invalidada como número do motor | AC-17, PD-23 fechada, PD-24 |
| 2026-10-20 | Análise da arquitetura da aplicação que vai consumir o vLLM (ABDI, v0.3, [F-023]): depende de *tool calling* não testado e roda fora do *cluster* | PD-25, PD-26 |
| 2026-10-22 | Administrador ajusta a refrigeração de `sabdiia01`. Rearranque do 7B cai: o *pod* não resolve `huggingface.co`, e a `v0.19.1` consulta o Hub mesmo com o modelo em cache ([F-024]) | PD-24; Bloco A2 (`HF_HUB_OFFLINE=1`) |
| 2026-10-22 | Rearranque com `HF_HUB_OFFLINE=1`: `Ready` em 2 min 44 s. Os *pods* de `sabdiia01` estão sem DNS, inclusive o do *cluster* | AC-18, PD-28 |
| 2026-10-22 | **Reteste térmico B-001c**: sem estrangulamento (72 °C máx. a 250 W); 47 *tok*/s com 1 usuário e 680 *tok*/s com 32, contra 10 e 114 antes do ajuste | AC-17, PD-24 (`sabdiia01` resolvido) |
| 2026-10-23 | 2ª intervenção, na refrigeração da sala. Reteste B-001d: curva de temperatura e vazão iguais às de 10-22 (72 °C, 680 *tok*/s); sem efeito mensurável na GPU, e o *benchmark* se repete entre dias | AC-17 |
| 2026-10-27 | Análise do projeto Ray do administrador (`llm_lhama_prototype`) e inventário dos 3 nós: Ray no *host* ocupa as GPUs de 01 e 02 sem o Kubernetes saber; `/` cheio em 01 e 02, com *pods* expulsos; Docker instalado | AC-19, AC-20, D-02 suspensa, PD-29, PD-30 |
| 2026-10-27 | Depois da limpeza do administrador: `/` em 46 % (01) e 70 % (02), *pods* de volta, GPUs vazias, Ray só com o *head*; vLLM `0.5.4` no *venv*; a `v0.19.1` foi apagada de 01 | AC-19, AC-20 (ampliados), PD-30 fechada, PD-15 volta a bloquear |
| 2026-10-27 | Proposta do administrador (dividir modelo entre nós com Ray) confrontada com o RTT medido (0,247 ms) e o código da `v0.19.1` | AC-21, AC-08 (corrigido), PD-31 |
| 2026-10-27 | Pergunta: dividir entre nós aproxima o resultado do gpt-oss no Ollama? *Model card* e código MXFP4 da `v0.19.1` | AC-22 |
| 2026-10-27 | Arquitetura de produção: réplicas de 1 GPU por nó, sem Ray; `Qwen3-30B-A3B-GPTQ-Int4` como primeiro candidato (~16,2 GB) | D-04 (provisória), PD-19 |
| 2026-10-28 | Manutenção do administrador conferida nos 3 nós: `/` passou a 631 G em 01 e 02 (como em 03), `/home` a 200 G; novo `bond1` de 4 × 10 GbE só com IPv6 da VLAN 302 (rede do NFS); Kubernetes `v1.37.1`, containerd `2.4.2`. Os *pods* continuam na rede de 1 GbE; GPU de 03 vazia | PD-15 fechada, AC-08 e AC-09 atualizados, PD-31 |
| 2026-10-28 | RTT pela rede nova ~0,24-0,31 ms, quase igual ao da antiga. Às 15:00, `vllms` sem o deepseek de produção e com o Ray do administrador em 3 *pods* (`v0.5.4`), *workers* reiniciando | AC-08, §2, PD-29 |
| 2026-10-28 | 15:11: Ray refeito em 3 *Deployments* com 1 GPU cada, todos no ar; deepseek e llama em `0/0`; nenhuma GPU livre para o estudo | AC-19 (atualizado), PD-29 |
| 2026-10-28 | 15:22: o Ray roda `Meta-Llama-3.1-8B-Instruct` (vLLM `0.5.4`) com *pipeline parallel* 3, um pedaço por nó, servidor iniciado à mão, `hostNetwork`, sem Ray Serve | AC-19, AC-21, PD-29 |
| 2026-10-28 | Análise do repositório `llm_lhama_prototype` (`45efe37`, pasta `k8s/`): servidor subido por `kubectl exec -it`, NCCL/Gloo em `bond0.500`, *token* do HF em `ConfigMap` versionado | AC-19 |
| 2026-10-28 | 17:12: nada do Ray/vLLM em execução nos 3 nós (nem *pod*, nem processo, nem contêiner; GPUs 0 MiB). A rede ganhou a VLAN `bond1.20` nos 3 nós, sem endereço: suspeita principal do erro de subida `[hipótese]` | AC-19, §2 |
| 2026-10-28 | 17:10: os *Deployments* `ray-head`/`ray-worker-2`/`ray-worker-3` foram removidos de `vllms` (nenhum *pod* no *namespace*); o administrador ajusta a rede e a nova subida da API dá erro `[erro não visto]` | AC-19 |
| 2026-10-28 | 16:51: a API do Ray não responde (porta 8000 recusada), GPUs com 0 MiB, *pods* `Running` sem reinício: o servidor saiu e o Kubernetes não viu. B-003 bloqueada até o administrador subir de novo | AC-19 |
| 2026-10-29 | Registro de testes compartilhado em `vllm-config` (`docs/registro-de-testes.md`): protocolo fixo 512 → 256 *tokens*, `temperature 0`, c=1/16/32. `v0.19.0` e `v0.19.1` têm `sm_70`; a diferença entre elas é o `transformers` v5 ([F-036]) | — |
| 2026-10-29 | 10:35: GPUs de 01 e 02 livres, `vllms` vazio; em 01 já estão a `v0.19.0` e a `v0.19.1` | §2 |
| 2026-10-29 | O *pull* da `v0.19.1` em 02 pelo *kubelet* cai 2× com `context canceled` (limite de 5 min do containerd); `ctr images pull` resolve em 6,5 min | AC-24 |
| 2026-10-29 | **B-004: Ray do estudo, Qwen2.5-7B com *pipeline parallel* 2 em 01 + 02, `v0.19.1`**: sobe e mede; 36,7 e 510,6 *tok*/s (1 e 32 usuários) contra 47,0 e 680,4 com 1 GPU; *KV cache* 3,1× | AC-23, AC-21 (corrigido), PD-31 |

## 4. Achados

### AC-01 — São 3 nós com 1 GPU cada: não há *tensor parallel* dentro de um nó {#ac-01}

**O que é.** As GPUs estão em máquinas diferentes; um *pod* recebe no máximo 1. Juntar GPUs num modelo
só exige paralelismo multinó, pela rede, o que custa latência a cada passo de *decode* `[hipótese]`.

**Evidência.** [inventario-cluster-2026-09-28.txt](logs-analysis/inventario-cluster-2026-09-28.txt);
`nvidia.com/gpu.count=1` nos 3 nós ([inventario-vllms](logs-analysis/inventario-vllms-2026-09-28.txt)).

```
NODE        GPU_ALLOC   GPU_CAP
sabdiia01   1           1
sabdiia02   1           1
sabdiia03   1           1
```

**Regra prática.** Parta de **1 réplica do vLLM por nó, 1 GPU por réplica**. Isso limita o modelo ao que
cabe em 32 GB. Paralelismo multinó está descartado enquanto a rede for 1 GbE (AC-08).

**Validade.** Kubernetes, GFD e `nvidia-smi` no *host* (1 GPU em cada nó), 2026-09-29.

### AC-02 — O *runtime* do Kubernetes é containerd, não Docker {#ac-02}

**O que é.** Os *pods* rodam em containerd, e a GPU chega a eles pelo GPU Operator (*toolkit* +
*device plugin* + RuntimeClass). Instruções de vLLM escritas para `docker run` (`--gpus`, `--ipc=host`,
`--shm-size`) precisam de equivalente no manifesto. A implantação existente já traduz `--shm-size`
como `emptyDir` com `medium: Memory` em `/dev/shm` (AC-05).

**Evidência.** `CONTAINER-RUNTIME containerd://2.3.5` nos 3 nós
([log](logs-analysis/inventario-cluster-2026-09-28.txt)).

**Regra prática.** Descreva a implantação em manifesto Kubernetes, não em `docker run`.

**Validade.** Kubernetes `v1.37.0`, 2026-09-29. Um *pod* **sem** `runtimeClassName` recebeu a GPU
(AC-10): a configuração padrão do containerd já passa pelo *toolkit* da NVIDIA `[inferência]`.

### AC-10 — Um *pod* com `nvidia.com/gpu: 1` recebe exatamente uma V100S, sem `runtimeClassName` {#ac-10}

**O que é.** O caminho Kubernetes → GPU Operator → containerd → GPU funciona em `sabdiia02`. Basta pedir
`nvidia.com/gpu: 1` em `resources.limits`; o *pod* não precisou declarar RuntimeClass. O `nvidia-smi`
dentro do contêiner vem do *driver* do *host*, já que a imagem *base* não o traz. Uma imagem com CUDA
12.4 rodou sobre o *driver* 580 / CUDA 13.0.

**Evidência.** [teste-gpu-pod-2026-09-29-1138.log](logs-analysis/teste-gpu-pod-2026-09-29-1138.log):

```
|   0  Tesla V100S-PCIE-32GB          On  |   00000000:05:00.0 Off |                    0 |
| N/A   34C    P0             27W /  250W |       0MiB /  32768MiB |      0%      Default |
    Image:         nvidia/cuda:12.4.1-base-ubuntu22.04
      Reason:       Completed
      Exit Code:    0
  Normal  Scheduled  6s    default-scheduler  Successfully assigned default/teste-gpu to sabdiia02
```

**Regra prática.** Nos manifestos do vLLM, peça a GPU só com `resources.limits: nvidia.com/gpu: 1` e fixe
o nó com `nodeSelector: kubernetes.io/hostname: sabdiia02` enquanto for o único livre.

**Validade.** `sabdiia02`, 2026-09-29. Imagens com CUDA 13 não foram testadas.

### AC-11 — `v0.19.1` é a última versão do vLLM com `sm_70` no Dockerfile; nela, Volta = Triton + FP16 + GPTQ {#ac-11}

**O que é.** Da `v0.12.0` à `v0.19.1`, o Dockerfile do vLLM compila com CUDA 12.9.1 e inclui `7.0` na lista
de arquiteturas. Na `v0.20.0` passa a CUDA 13.0.2 e tira o `7.0`, coerente com o CUDA 13 não compilar
para Volta (AC-04). Desde então a imagem padrão e o PyPI são CUDA 13. As variantes `-cu129` usam o mesmo
Dockerfile, sem `7.0` `[inferência: o *pipeline* de *release* pode passar outra lista, não verificado]`.
No código da `v0.19.1`, o que vale para a V100S:
- ***Attention*:** a ordem de tentativa abaixo de CC 8.0 é FlashAttention → FlashInfer (exige CC ≥ 7.5) →
  **Triton** (aceita qualquer CC). O esperado é Triton `[hipótese até o log de arranque]`.
- **BF16:** recusado com `ValueError`; use `--dtype float16`.
- ***Quantization*:** GPTQ exige CC ≥ 6.0 (roda); **AWQ exige CC ≥ 7.5 (não roda)**.
- **AVX2:** a `v0.12.0` importou o vLLM e processou os argumentos numa CPU sem AVX2 antes de cair por
  outro motivo (AC-07). É indício de que a CPU não barra, não prova.

**Evidência.** [F-003], [F-004] (Dockerfiles), [F-005] (*release notes*), [F-006] (seleção de *backend*),
[F-007] (capacidade mínima de GPTQ/AWQ), [F-008] (imagens no Docker Hub), em [FONTES.md](FONTES.md):

```
v0.19.1  ARG CUDA_VERSION=12.9.1   torch_cuda_arch_list='7.0 7.5 8.0 8.9 9.0 10.0 12.0'
v0.20.0  ARG CUDA_VERSION=13.0.2   torch_cuda_arch_list='7.5 8.0 8.6 8.9 9.0 10.0 11.0 12.0+PTX'
AWQConfig.get_min_capability -> 75   # "The AWQ kernel only supports Turing or newer GPUs."
```

**Regra prática.** Para V100/V100S, use `vllm/vllm-openai:v0.19.1` ou anterior, com `--dtype float16`, e
modelos FP16 ou GPTQ, nunca AWQ ou FP8. Antes de trocar de versão, confira `torch_cuda_arch_list` no
Dockerfile da *tag*.

**Validade.** Leitura de código e documentação em 2026-09-29. O arranque de 2026-10-02 confirmou que a
imagem publicada da `v0.19.1` tem `sm_70`, usa Triton e não exige AVX2 (AC-13). GPTQ e a recusa de AWQ na
`v0.19.1` continuam só lidos no código, `[não executado]`.

### AC-12 — `Qwen/Qwen3.8-27B` não cabe numa V100S em FP16 e não tem variante quantizada que rode em `sm_70` {#ac-12}

**O que é.** O modelo pedido tem 27,78 bilhões de parâmetros. Em FP16 são 2 *bytes* por parâmetro:
**55,6 GB** só de *weights*, contra 32 GiB da V100S, e não há como somar GPUs (AC-01, AC-08). As variantes
quantizadas publicadas não servem aqui: FP8 e NVFP4 exigem GPUs mais novas (AC-11), GGUF, EXL3 e MLX
são de outros motores, e **não existe GPTQ** publicada, que é o formato que roda em Volta. Sobra um
caminho dentro do vLLM: quantizar para 4 bits ao carregar, com bitsandbytes, que na `v0.19.1` aceita
CC ≥ 7.0. Seriam ~14 GB de *weights* `[cálculo: 0,5 byte/parâmetro; partes não quantizadas a mais]`. A
`v0.19.1` conhece a arquitetura (`qwen3_5`); a `v0.6.4`, de 2024, não `[inferência pela data]`.

**Evidência.** [F-009] a [F-012] em [FONTES.md](FONTES.md):

```
safetensors.parameters: BF16: 27,781,427,952        -> x 2 bytes = 55,6 GB
"Qwen3_5ForConditionalGeneration": ("qwen3_5", ...)  (registry.py, v0.19.1)
BitsAndBytesConfig.get_min_capability -> 70
```

**Regra prática.** Antes de escolher um modelo para a V100S, multiplique os parâmetros por 2 *bytes*: acima
de ~14 bilhões, FP16 não cabe com folga para *KV cache*, e é preciso GPTQ pronta ou bitsandbytes. Para
este modelo, o único caminho no vLLM é `v0.19.1` + bitsandbytes 4 bits, que depende de destravar o disco
(PD-15) e de teste (PD-16).

**Validade.** Leitura de fontes em 2026-10-02. Conferido no *pod* em execução no mesmo dia (saída colada
pelo usuário): a imagem `v0.19.1` traz `bitsandbytes 0.49.2`, `transformers 5.5.4` e
`torch 2.10.0+cu129` (CUDA 12.9); a flag é `--quantization bitsandbytes` ([F-013]). **O modelo ainda não
foi carregado.** Não verificado: se o bitsandbytes funciona com este modelo multimodal, o uso real de
VRAM e a velocidade (PD-16).

### AC-13 — vLLM `v0.19.1` roda na V100S: motor V1, *attention* Triton, *CUDA graphs* e FP16, em CPU sem AVX2 {#ac-13}

**O que é.** Primeiro arranque real de uma versão moderna do vLLM neste *hardware*
(`Qwen/Qwen2.5-0.5B-Instruct`, `--dtype float16`, `sabdiia01`). O que o log confirma:
- **Sobe e gera.** Sem `no kernel image` nem `Illegal instruction`: a imagem publicada tem `sm_70` e não
  exige AVX2.
- ***Attention*:** `TRITON_ATTN`, escolhido entre `['TRITON_ATTN', 'FLEX_ATTENTION']`. A linha `ERROR`
  sobre FlashAttention 2 é só o aviso de que ela exige CC ≥ 8; não é falha.
- **BF16 → FP16:** com `--dtype float16`, o vLLM converte e avisa (`Casting torch.bfloat16 to
  torch.float16`).
- ***CUDA graphs* funcionam em `sm_70`:** 51 + 35 grafos capturados em 9 s, ocupando 0,32 GiB. Não é
  preciso `--enforce-eager`.
- **Padrões da versão:** `enable_prefix_caching=True`, `enable_chunked_prefill=True`,
  `gpu_memory_utilization` 0,90, e o `generation_config.json` do modelo **sobrescreve a amostragem**
  (`--generation-config vllm` desliga isso).
- **Tempos (arranque a frio):** imagem de 9,6 GB baixada em 5 min 19 s; do início do contêiner ao
  servidor no ar, 1 min 52 s (13,5 s de *download* do modelo, 19,7 s de `torch.compile`, 43,8 s de
  inicialização do motor).
- **Memória:** modelo 0,93 GiB; *KV cache* 26,93 GiB = 2.353.152 *tokens*; `nvidia-smi` mostra
  29.998 MiB de 32.768.

**Evidência.** [primeiro-arranque-v0.19.1-retomada-sabdiia01-2026-10-02-1413.log](logs-analysis/primeiro-arranque-v0.19.1-retomada-sabdiia01-2026-10-02-1413.log):

```
(EngineCore) INFO  [core.py:105] Initializing a V1 LLM engine (v0.19.1) with config: ... dtype=torch.float16 ... enforce_eager=False ... enable_prefix_caching=True, enable_chunked_prefill=True
(EngineCore) ERROR [fa_utils.py:145] Cannot use FA version 2 is not supported due to FA2 is only supported on devices with compute capability >= 8
(EngineCore) INFO  [cuda.py:334] Using TRITON_ATTN attention backend out of potential backends: ['TRITON_ATTN', 'FLEX_ATTENTION'].
(EngineCore) INFO  [kv_cache_utils.py:1319] GPU KV cache size: 2,353,152 tokens
(EngineCore) INFO  [gpu_model_runner.py:6046] Graph capturing finished in 9 secs, took 0.32 GiB
Successfully pulled image "vllm/vllm-openai:v0.19.1" in 5m18.981s ... Image size: 9612695005 bytes.
{"version":"0.19.1"}   ... "text":" de R$ 1,2 trilhão e o país tem uma população de mais de" ... "completion_tokens":20
```

**Regra prática.** Em V100/V100S, use `vllm/vllm-openai:v0.19.1` com `--dtype float16`, sem
`--enforce-eager`. Ignore o `ERROR` de FA2. Em medições, passe `--generation-config vllm` ou fixe a
amostragem na requisição, e lembre que *prefix caching* vem ligado.

**Validade.** `v0.19.1`, `sabdiia01`, 2026-10-02, modelo de 0,5B, uma geração de 20 *tokens*. Não
testado: GPTQ, carga concorrente. Modelo grande com bitsandbytes: AC-14. *Throughput*: `[não medido]`.

### AC-14 — `Qwen/Qwen3.8-27B` roda numa V100S com bitsandbytes 4 bits e `--enforce-eager`, a ~3 *tokens*/s {#ac-14}

**Resultado (tentativa 2, 2026-10-02 15:09).** Com `--enforce-eager` o *pod* ficou `Ready` em 12 min 24 s
(modelo já em cache). Modelo 18,06 GiB; ***KV cache* 5,0 GiB = 20.384 *tokens***; 28.728 MiB de GPU em uso.
Uma geração de 200 *tokens* levou **71,1 s**: 13,5 s até o primeiro *token* e ~0,29 s por *token* depois,
ou seja, **~3,5 *tokens*/s** (o log do motor mostra 3,0 a 3,3). É **uma** requisição, sem concorrência:
ordem de grandeza, não medição. Para comparar, a única requisição registrada do deepseek 33B em GPTQ deu
~20 *tokens*/s (AC-05, também n = 1). Os 10 min de inicialização do motor se repetem a cada arranque
(`init engine ... took 606.65 seconds`). O texto saiu coerente, mas o raciocínio do modelo veio dentro
de `content` (termina em `</think>`), porque nenhum *reasoning parser* foi configurado, e consumiu a
maior parte dos 200 *tokens*.

```
INFO  [gpu_worker.py:436] Available KV cache memory: 5.0 GiB
INFO  [kv_cache_utils.py:1319] GPU KV cache size: 20,384 tokens
INFO  [core.py:283] init engine (profile, create kv cache, warmup model) took 606.65 seconds
INFO  [loggers.py:259] Engine 000: ... Avg generation throughput: 3.1 tokens/s, Running: 1 reqs
"usage":{"prompt_tokens":69,"total_tokens":269,"completion_tokens":200}   ### tempo total da requisição: 71.091192 s
vllm:time_to_first_token_seconds_sum 13.508248567581177
```

Log: [teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1509.log](logs-analysis/teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1509.log).
*CUDA graphs* não são opção para este modelo em 32 GB na `v0.19.1`: a medição exige um *KV cache* de 512
blocos de 784 *tokens*, e os 5,0 GiB disponíveis comportam 26 blocos `[cálculo a partir do log]`.

**Decisão (2026-10-13):** a velocidade não atende ao uso pretendido; o modelo foi descartado (D-03).

**Tentativa 1 (14:36), sem `--enforce-eager`: carrega em 18,06 GiB, mas cai por falta de memória ao medir os *CUDA graphs*.**

**O que é.** Primeira tentativa do modelo pedido (`v0.19.1`, `--quantization bitsandbytes`, `--dtype
float16`, `--max-model-len 8192`, `sabdiia01`). Funcionou até o carregamento: o `transformers` 5.5.4
reconhece a arquitetura (`Qwen3_5ForConditionalGeneration`), o bitsandbytes quantiza, e o modelo ocupa
**18,06 GiB** em vez de 55,6 GB. Caiu 22 min depois de iniciar, com `CUDA out of memory`, na etapa em que
o vLLM mede a memória dos *CUDA graphs*. Para isso ele cria um *KV cache* "mínimo" de 512 blocos, e neste
modelo, que é híbrido, cada bloco tem **784 *tokens*** (contra 16 nos modelos comuns): o mínimo deixa de
ser pequeno. Nesse momento a GPU já tinha 31,29 GiB em uso. Outros números do arranque:
- *download* de 55,6 GB em 432 s (~125 MB/s): o *link* de internet não é gargalo;
- rodada de *profiling*/*warmup*: **550 s**, um sinal de que a geração pode ser lenta `[hipótese]`;
- pico de ~25,2 GiB na GPU durante o *profiling*, com o codificador de imagem incluído;
- *prefix caching* vem desligado para este modelo.

**Evidência.** [teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1436.log](logs-analysis/teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1436.log):

```
INFO  [model.py:549] Resolved architecture: Qwen3_5ForConditionalGeneration
INFO  [config.py:281] Setting attention block size to 784 tokens to ensure that attention page size is >= mamba page size.
INFO  [weight_utils.py:581] Time spent downloading weights for Qwen/Qwen3.8-27B: 432.403565 seconds
INFO  [gpu_model_runner.py:4820] Model loading took 18.06 GiB memory and 454.135344 seconds
INFO  [monitor.py:76] Initial profiling/warmup run took 550.25 s
INFO  [kv_cache_utils.py:829] Overriding num_gpu_blocks=0 with num_gpu_blocks_override=512
  File ".../gpu_worker.py", line 381, in determine_available_memory
    cudagraph_memory_estimate = self.model_runner.profile_cudagraph_memory()
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 1.53 GiB. GPU 0 has a total capacity of 31.73 GiB of which 452.25 MiB is free.
```

**Regra prática.** Para este modelo em 32 GB: `vllm serve Qwen/Qwen3.8-27B --quantization bitsandbytes
--dtype float16 --max-model-len 8192 --enforce-eager`. O código da `v0.19.1` só chama
`profile_cudagraph_memory` quando `enforce_eager` é falso ([F-014]). Conte com ~3 *tokens*/s e 12 min de
arranque: serve para uso pontual ou em lote, não para conversa interativa. Dimensione `startupProbe`
para pelo menos 20 min. Antes de servir a usuários, configure o *reasoning parser* (PD-18).

**Validade.** `v0.19.1`, `sabdiia01`, 2026-10-02, duas tentativas, uma geração. Não medido: carga
concorrente, entrada de imagem, qualidade das respostas em 4 bits, contexto perto de 8192 *tokens*.

### AC-24 — O 1º *pull* da `v0.19.1` pelo Kubernetes cai com `context canceled`: o containerd desiste após 5 min sem progresso; `ctr images pull` baixa em 6,5 min {#ac-24}

**O que é.** Em `sabdiia02`, o *kubelet* tentou baixar a `v0.19.1` duas vezes, e as duas caíram ~7 min
depois de começar, **na mesma camada**, durante a descompactação. A configuração do containerd de 02 tem
`image_pull_progress_timeout = '5m0s'`: ele cancela o *pull* que fica 5 min sem progresso. O `ctr`, que não
passa por esse limite, baixou a mesma imagem sem erro em 6 min 30 s, e `/` subiu ~30 G no total (AC-09).
Descompactar a maior camada no disco destes nós não conta como progresso e passa dos 5 min `[hipótese bem
apoiada]`. O *kubelet* repete com intervalo crescente e cairia sempre no mesmo ponto. Em 01, o 1º *pull* da
`v0.19.1` pelo *kubelet* funcionou em 2026-10-02, com o containerd `2.3.5`; se o limite já existia ali,
`[não verificado]`.

**Evidência.** Eventos do *pod* `ray-pp2-worker` (colados no chat, 2026-10-29) e
[pull-v0191-sabdiia02-2026-10-29-1101.log](logs-analysis/pull-v0191-sabdiia02-2026-10-29-1101.log):

```
Failed to pull image "vllm/vllm-openai:v0.19.1": ... failed to extract layer (... sha256:257588654d22...) to overlayfs ...: context canceled
Failed to pull image "vllm/vllm-openai:v0.19.1": ... failed to extract layer (... sha256:257588654d22...) to overlayfs ...: context canceled
    image_pull_progress_timeout = '5m0s'
real	6m30.469s
ctr saiu com 0   fim 11:07:58
```

**Regra prática.** Antes do 1º *pod* com uma imagem do vLLM num nó, baixe-a no próprio nó (servidor,
bash, como `root`): `ctr -n k8s.io images pull docker.io/vllm/vllm-openai:v0.19.1`, e confira com
`ctr -n k8s.io images ls | grep vllm-openai`. A alternativa permanente é o administrador aumentar
`image_pull_progress_timeout` `[não executado]`.

**Validade.** 2026-10-29, `sabdiia02`, containerd `2.4.2`, imagem `v0.19.1` (~9,6 GB comprimida). O valor
do limite em 01 e 03 `[não verificado]`. Imagens menores (a `v0.5.4`, 5,48 GB) desceram pelo *kubelet* em
2026-10-28.

### AC-23 — O Qwen2.5-7B dividido entre 01 e 02 pelo Ray (*pipeline parallel* 2) rende 22-25 % menos que em 1 GPU; só o *KV cache* cresce (3,1×) {#ac-23}

**O que é.** Mesmo modelo, versão, *flags* e carga do `T-001` (B-001c), mudando só o arranjo: 2 GPUs (01 +
02) com `--pipeline-parallel-size 2 --distributed-executor-backend ray`. **Duas GPUs entregaram menos que
uma.** Com 1 usuário, 36,7 contra 47,0 *tok*/s, e o tempo por *token* foi de 20,3 para 26,6 ms: +6,3 ms,
~25 vezes o RTT entre os nós (0,247 ms). Com 32 usuários, 510,6 contra 680,4 *tok*/s; o TTFT ficou igual
(p50 1,10 × 1,09 s). As GPUs passaram parte do tempo paradas: com 32 usuários, uso médio de 60 % em 01 e
81 % em 02, a 135 e 156 W, contra ~250 W da GPU sozinha. O ganho é de memória: cada GPU guarda metade dos
pesos (7,13 GiB), e o *KV cache* sobe de 246.016 para **762.928 *tokens*** (93 conversas de 8.192 *tokens*,
contra 30). Explicação `[hipótese]`: cada passo atravessa as duas etapas em sequência, e o custo é da
coordenação (Ray Compiled Graph, sincronização das etapas) e do desequilíbrio entre elas (a última faz a
projeção para o vocabulário e a amostragem), não do cabo. A GPU de 02, a última etapa, foi a mais ocupada.

**Evidência.** [B-004-ray-pp2-qwen25-7b-sabdiia01-2026-10-29-1039.log](logs-analysis/B-004-ray-pp2-qwen25-7b-sabdiia01-2026-10-29-1039.log),
amostras em [testes/2026-10-29-1113-…/gpu-amostras.csv](logs-analysis/testes/2026-10-29-1113-Qwen_Qwen2.5-7B-Instruct/gpu-amostras.csv):

```
 2.0/2.0 GPU (2.0 used of 2.0 reserved in placement groups)
(RayWorkerWrapper pid=436, ip=192.168.50.152) ... Model loading took 7.13 GiB memory and 9.469487 seconds
GPU KV cache size: 762,928 tokens
Maximum concurrency for 8,192 tokens per request: 93.13x
| T-xxx | 1 | 12 | 0 | 36.7 | 38 | 189 / 199 | 26.6 / 27.6 | ...
| T-xxx | 32 | 512 | 0 | 510.6 | 17 | 1100 / 3316 | 59.1 / 66.6 | ...
```

**Regra prática.** Modelo que cabe em 32 GB: réplicas de 1 GPU (D-04), nunca dividido entre nós. *Pipeline
parallel* entre nós só para **capacidade** (modelo maior que 32 GB, ou contexto × concorrência que não cabe
numa GPU), contando perder ~25 % de vazão `[extrapolado do 7B]`. Para subir: [runbook](runbooks/teste-ray-pp2-qwen25-7b.md)
(`ray[cgraph,default]==2.48.0` e `cupy-cuda12x==13.6.0` instalados ao iniciar, `VLLM_HOST_IP` por *pod*,
`NCCL_SOCKET_IFNAME`/`GLOO_SOCKET_IFNAME` = `bond0.500`, `hostNetwork`).

**Validade.** 2026-10-29; `v0.19.1`, Ray `2.48.0`, `Qwen/Qwen2.5-7B-Instruct` FP16, `sabdiia01` + `sabdiia02`
(MTU 1500, `bond0` de 1 GbE); uma rodada por nível; gerador no *head*, dividindo a CPU com o Ray e o vLLM,
como no `T-001`. **Não testado:** se os *CUDA graphs* foram capturados (o log do arranque se perdeu, §9; o
comando não tem `--enforce-eager`); 2 réplicas medidas (os ~1.360 *tok*/s são cálculo); um modelo que
precise das 2 GPUs; `sabdiia03` (MTU 9000).

### AC-22 — O gpt-oss não roda no vLLM na V100S, com ou sem divisão entre nós: o MXFP4 exige *compute capability* 8.0 {#ac-22}

**O que é.** Os dois gpt-oss são MoE com os *weights* de MoE em MXFP4 [F-028]. Na `v0.19.1`, o método
MXFP4 declara capacidade mínima 80 [F-029], e a V100S é 70 (AC-04): o vLLM recusa o modelo
`[inferência pelo código; não executado]`. Dividir entre nós não muda isso, e o 120b nem caberia: o
*model card* fala de uma GPU de 80 GB, contra 57,6 GB úteis em 2 V100S (PD-31). No outro servidor, o
Ollama rodou o 120b com 2 V100S e ainda ~4 % na CPU (PD-21): o llama.cpp tem *kernels* próprios para esse
formato, o vLLM não. **A velocidade do gpt-oss vem de ser MoE** (5,1 B parâmetros ativos por *token* no
120b), não da divisão. E dividir não muda a resposta: o mesmo modelo dividido responde igual ao inteiro.
A qualidade vem do modelo escolhido.

**Evidência.** [F-029], [F-028]:

```
    def get_min_capability(cls) -> int:
        return 80
"117B parameters with 5.1B active parameters" ... "on a single 80GB GPU"
"21B parameters with 3.6B active parameters" ... "within 16GB of memory"
```

**Regra prática.** Para o perfil do gpt-oss (MoE, poucos parâmetros ativos) no vLLM desta GPU, o
candidato é um MoE com *quantization* que tem *kernel* em `sm_70`, inteiro numa V100S e com uma réplica por
nó: `Qwen/Qwen3-30B-A3B-GPTQ-Int4` (PD-19, com o cuidado do AC-15). O próprio gpt-oss só pelo Ollama (o 20b
cabe numa GPU, PD-21). A comparação de qualidade se faz com as perguntas da aplicação (PD-25), não pelo
tamanho.

**Validade.** 2026-10-27, `v0.19.1`. Onde o mínimo é aplicado e se o *backend* de MoE (`oracle.mxfp4`) tem
caminho para `sm_70`: `[não verificado]`. Fecha-se de vez com um arranque (falha esperada em segundos).

### AC-21 — Entre dois nós, *tensor parallel* sai mais lento que 1 GPU só pela rede; *pipeline parallel* também perde (medido: −22 a −25 %, AC-23) {#ac-21}

**O que é.** Com *tensor parallel*, o vLLM `v0.19.1` faz **2 *all-reduce* por camada** (saída da atenção e
do MLP) a cada passo de *decode* [F-027]. No `Qwen/Qwen2.5-7B-Instruct` (28 camadas, `hidden_size`
3584, [F-026]) são 56 por passo, cada um esperando ao menos uma ida e volta na rede. Com o RTT medido
entre 01 e 02 (0,247 ms), **só a espera soma ≥ 13,8 ms por *token***. Uma GPU sozinha gasta 20,3 ms por
*token* com 1 usuário (B-001c). Mesmo que cada GPU fizesse metade do trabalho em ~10 ms `[hipótese
otimista]`, o total (≥ 23,8 ms) já supera a GPU sozinha. Com 32 usuários, cada *all-reduce* leva 229 KB
(3584 × 32 × 2 *bytes*), 1,8-2,3 ms a 98-125 MB/s (AC-08): **a rede limita a vazão a ≤ 245-310 *tok*/s**,
contra 680 de uma GPU e ~1360 de duas réplicas `[cálculo; 2× é hipótese]`. *Pipeline parallel* manda
pela rede só uma passagem por passo, na fronteira entre as metades (~2,6 ms em 32 usuários) `[cálculo]`.
Essa conta previa ~5 % de custo e **errou**: medido, o *pipeline parallel* 2 perde 22-25 % de vazão e
acrescenta 6,3 ms por *token* (AC-23). A transferência é pequena; o custo está em coordenar as etapas. Não
acelera nada; serve só para juntar 64 GB para um modelo que não cabe em 32.

**Evidência.** [rtt-sabdiia01-02-2026-10-27-1446.log](logs-analysis/rtt-sabdiia01-02-2026-10-27-1446.log);
código [F-027]; configuração [F-026]:

```
100 packets transmitted, 100 received, 0% packet loss, time 20586ms
rtt min/avg/max/mdev = 0.177/0.247/0.340/0.032 ms
if self.reduce_results and self.tp_size > 1:
    output = tensor_model_parallel_all_reduce(output_parallel)
```

**Regra prática.** Não divida modelo entre nós com *tensor parallel* nesta rede. Para um modelo de 33-57 GB
que não caiba numa V100S, o arranjo entre nós a testar é `--pipeline-parallel-size 2` (PD-31), e ele
compete com 2 GPUs no mesmo nó (PD-22) e com *quantization*/MoE numa GPU (PD-19). Para vazão com um modelo
que cabe em 32 GB: réplicas independentes (AC-01).

**Validade.** 2026-10-27; `v0.19.1`, Qwen2. O RTT é de ICMP, um piso: o NCCL sobre TCP acrescenta pilha e
cópias `[não medido]`. Vale para modelos com o mesmo padrão de 2 *all-reduce* por camada. *Tensor parallel*
entre nós segue `[não executado]`; *pipeline parallel* 2 entre 01 e 02 foi executado em 2026-10-29 (AC-23).

### AC-19 — O Ray do administrador rodava no *host*, invisível ao Kubernetes; desde 2026-10-28 roda em *pods* que reservam as 3 GPUs, com a produção desligada {#ac-19}

**O que é.** O projeto `llm_lhama_prototype` do administrador sobe um *cluster* Ray com *head* em
`sabdiia01` e *worker* em `sabdiia02`, num *venv* Python 3.9 em `/home/utec/llm_lhama_prototype/venv`,
como `root`. Os contêineres Docker do projeto (`ray-head-node`, `ray-worker-node`) estão parados com
`Exited (1)`. Como a GPU não passa pelo *device plugin*, o Kubernetes continua anunciando `0 0` nos dois
nós e pode agendar um *pod* com `nvidia.com/gpu: 1` numa GPU que já tem 8 GB ocupados. Na hora da coleta,
nenhum dos dois servia nada: 0 % de uso e nada escutando na porta 8000. O padrão dos processos indica
**um modelo dividido entre as duas GPUs** (*tensor* ou *pipeline parallel*, executor Ray do vLLM), e não
réplicas independentes `[inferência]`. Indícios: `RayWorkerWrapper` é o *worker* do executor distribuído
do vLLM, o `python3` comum que segura a GPU em 01 é o padrão do motor V0, e 8.162 MiB por GPU batem com
metade dos ~15 GiB do Llama-3.1-8B FP16 `[cálculo; modelo não confirmado]`. Os scripts versionados não
rodam como estão (`deploy.py` tem `arg_utilss` e `num_replcas`, e pede 3 réplicas com `tensor_parallel_size=1`),
então o que roda não é o `deploy.py` do repositório `[hipótese]`. O painel do Ray (`0.0.0.0:8265`) e o GCS
(`*:6379`) ficam abertos na rede, sem autenticação `[não verificado na versão em uso]`, num nó `control-plane`.

**Evidência.** [01](logs-analysis/ray-docker-inventario-sabdiia01-2026-10-27-1214.log),
[02](logs-analysis/ray-docker-inventario-sabdiia02-2026-10-27-1218.log):

```
sabdiia01  577807 root 03:44 /home/utec/llm_lhama_prototype/venv/.../ray/gcs/gcs_server --log_dir=/tmp/ray/session_2026-10-27_12-10-38_728215_577731/logs
           LISTEN 0.0.0.0:8265 (python3)    LISTEN *:6379 (gcs_server)
           579011, python3, 8162 MiB        nvidia.com/gpu     0           0
           ray-head-node   llm_lhama_prototype-ray-head   Exited (1) 41 minutes ago
sabdiia02  522743 root 01:03 .../ray/raylet/raylet --raylet_socket_name=/tmp/ray/session_2026-10-27_12-10-38_728215_577731/sockets/raylet.1
           523371, ray::RayWorkerWrapper.execute_method, 8162 MiB      nvidia.com/gpu     0           0
```

**Regra prática.** Antes de qualquer experimento ou medição, uma GPU só conta como livre se passar nas
duas perguntas de "Qual GPU está livre?" ([COMANDOS.md](COMANDOS.md)): `0 0` no Kubernetes **e**
`nvidia-smi --query-compute-apps` vazio. Não use `sabdiia01` nem `sabdiia02` enquanto o Ray estiver no ar
(D-02 suspensa). O paralelismo que o estudo recomenda continua o de AC-01: réplicas de 1 GPU por nó.
Dividir um 8B, que cabe numa V100S, entre dois nós em 1 GbE (AC-08) só acrescenta tráfego de rede por
*token* `[hipótese: não medido]`.

**Às 14:20 o quadro era outro** ([01](logs-analysis/ray-pd29-pd30-sabdiia01-2026-10-27-1420.log),
[02](logs-analysis/ray-pd29-pd30-sabdiia02-2026-10-27-1422.log)): as duas GPUs estavam sem processo, o
Ray tinha só o *head* em 01 (`1 node`, `0.0/1.0 GPU`), nenhuma aplicação Serve, e nada rodava em 02. O
*venv* tem **vLLM `0.5.4`**, Ray `2.38.0` e torch `2.4.0+cu121`; o `requirements.txt` pede `0.6.2`. Os
`.py` do servidor têm o mesmo *hash* dos versionados, inclusive o `deploy.py` com erros: o que ocupava as
GPUs às 12:14 não foi o `deploy.py` pelo Serve `[confirmado]`, e o que foi continua sem registro. **O Ray
liga e desliga sem aviso:** a GPU que está livre agora pode não estar daqui a pouco.

**Atualização 2026-10-28: o Ray foi para dentro do Kubernetes e ocupa as 3 GPUs; a produção foi
desligada.** Às 15:11, `vllms` tinha `ray-head` (01), `ray-worker-2` (02) e `ray-worker-3` (03), três
*Deployments* simples (não KubeRay) com `vllm/vllm-openai:v0.5.4`, **cada um pedindo `nvidia.com/gpu: 1`**, todos
`1/1`. O Kubernetes passa a ver o uso: `nvidia.com/gpu 1 1` nos 3 nós, nenhuma GPU livre para o estudo. O
`vllm-deepseek-33b` e o `vllm-llama31-8b` estão **escalados a `0/0`, não apagados**. O `Service`
`LoadBalancer` `192.168.50.160:8001` continua, mas sem *pod*: a API de produção não responde `[inferência:
seletor sem pod; não testado]`. Os *Deployments* `ray-worker-*` das 15:03 substituíram o `ray-worker` único
das 14:50, que caía em `BackOff`; a causa daquelas quedas não ficou registrada
([log](logs-analysis/vllms-ray-k8s-sabdiia01-2026-10-28-1511.log)):

```
deployment.apps/ray-worker-3        1/1   ...  vllm/vllm-openai:v0.5.4
deployment.apps/vllm-deepseek-33b   0/0   ...  vllm/vllm-openai:v0.6.4
service/vllm-deepseek-33b   LoadBalancer   10.102.231.75   192.168.50.160   8001:30191/TCP
ray-worker-3-7cfd96f894-ckb8n   sabdiia03   1     vllm/vllm-openai:v0.5.4
  nvidia.com/gpu     1           1          (sabdiia01, 02 e 03)
587107, python3, 5664 MiB                   (GPU de sabdiia01, no host)
```

**O que roda (2026-10-28 15:22):** `meta-llama/Meta-Llama-3.1-8B-Instruct` com **`--pipeline-parallel-size 3
--tensor-parallel-size 1`** e `--distributed-executor-backend ray`, isto é, **um 8B, que cabe numa V100S,
dividido em 3 pedaços, um por nó**. Mais: `--dtype half --enforce-eager --gpu-memory-utilization 0.98
--max-model-len 4096 --max-num-seqs 16 --enable-chunked-prefill=False`. Detalhes que pesam:

- O servidor do vLLM **não está no manifesto**: os *Deployments* só rodam `ray start ... --block`, e o
  `api_server` foi iniciado à mão dentro do *head* (`kubectl exec` `[inferência]`). Se o *pod* reiniciar, o
  modelo não volta sozinho, e o Kubernetes não sabe se a API está de pé.
- `hostNetwork: true`: a API (`:8000`) e o painel do Ray (`:8265`) ficam no IP do nó, `192.168.50.151`, sem
  `Service` e sem autenticação. A rede entre os pedaços é a do nó, `bond0` (`--node-ip-address 192.168.50.x`);
  os valores de `NCCL_SOCKET_IFNAME`/`GLOO_SOCKET_IFNAME` não foram lidos.
- **Não é Ray Serve**: `serve status` falha com `No module named 'grpc'` dentro da imagem.
- GPUs: 26.026 / 30.928 / 25.024 MiB com 0 % de uso (ocioso na coleta). A maior parte é *KV cache*, por causa
  do `0.98`; os *weights* do 8B em FP16 são ~15 GiB no total `[cálculo]`.
- Volume do cache: PVC `hf-cache-pvc` (o AC-03 registra `hf-cache`; se é o mesmo, `[não verificado]`).

```
438  13:54 python3 -m vllm.entrypoints.openai.api_server --model meta-llama/Meta-Llama-3.1-8B-Instruct
     --pipeline-parallel-size 3 --tensor-parallel-size 1 --distributed-executor-backend ray --dtype half ...
command: ["/bin/bash","-c","ray start --head --node-ip-address=192.168.50.151 --port=6379 --dashboard-host=0.0.0.0 --num-gpus=1 --block"]
 3.0/3.0 GPU (3.0 used of 3.0 reserved in placement groups)
ray-head: 26026 MiB, 0 %    ray-worker-2: 30928 MiB, 0 %    ray-worker-3: 25024 MiB, 0 %
```

([log](logs-analysis/ray-k8s-modelo-sabdiia01-2026-10-28-1522.log).) Pelo AC-21, dividir em camadas um modelo
que cabe numa GPU não deixa uma resposta mais rápida e ocupa 3 GPUs para o trabalho de uma; três réplicas
independentes do mesmo 8B atenderiam ~3× mais requisições simultâneas `[hipótese, não medido aqui]`. Com
`--enforce-eager`, qualquer número medido nessa configuração é piso (CLAUDE.md).

**16:51: o servidor caiu e ninguém percebeu.** Os três *pods* seguiam `Running` havia 108 min com 0
reinícios, mas a porta 8000 recusava conexão, não havia `api_server` no *head* e as 3 GPUs estavam com
**0 MiB**. Só o GCS (`:6379`) escutava; o painel (`:8265`) também não. As GPUs continuam reservadas no
Kubernetes (`nvidia.com/gpu: 1` por *pod*) sem servir nada. É a fragilidade prevista acima: o servidor está
fora do manifesto, então nem o Kubernetes nem uma *probe* veem a queda. Por que caiu (encerrado pelo
administrador, morto com a sessão do `kubectl exec`, ou erro): `[não verificado]`
([log](logs-analysis/api-ray-diagnostico-sabdiia01-2026-10-28-1651.log)):

```
curl: (7) Failed to connect to 192.168.50.151 port 8000: Connection refused
LISTEN 0  4096  *:6379  *:*  users:(("gcs_server",pid=583733,fd=19))
ray-head-545cc769b9-7sjvc   1/1   Running   0   108m   192.168.50.151   sabdiia01
ray-head: 0 MiB, 0 %    ray-worker-2: 0 MiB, 0 %    ray-worker-3: 0 MiB, 0 %
```

**O repositório do administrador confirma o mecanismo (commit `45efe37`, 2026-10-28 15:48, `k8s/`).** O
`k8s/README.txt` sobe o servidor com `kubectl exec -it pod/ray-head-... -- python3 -m
vllm.entrypoints.openai.api_server ...`: o processo é filho de uma sessão interativa e morre quando ela fecha
`[hipótese forte para a queda das 16:51]`. O `02-ray-cluster.yaml` fixa cada *pod* com `nodeName`, usa
`hostNetwork: true` e `NCCL_SOCKET_IFNAME`/`GLOO_SOCKET_IFNAME` = `bond0.500` (a rede de 1 GbE com IPv4). Se a
subida das 17:10 usou outra interface, por exemplo a `bond1.20` sem endereço, a mudança não está no
repositório `[não verificado]`. **O `01-fundacao.yaml` põe um *token* real do Hugging Face num `ConfigMap`**
(`envFrom` nos 3 *pods*), versionado e enviado ao remoto: qualquer um que leia o repositório ou os
`ConfigMaps` de `vllms` o vê. O *token* deve ser revogado no Hugging Face e passar a `Secret` criado fora do
repositório (CLAUDE.md, "Segredos").

**Regra prática para o MVP, qualquer que seja o arranjo:** o comando que serve o modelo vai no manifesto
(`command`/`args` do contêiner), com `readinessProbe`/`livenessProbe` em `/health`, para o Kubernetes
reiniciar o que cair e tirar do `Service` o que não responde. Proposta entregue ao administrador para o
arranjo do Ray, já na `v0.19.1`: [configs/proposta-ray-cluster-pp3.yaml](configs/proposta-ray-cluster-pp3.yaml)
`[não executado]`. A `v0.19.1` **não traz Ray na imagem** e o executor Ray dela exige `ray >= 2.43.0` com
Compiled Graph [F-034]: subir o arranjo na versão do estudo custa instalar o Ray em cada contêiner.

**Validade.** 2026-10-27, 12:14-14:22; atualização 2026-10-28 15:11, 15:22 e 16:51. Modelo e grau de paralelismo do que rodou às 12:14: `[não
verificado]` (PD-29). Não se sabe desde quando o Ray usa as GPUs. A B-001d (2026-10-23) não gravou
`--query-compute-apps`, então a exclusividade da GPU naquela medição também não está provada.

### AC-20 — `/` encheu (100 %) em `sabdiia01` e `sabdiia02`, o *kubelet* expulsou *pods* e a `v0.19.1` sumiu de `sabdiia01` {#ac-20}

**O que é.** Às 12:14, `/` (70 G) estava cheio em 01 e 02, com imagens e contêineres Docker do projeto Ray
somados ao containerd (AC-09). O *kubelet* expulsou o `speaker` do MetalLB (em 01 e 02, o que anuncia os IPs
de LoadBalancer, inclusive o da produção, AC-06) e o `node-exporter`. A condição `DiskPressure` voltou a
`False` às 12:40 (01) e 12:41 (02), o horário da limpeza, o que confirma a pressão de disco antes dela
`[inferência pelo lastTransitionTime; o motivo das expulsões sumiu com os pods]`. Às 14:20, `/` estava em
46 % (01) e 70 % (02), o `data-root` do Docker era `/home/utec/docker_data` (se foi movido na limpeza ou
já estava lá: `[não verificado]`), os três `speaker` e o deepseek estavam `Running` em produção, e **nenhum
nó tinha mais imagem `vllm-openai`**: a `v0.19.1` de 01, sem uso desde a B-001d, foi apagada (pelo GC do
*kubelet* ou na limpeza). O `etcd` dos nós `control-plane` grava em `/` (`/var/lib/etcd`, 490 M em 01): o
disco cheio atinge o *cluster* inteiro, não só os *pods* do nó.

**Evidência.** [01](logs-analysis/ray-docker-inventario-sabdiia01-2026-10-27-1214.log),
[02](logs-analysis/ray-docker-inventario-sabdiia02-2026-10-27-1218.log):

```
sabdiia01  /dev/mapper/ol-root   70G   70G  5.9M 100% /
           Images 3 2 18.39GB 15.18kB (0%)    Containers 2 0 16.35GB 16.35GB (100%)
           metallb-system speaker-nls5d  0/1 Evicted 0 12m
           monitoring monitoring-prometheus-node-exporter-snzst  0/1 Evicted 0 12m
sabdiia02  /dev/mapper/ol-root   70G   70G  1.1M 100% /
           Images 1 1 17.82GB 0B (0%)        Containers 1 0 6.497GB 6.497GB (100%)
           metallb-system speaker-ckzd4  0/1 Evicted 0 88s
```

Às 14:20 ([01](logs-analysis/ray-pd29-pd30-sabdiia01-2026-10-27-1420.log),
[02](logs-analysis/ray-pd29-pd30-sabdiia02-2026-10-27-1422.log)):

```
sabdiia01  DiskPressure False ... Tue, 27 Oct 2026 12:40:47 -0300   KubeletHasNoDiskPressure
           /dev/mapper/ol-root   70G   32G   39G  46% /     15G /var/lib/containerd   490M /var/lib/etcd
           /home/utec/docker_data          nenhuma imagem vllm-openai
sabdiia02  /dev/mapper/ol-root   70G   49G   22G  70% /     31G /var/lib/containerd   426M /var/lib/etcd
pod/vllm-deepseek-33b-67754f4465-fwv4p   1/1   Running   0   26h   10.244.50.184   sabdiia03
```

**Regra prática.** Docker em nó do *cluster* fica com `data-root` em `/home`, nunca em `/`. **A `v0.19.1`
não cabe de volta em `/` com segurança:** ~30 G (AC-09) sobre os 39 G livres de 01 deixariam 9 G, abaixo
dos 10,5 G (15 %) em que o *kubelet* entra em `DiskPressure` `[cálculo]`; em 02 (22 G livres) não cabe.
Voltar a testar exigia primeiro mover o *root* do containerd para `/home` (PD-15). **Superado em
2026-10-28:** `/` passou a 631 G em 01 e 02 (AC-09).

**Validade.** 2026-10-27, 12:14-14:22. O que exatamente encheu `/` e o que a limpeza removeu: `[não
verificado]` (os contêineres Docker parados somavam 22,85 G recuperáveis às 12:14).

### AC-17 — A V100S de `sabdiia01` estrangulava por temperatura (~400 MHz em 2 min); depois do ajuste de refrigeração, sustenta 250 W a 72 °C e rende 4 a 6 vezes mais {#ac-17}

**O que é.** A GPU de `sabdiia01` fica a 72 °C parada, só com o modelo carregado. Sob carga ela chega a
82 °C, e o *driver* reduz o *clock* para segurar a temperatura (`SW Thermal Slowdown: Active`). Segundo a
NVIDIA, esse motivo significa que o algoritmo de controle térmico está baixando o *clock* abaixo do
solicitado porque a temperatura passou do limite "Max" ([F-022]). Que isso derruba a vazão do vLLM é a
nossa medição, não a documentação. Em 2 min o
*clock* do SM vai de 1560 para ~400 MHz, um quarto do máximo de 1597, e a potência cai de 250 para 74 W.
O vLLM acompanha: requisições idênticas passaram de 5,6 s para 21,8 s. A primeira, ainda com *clock*
alto, saiu a ~45 *tok*/s num 7B em FP16, que é a ordem de grandeza desta GPU sem estrangulamento
`[inferência]`. A cota de CPU do *pod* **não** é a causa: o contador `nr_throttled` subiu de 12 para 13
na rodada inteira. **A B-001 mediu a GPU superaquecida, não o motor.** A causa provável é a ventilação do
servidor para a placa: a V100S PCIe não tem ventoinha própria e depende do fluxo de ar do chassi
`[hipótese]`. Em 2026-09-29, paradas, as outras V100S estavam a 32-34 °C (`sabdiia02`) e 61 °C
(`sabdiia03`, com o deepseek carregado).

**Evidência.** [B-001b-diagnostico-sabdiia01-2026-10-14-1832.log](logs-analysis/B-001b-diagnostico-sabdiia01-2026-10-14-1832.log),
[gpu-amostras-b001b.csv](logs-analysis/gpu-amostras-b001b.csv), [gpu-performance-b001b.txt](logs-analysis/gpu-performance-b001b.txt):

```
temperature.gpu, power.draw [W], clocks.current.sm [MHz], clocks.max.sm [MHz], utilization.gpu [%]
72, 55.48 W, 1245 MHz, 1597 MHz, 0 %        (parada)
79, 249.54 W, 1560 MHz, 1597 MHz, 100 %     (18:32:31, início da carga)
82, 74.08 W, 405 MHz, 1597 MHz, 100 %       (18:34:48, 2 min depois)
    Clocks Event Reasons ... SW Thermal Slowdown : Active      (nas 3 fotos)
nr_throttled 12 -> 13     throttled_usec 10788904 -> 11937768
```

Limites de temperatura, **iguais nos 3 nós** ([sabdiia01](logs-analysis/termico-sabdiia01-2026-10-15-1417.log),
[02](logs-analysis/termico-sabdiia02-2026-10-15-1418.log), [03](logs-analysis/termico-sabdiia03-2026-10-15-1419.log)):
`GPU Max Operating Temp : 83 C` (onde começa o `SW Thermal Slowdown`, F-022), `GPU Slowdown Temp : 87 C`,
`GPU Shutdown Temp : 90 C`. O patamar de 82 °C da B-001b é o *driver* segurando a GPU abaixo dos 83 °C.
Paradas em 2026-10-15: `sabdiia01` 67 °C / 52,7 W com o Qwen2.5-7B carregado; `sabdiia03` 60 °C / 44,3 W
com o deepseek; `sabdiia02` 31 °C / 27,2 W, sem modelo. Esses números não separam "refrigeração pior" de
"mais calor gerado", e o comportamento de `sabdiia03` sob carga `[não medido]`.

**Depois do ajuste (2026-10-22).** O administrador revisou a refrigeração de `sabdiia01` (o que mudou:
`[não verificado]`). Reteste B-001c, mesmo *pod*, mesmo modelo: parada, a GPU foi de 67-72 °C para
**31 °C**; com 3 min 25 s de carga contínua a 240-250 W (concorrência 32), chegou a **72 °C** e não
estrangulou (contador `SW Thermal Slowdown` em 0 µs). O *clock* fica em 1500-1597 MHz, com quedas
breves a ~1260 MHz a cada ~12 s. Elas **não são estrangulamento**: vêm com potência menor (média de
225 W contra 240 W), o contador de `SW Power Capping` cresceu só 0,15 s na rodada inteira, e o período
coincide com as levas da carga sintética, em que as 32 requisições de tamanho igual terminam juntas
`[hipótese: a GPU espera a leva seguinte]`.

```
                         antes (B-001b/B-001, 10-14)    depois (B-001c, 10-22)
concorrência 1           10,0 tok/s · TPOT p50 93 ms     47,0 tok/s · TPOT p50 20,3 ms · 5,3 s/requisição
concorrência 32          113,7 tok/s · TTFT p50 8,96 s   680,4 tok/s · TTFT p50 1,09 s · TPOT p50 42,9 ms
temperatura máx. / clock 82 °C / ~400 MHz                72 °C / mín. 1245, médio 1474 MHz
SW Thermal Slowdown      Active (3 de 3 fotos)           0 us no contador, 0 de 3 fotos
```

Na concorrência 32, as cargas não são idênticas (512 requisições com a semente 102, contra 256 com a
semente 32): ordem de grandeza. A comparação formal é a B-002 (Bloco F).
Log: [B-001c-reteste-termico-sabdiia01-2026-10-22-1552.log](logs-analysis/B-001c-reteste-termico-sabdiia01-2026-10-22-1552.log).

**Depois da 2ª intervenção, na sala (2026-10-23).** Mesma carga, mesmo *pod* (rodando havia 24 h), B-001d:
**nada mudou na GPU**. A curva de temperatura coincide com a de ontem amostra a amostra (31 °C parada,
43 °C aos 20 s, 64 °C aos 2 min, 72 °C no fim), com a mesma potência média (235,5 contra 235,9 W) e o
contador `SW Thermal Slowdown` em 0 µs. Vazão: 48,2 e 680,5 *tok*/s (ontem, 47,0 e 680,4). Duas
consequências: a temperatura da GPU sob carga não depende da sala nesta faixa `[hipótese: a V100S
PCIe é passiva e depende do fluxo de ar das ventoinhas do chassi, não verificado]`; e o
`vllm bench serve` repete a fase 2 com diferença de 0,01 % entre dias, então diferenças de alguns
por cento numa alavanca (PD-27) já são sinal, não ruído (uma repetição só).
Log: [B-001d-reteste-termico-sabdiia01-2026-10-23-1635.log](logs-analysis/B-001d-reteste-termico-sabdiia01-2026-10-23-1635.log).

**Regra prática.** Antes de qualquer medição, vigie `clocks.current.sm`, `temperature.gpu` e
`nvidia-smi -q -d PERFORMANCE` **durante a carga**. O critério é o **contador** `SW Thermal Slowdown`
(e `HW Thermal Slowdown`) parado durante a carga e a temperatura abaixo de 83 °C, não um piso de *clock*:
a V100S varia o *clock* com a carga mesmo sem estrangular. Medição com `SW Thermal Slowdown` ativo não
vale como número do motor. Ao avaliar 2 GPUs no mesmo nó (PD-22), conte com mais calor no chassi.

**Validade.** `sabdiia01`: estrangulamento em 2026-10-14 (3 min, concorrência 1); sem estrangulamento em
2026-10-22 (1 min a concorrência 1 + 3 min 25 s a concorrência 32), com a temperatura ainda subindo
devagar no fim (71 → 72 °C no último minuto); repetido igual em 2026-10-23 (B-001d), com 72 °C nos
últimos 40 s. Carga de 20 min ou mais: `[não medido]` (B-002).
`sabdiia02` e `sabdiia03` sob carga: `[não medido]`.

### AC-18 — Com o modelo em cache, a `v0.19.1` ainda precisa de rede para arrancar; com `HF_HUB_OFFLINE=1`, não {#ac-18}

**O que é.** Ao arrancar, a `v0.19.1` procura no Hugging Face um arquivo que o modelo não tem. Como ele
não existe, nunca entra no cache, e a busca vai ao Hub ([F-024]). Sem DNS, a consulta falha e o *pod*
cai em ~3 min, com o modelo inteiro em `/home`. Com `HF_HUB_OFFLINE=1`, o vLLM troca o nome do modelo
pelo caminho no cache e não consulta a rede ([F-025]). O log do motor passa a mostrar o caminho em
`model` e `served_model_name`, mas **a API continua anunciando o nome do Hub**: `/v1/models` devolveu
`Qwen/Qwen2.5-7B-Instruct`, e o `vllm bench serve` funcionou com esse nome (B-001c).

**Evidência.** [sem offline](logs-analysis/teste-concorrencia-arranque-sabdiia01-2026-10-22-1521.log),
[com offline](logs-analysis/teste-concorrencia-arranque-offline-sabdiia01-2026-10-22-1541.log):

```
ERROR [repo_utils.py:45] Error retrieving file list: [Errno -3] Temporary failure in name resolution
vllm-conc   0/1     Error    0          3m6s
---
INFO [arg_utils.py:665] HF_HUB_OFFLINE is True, replace model_id [Qwen/Qwen2.5-7B-Instruct] to model_path [/hf-cache/hub/models--Qwen--Qwen2.5-7B-Instruct/snapshots/a09a35458c702b33eeacc393d103063234e8bc28]
... served_model_name=/hf-cache/hub/models--Qwen--Qwen2.5-7B-Instruct/snapshots/a09a35458c702b33eeacc393d103063234e8bc28
### PARADA: pod Ready   em 2026-10-22 15:44:04
---
### nome do modelo servido (com HF_HUB_OFFLINE=1 é o caminho no cache): Qwen/Qwen2.5-7B-Instruct   (B-001c)
```

**Regra prática.** Em produção, baixe o modelo antes e suba com `HF_HUB_OFFLINE=1` (variável de
ambiente), para o arranque não depender de internet nem de DNS. O nome que os clientes usam não muda.
Para trocar de modelo, rode antes um arranque com rede, ou um `Job` que baixe o modelo para o cache.

**Validade.** `v0.19.1`, `sabdiia01`, 2026-10-22, `Qwen/Qwen2.5-7B-Instruct`. Modelo ausente do cache com
o modo *offline* ligado: `[não executado]` (deve falhar).

### AC-16 — Com bitsandbytes, o Qwen3.8-27B não ganha nada com concorrência: ~4 *tokens*/s no total, com 1 ou 8 requisições {#ac-16}

**O que é.** No *pod* da tentativa 2 (AC-14), sem reiniciar nada, foram disparadas 1, 4 e 8 requisições
simultâneas de 100 *tokens* com o raciocínio desligado. A vazão total **não sobe**: fica em ~4
*tokens*/s, e cada usuário passa a ver menos de 1 *token*/s. Isso derruba a principal vantagem do vLLM
sobre o Ollama, que é servir várias requisições no mesmo lote. A causa é `[hipótese]`: o bitsandbytes
pode ter um caminho rápido só para lote de 1 e descompactar os pesos inteiros quando o lote cresce.
Com uma requisição só e o raciocínio desligado, saíram 100 *tokens* em 18,7 s (5,35 *tokens*/s, contando
o tempo até o primeiro *token*). O raciocínio desliga por requisição com `chat_template_kwargs` e
`enable_thinking: false`: o *template* do modelo aceita, e a resposta veio sem `</think>`.

**Evidência.** [alavancas-qwen38-2026-10-14-1625.log](logs-analysis/alavancas-qwen38-2026-10-14-1625.log):

```
### N | tokens gerados | segundos | tokens/s total | tokens/s por usuário
1 | 100 | 18.7 | 5.35 | 5.35
4 | 400 | 145.6 | 2.75 | 0.69
8 | 800 | 210.1 | 3.81 | 0.48
Engine 000: ... Avg generation throughput: 4.0 tokens/s, Running: 8 reqs, Waiting: 0 reqs, GPU KV cache usage: 31.1%
vllm:num_preemptions_total ... 0.0
```

**Regra prática.** bitsandbytes no vLLM, nesta GPU, serve no máximo para **um usuário por vez**. Para
servir vários usuários, use um modelo que rode sem bitsandbytes (FP16 ou GPTQ Int8, AC-15). Para
desligar o raciocínio de modelos Qwen3.x: `"chat_template_kwargs": {"enable_thinking": false}` no corpo
da requisição.

**Validade.** `v0.19.1`, `--enforce-eager`, `sabdiia01`, 2026-10-14. Uma rodada por nível de
concorrência, sem repetição, *prompts* curtos: ordem de grandeza, não medição. Com *CUDA graphs* (R1):
`[não executado]`.

### AC-15 — Na V100S, GPTQ de 4 bits cai num *kernel* que a própria `v0.19.1` chama de defeituoso {#ac-15}

**O que é.** O caminho rápido de GPTQ no vLLM é o Marlin, que exige *compute capability* ≥ 7.5. A V100S é
7.0, então GPTQ cai no *kernel* antigo `gptq_gemm`. Para 4 bits, a `v0.19.1` emite um aviso dizendo que
esse *kernel* "é defeituoso". O texto não diz qual é o defeito; pode ser lentidão ou resposta errada
`[não verificado]`. GPTQ de **8 bits** não dispara o aviso. Em modelos MoE, as camadas de especialistas
usam outro caminho (`MoeWNA16`, CC ≥ 7.0), mas as demais camadas continuam no `gptq_gemm`. Dois efeitos
para a escolha de modelo: (1) o deepseek em produção, GPTQ de 4 bits na `v0.6.4`, nunca teve a
qualidade das respostas conferida; (2) o `Qwen/Qwen3.5-27B-GPTQ-Int4`, da família do modelo pedido,
deixa 10,67 bilhões de parâmetros em BF16, ~21 GB, e com a parte de 4 bits passa de ~29 GB de pesos:
**não cabe** na V100S `[cálculo]`.

**Evidência.** [F-015], [F-016], [F-017] em [FONTES.md](FONTES.md):

```
gptq.py, weight_bits == 4:  "Currently, the 4-bit gptq_gemm kernel for GPTQ is buggy. Please switch to gptq_marlin."
GPTQMarlinConfig.get_min_capability -> 75
MoeWNA16Config.get_min_capability   -> 70
Qwen3.5-27B-GPTQ-Int4: I32 17,112,760,320 · BF16 10,668,659,184
```

**Regra prática.** Na V100S, prefira GPTQ **Int8** ou modelo em FP16. Se testar GPTQ Int4, confira a
resposta e não só a velocidade: uma pergunta de resposta conhecida, com `temperature` 0. Antes de
escolher um GPTQ, some os parâmetros não quantizados do `safetensors` da página do modelo.

**Validade.** Leitura de código e da API do Hugging Face em 2026-10-13, **nada executado**. O que o
aviso quer dizer na prática não foi medido.

### AC-03 — O cache de modelos é um PVC NFS compartilhado por todos os *pods* do vLLM {#ac-03}

**O que é.** `vllms/hf-cache` (200 Gi, RWX, NFS) é montado em `/root/.cache/huggingface` pelos dois
*deployments* do vLLM. Um modelo baixado uma vez serve a qualquer nó. O preço é ler *weights* pela rede
a cada arranque (PD-04). Os tamanhos dos PVs não são cotas: todos ficam na mesma exportação NFS de
500 G, que tem 17 G usados no total (Bloco 2). O PV de 200 Gi em `Released` (antigo `default/hf-cache`)
não prende espaço relevante.

**Evidência.**

```
pvc-6687e544-...   200Gi   RWX   Retain   Bound      vllms/hf-cache          nfs-storage
pvc-5ff9095f-...   200Gi   RWX   Retain   Released   default/hf-cache        nfs-storage
```

**Regra prática.** Reaproveite `vllms/hf-cache` nos testes para não baixar modelo de novo. Meça o tempo
de carregamento antes de decidir por cache local.

**Validade.** 2026-09-29. Banda de leitura do NFS: `[não medido]` (limites da rede em AC-08).

### AC-04 — GPU Tesla V100S-PCIE-32GB (`sm_70`), *driver* 580.173.02 / CUDA 13.0 no *host* {#ac-04}

**O que é.** Premissa "V100 32 GB" confirmada, com precisão: é a **V100S** PCIe. O *driver* é do
*host* (`gpu.deploy.driver=pre-installed`), não do Operator. O *driver* 580 anuncia CUDA 13.0: imagens
com CUDA até 13.0 rodam. O CUDA 13.0 **removeu a compilação para Volta** ([F-002]): software construído
com CUDA 13 não traz *kernels* `sm_70` (consequência para o vLLM em AC-11). Que a série 580 seja a última
de *driver* com Volta continua `[não verificado]`: a F-002 não fala de *driver*.

**Evidência.** *Labels* GFD, iguais nos 3 nós
([log](logs-analysis/inventario-vllms-2026-09-28.txt)):

```
nvidia.com/cuda.driver-version.full=580.173.02
nvidia.com/cuda.runtime-version.full=13.0
nvidia.com/gpu.compute.major=7
nvidia.com/gpu.compute.minor=0
nvidia.com/gpu.deploy.driver=pre-installed
nvidia.com/gpu.product=Tesla-V100S-PCIE-32GB
```

**Regra prática.** Antes de escolher a imagem do vLLM, confira **com que CUDA ela foi construída** e se
traz *kernels* `sm_70` (PD-03). Não atualize o *driver* dos nós sem conferir se a versão nova suporta
Volta.

**Validade.** 2026-09-29. CUDA 13 sem Volta: `[confirmado, F-002]`. Série 580 como última com Volta:
`[não verificado]`.

### AC-05 — vLLM `v0.6.4` + GPTQ serve um 33B numa V100S: XFormers, *kernel* GPTQ não-Marlin, 43.600 *tokens* de *KV cache* {#ac-05}

**O que é.** O `deepseek-coder-33B-instruct-GPTQ` em `float16`, com contexto de 8192, roda em
`sabdiia03`. Na V100S a `0.6.4` recusa FlashAttention-2 e usa **XFormers**, e avisa que o GPTQ "não
está totalmente otimizado", ou seja, usa o *kernel* GPTQ comum, não o Marlin `[hipótese: Marlin exige
sm_80]`. O modelo é publicado em BF16 e o vLLM converte para FP16 sozinho. Com
`--gpu-memory-utilization 0.90` sobram **2725 blocos × 16 = 43.600 *tokens*** de *KV cache* na GPU,
espaço para 5 sequências de 8192 *tokens*, contra as 4 que `--max-num-seqs 4` permite. A configuração é
conservadora: `--enforce-eager` desliga *CUDA graphs* e *prefix caching* está desligado (padrão da
`0.6.4`). É o piso conhecido, não o ótimo.

**Evidência.** [inventario-vllms-logs-2026-09-29.txt](logs-analysis/inventario-vllms-logs-2026-09-29.txt)
(arranque de 09-18, preservado no log da execução anterior, e `/metrics`):

```
WARNING 09-18 13:13:23 config.py:1865] Casting torch.bfloat16 to torch.float16.
WARNING 09-18 13:13:30 config.py:428] gptq quantization is not fully optimized yet. The speed can be slower than non-quantized models.
INFO 09-18 13:13:44 selector.py:261] Cannot use FlashAttention-2 backend for Volta and Turing GPUs.
INFO 09-18 13:13:44 selector.py:144] Using XFormers backend.
vllm:cache_config_info{block_size="16",...,enable_prefix_caching="False",gpu_memory_utilization="0.9",...,num_cpu_blocks="1057",num_gpu_blocks="2725",...}
```

No *host* ([sabdiia03](logs-analysis/inventario-no-sabdiia03-2026-09-29-1004.log)), o processo ocupa
**28.598 MiB** dos 32.768, abaixo do teto de 0,90 × 32.768 = 29.491 MiB:

```
|    0   N/A  N/A          838553      C   /usr/bin/python3                      28598MiB |
```

Observação única, **não é medição**: a única requisição registrada teve TTFT de 0,48 s e 157
*tokens* em 7,79 s de *decode*, ≈ 50 ms/*token* (n = 1, *eager*, carga desconhecida).

**Regra prática.** Em `sm_70`, conte com XFormers e com o *kernel* GPTQ comum. Dimensione
`--max-num-seqs` pelo *KV cache* do log (`num_gpu_blocks × block_size`), não por palpite. Aqui cabe mais
concorrência com pedidos curtos.

**Validade.** `v0.6.4`, `sabdiia03`, 2026-09-29. *Throughput* sob carga: `[não medido]`. Causa dos 18
reinícios iniciais: PD-11.

### AC-06 — A API do vLLM em produção está exposta por LoadBalancer sem autenticação {#ac-06}

**O que é.** O `Service` `vllm-deepseek-33b` é `LoadBalancer`, com IP `192.168.50.160:8001`
alocado pelo MetalLB do pool `pool-publico`, e o contêiner sobe **sem `--api-key`**. Quem alcança esse
IP usa o modelo. Se "publico" significa acessível de fora da rede interna: `[não verificado]`.

**Evidência.**

```
service/vllm-deepseek-33b   LoadBalancer   10.102.231.75   192.168.50.160   8001:30191/TCP
metallb.io/ip-allocated-from-pool: pool-publico
```

**Regra prática.** Nenhum *deployment* novo sobe como `LoadBalancer` sem `--api-key` ou autenticação na
borda (há um Kong no *cluster*). Nos testes, use `ClusterIP` e `kubectl port-forward`.

**Validade.** 2026-09-28. Alcance real do pool `pool-publico` e regras de *firewall*: `[não verificado]`.
Confirmado em 2026-09-29 que a API responde sem credencial a partir de `sabdiia03` (`/v1/models`,
`/metrics` no Bloco 1c).

### AC-07 — O `CrashLoopBackOff` da `v0.12.0` é `401` no Hugging Face, não incompatibilidade com Volta {#ac-07}

**O que é.** `vllm-llama31-8b` morre cerca de 20 s depois de subir, ao buscar o `config.json` de
`meta-llama/Llama-3.1-8B-Instruct`, um repositório *gated*. **O *token* do Secret `hf-secret` é
inválido**: até o `whoami` do Hugging Face o recusa (Bloco 1d). O deepseek só funciona porque o modelo
dele é público e já está no cache. Um *token* inválido pode barrar até *downloads* públicos, porque vai
no cabeçalho de toda requisição `[hipótese]`. O processo não
chega a iniciar a GPU, então **o caso não diz nada sobre a `v0.12.0` em `sm_70`**. Enquanto isso, a
GPU de `sabdiia01` ficou reservada por 7d14h e 2017 reinícios.

**Evidência.** [inventario-vllms-logs-2026-09-29.txt](logs-analysis/inventario-vllms-logs-2026-09-29.txt):

```
INFO 09-29 05:04:28 [api_server.py:1772] vLLM API server version 0.12.0
huggingface_hub.errors.GatedRepoError: 401 Client Error.
Cannot access gated repo for url https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct/resolve/main/config.json.
    Last State:     Terminated  Reason: Error  Exit Code: 1
      Started:      Tue, 29 Sep 2026 09:04:09 -0300   Finished: Tue, 29 Sep 2026 09:04:30 -0300
    Restart Count:  2017
```

[inventario-hf-token-2026-09-29-0931.log](logs-analysis/inventario-hf-token-2026-09-29-0931.log):

```
huggingface_hub.errors.HfHubHTTPError: 401 Client Error: Unauthorized for url: https://huggingface.co/api/whoami-v2
Invalid username or password.
```

**Regra prática.** Diante de `CrashLoopBackOff`, leia `kubectl logs --previous` antes de culpar a GPU ou
a versão. Antes de implantar, valide o *token* com o `whoami` do `huggingface_hub` (Bloco 1d do
runbook). Enquanto o `hf-secret` não for trocado, os testes novos usam modelo público e **não
injetam o `HF_TOKEN`**.

**Validade.** `v0.12.0`, 2026-09-29. A `v0.12.0` em `sm_70` continua `[não executado]` (PD-03).

### AC-08 — Entre dois nós a rede é 1 GbE, não importa quantas conexões; a porta a 100 Mbps de `sabdiia01` está fora do agregado {#ac-08}

**O que é.** Cada nó agrega 6 portas em `bond0` (802.3ad/LACP) com `Transmit Hash Policy: layer2`: a
porta de saída é escolhida pelo **endereço MAC de destino**. Todo o tráfego de um nó para um mesmo
destino sai por uma única porta de 1 Gbps (≈ 125 MB/s), **mesmo com várias conexões em paralelo**.
Consequências: (1) ler 17 G de *weights* do NFS leva pelo menos ~140 s `[cálculo, não medido]`, e
`nconnect` não ajudaria na saída; (2) *tensor parallel* entre nós fica fora de questão, e *pipeline
parallel* só serve para caber um modelo maior, não para acelerar (AC-21). Em `sabdiia01`, a porta `enp65s0f1` negociou 100 Mbps, mas o LACP a pôs num agregador à
parte (ID 1), e o agregador ativo é o 2: ela **não carrega dados**, só quadros de controle. O nó opera com
5 portas em vez de 6, sem conexão lenta. Placa e *switch* anunciam 1000baseT e não há erros nem quedas de
*link*: o padrão típico de **cabo com par defeituoso** `[hipótese]`.

**Evidência.** [rede-bond-sabdiia01-2026-10-02-1239.log](logs-analysis/rede-bond-sabdiia01-2026-10-02-1239.log):

```
Transmit Hash Policy: layer2 (0)
MII Status: up
	Aggregator ID: 2                      <- agregador ativo do bond
Slave Interface: enp65s0f0   Speed: 1000 Mbps   Aggregator ID: 2
Slave Interface: enp65s0f1   Speed: 100 Mbps    Aggregator ID: 1
	Advertised link modes:               ... 1000baseT/Full
	Link partner advertised link modes:  ... 1000baseT/Full
	Speed: 100Mb/s   Duplex: Full
enp65s0f1 RX: 1236959 packets, 1236959 mcast, 0 errors
```

Vazão medida de uma conexão `sabdiia01` → `sabdiia02`, com `dd | ssh` (2026-10-02, saída colada pelo
usuário, sem log em arquivo). São 786 Mbps: passou por porta de 1 Gbps, não pela de 100 Mbps. O `ssh`
cifra os dados, então o número é um piso para a rede, não o teto:

```
3145728000 bytes (3.1 GB, 2.9 GiB) copied, 31.9909 s, 98.3 MB/s
```

**Atualização 2026-10-28: o `bond1` de 40 G existe, mas os *pods* não passam por ele.** O administrador
criou `bond1` (4 × 10 GbE, 802.3ad, também `layer2`) só com a VLAN 302 e só endereços IPv6
`2801:80:f8c:302::/64`, a mesma rede do servidor NFS (`[2801:80:f8c:302::aa]`, §2). O IP do nó, a rota
*default* e o IP que o Calico usa para levar tráfego de *pod* entre nós continuam em `bond0.500`
(192.168.50.x, 1 GbE); as rotas de *pod* saem por `tunl0` para esses IPs. Logo: (1) o **NFS** deve ter
passado para o `bond1`, com teto de **10 Gbps por destino** por causa do `layer2`. A rota foi
confirmada em `sabdiia03` (`2801:80:f8c:302::aa dev bond1.302`); em 01 e 02, `[não verificado]`; (2) **entre *pods*,
a rede segue 1 GbE**, e o AC-21 vale como antes. **O RTT quase não muda na rede nova** (`sabdiia03` →
`sabdiia02`, 100 pacotes cada, 2026-10-28 14:52): **0,311 ms** pelo `bond1` contra **0,348 ms** pelo `bond0`
([log](logs-analysis/producao-rede-nova-sabdiia03-2026-10-28-1452.log)); de `sabdiia01` a `sabdiia02`
(15:00), **0,236 ms** contra **0,319 ms** ([log](logs-analysis/producao-rede-nova-sabdiia01-2026-10-28-1500.log)).
A mesma medida pelo `bond0` deu 0,247 ms em 2026-10-27: a variação entre dias é do tamanho do ganho. Mais banda não reduz a espera por
troca, que é o custo do *tensor parallel*. **MTU desigual:** em 03, `bond0.500` tem 9000 e o túnel do Calico
(`tunl0`, `cali*`) 8980; em 01 e 02, `bond0` tem 1500. Em 01, conferido: `bond0` 1500 e `tunl0` **1480**, contra 8980 em 03. *Pods* de 03 podem mandar a 01/02 pacotes maiores do
que eles aceitam `[hipótese; TCP negocia o tamanho, UDP grande e ICMP não]`: levar ao administrador.
Em `sabdiia03`, duas portas do `bond1` ficaram num agregador inativo (`speed=20000`, configuração do
*switch* `[hipótese]`) e o `bond0` tem MTU 9000 contra 1500 nos outros dois. Em `sabdiia01`, a porta a 100
Mbps continua fora do agregado. Evidência: [01](logs-analysis/estado-disco-rede-sabdiia01-2026-10-28-1419.log),
[02](logs-analysis/estado-disco-rede-sabdiia02-2026-10-28-1420.log),
[03](logs-analysis/estado-disco-rede-sabdiia03-2026-10-28-1421.log):

```
bond1.302@bond1  UP   2801:80:f8c:302:c8:1f:66fa:fe55/64          (sabdiia01; sem IPv4)
bond0.500@bond0  UP   192.168.50.151/24 ...
10.244.182.128/26 via 192.168.50.152 dev tunl0 proto bird onlink
sabdiia01   192.168.50.151/24                                     (CALICO_IPV4)
bond0 mtu=1500 speed=5000 / bond1 mtu=1500 speed=40000            (01)
bond0 mtu=9000 speed=6000 / bond1 mtu=1500 speed=20000            (03)
```

**Regra prática.** Descarte *tensor parallel* multinó enquanto a rede **dos *pods*** for 1 GbE; *pipeline parallel*
entre nós só para modelos que não cabem em 32 GB, depois de medido (AC-21, PD-31). Para arranque rápido, compare
NFS × cópia local em `/home` (AC-09, PD-04). A porta a 100 Mbps **não invalida medições em `sabdiia01`**;
trocar o cabo devolve a sexta porta (PD-13). Num *bond* LACP, confira `Aggregator ID` além de `Speed`.

**Validade.** 2026-10-02, `sabdiia01`. Vazão de saída medida uma vez, com `ssh` (n = 1). Política de
*hash* do *switch* (tráfego de entrada) e banda real do NFS: `[não medido]`. `Transmit Hash Policy` de 02 e 03: `[não verificado]`.

### AC-09 — `/` guarda as imagens e o `etcd`: era 70 G (apertado) e desde 2026-10-28 é 631 G nos 3 nós; `/home` caiu para 200 G {#ac-09}

**O que é.** O containerd guarda as imagens em `/var/lib/containerd`, dentro de `/` (70 G), que já está
61-72 % ocupado. A imagem `vllm/vllm-openai:v0.6.4` tem **5,62 GB** no registro, mas desempacotada
ocupa mais `[hipótese]`. `/var/lib/containerd` tem 20 G em `sabdiia03` (só a `v0.6.4` de vLLM) e 33 G em
`sabdiia01`, onde está também a `v0.12.0`. A diferença, **~13 G**, é a estimativa do custo em disco de
uma imagem nova do vLLM `[hipótese: 01 pode ter outras imagens]`. O *kubelet* dos 3 nós usa os
limiares padrão (`configz`, 2026-09-29): ao passar de **85 %** de `/`, apaga imagens **sem uso** até 80 %;
com menos de **15 % livre**, entra em *DiskPressure* e expulsa *pods*. Como imagens e sistema dividem o
mesmo `/` de 70 G, as duas coisas começam no mesmo ponto: **59,5 G usados**. Se o GC não conseguir
liberar espaço (imagens em uso), vem a expulsão. Já `/home` (761 G, LVM
no mesmo disco) está praticamente vazio nos 3 nós e serve de cache local de modelos, fora do NFS e da
rede de 1 GbE. O disco é um só, `ROTA=1`: HD ou volume de RAID que se declara rotacional
`[não verificado]`.

**Evidência.** [sabdiia01](logs-analysis/inventario-no-sabdiia01-2026-09-29-1006.log):

```
/dev/mapper/ol-root   70G   51G   20G  72% /
/dev/mapper/ol-home  761G  5.8G  755G   1% /home
sda         836.6G    1 disk
```

Imagens e diretório do containerd ([01](logs-analysis/imagens-no-sabdiia01-2026-09-29-1025.log),
[02](logs-analysis/imagens-no-sabdiia02-2026-09-29-1025.log),
[03](logs-analysis/imagens-no-sabdiia03-2026-09-29-1024.log)):

```
33G	/var/lib/containerd        (sabdiia01)
25G	/var/lib/containerd        (sabdiia02)
20G	/var/lib/containerd        (sabdiia03)
docker.io/vllm/vllm-openai   v0.6.4   13c224cdc000d   5.62GB   (sabdiia03)
```

Limiares em vigor ([configz, 01](logs-analysis/imagens-kubelet-sabdiia01-2026-09-29-1030.log); 02 e 03
idênticos) e imagens de vLLM por nó (`ctr`, tamanho comprimido):

```
"imageGCHighThresholdPercent":85
"imageGCLowThresholdPercent":80
"imagefs.available":"15%"
"nodefs.available":"10%"
sabdiia01: vllm/vllm-openai:v0.12.0  8.3 GiB
sabdiia02: vllm/vllm-openai:v0.6.4   5.2 GiB; open-webui:main 1.5 GiB
sabdiia03: vllm/vllm-openai:v0.6.4   5.2 GiB
```

| Nó | `/` usado | Folga até 85 % (59,5 G) | Imagens de vLLM |
|---|---|---|---|
| `sabdiia01` | 51 G | **8,5 G** | `v0.12.0` (em uso pelo *pod* que cai) |
| `sabdiia02` | 43 G | **16,5 G** | `v0.6.4` (sem uso ali) |
| `sabdiia03` | 44 G | 15,5 G | `v0.6.4` (em uso pelo deepseek) |

**Uma imagem de vLLM ocupa ~3,3× o tamanho comprimido** `[medido]`, porque o containerd guarda as
camadas comprimidas (`content`) e as desempacotadas (`snapshotter.overlayfs`). Remover a `v0.12.0`
(8,3 GiB comprimida) de `sabdiia01` liberou **27 G**: `/var/lib/containerd` caiu de 33 G para 5,8 G. Pela
mesma razão, a `v0.19.1` (9,6 GB = 8,95 GiB comprimida, [F-008]) deve ocupar **~29 G** `[cálculo]`. **Só
cabe num nó com `/` esvaziado antes**: em `sabdiia01`, depois da remoção, `/` ficou com 24 G usados e
47 G livres.

**Remover imagem com `ctr` exige apagar as três referências, pelo *digest*.** O containerd, sob o
Kubernetes, registra cada imagem três vezes: nome com *tag*, nome com *digest* e `sha256:<id>`. Em
`sabdiia02`, apagar só as duas primeiras (filtro pelo nome) não liberou nada: `df` e `du` não mudaram
(43 G em `/`, 25 G em `/var/lib/containerd`), porque a terceira continuou segurando as camadas. Em
`sabdiia01`, apagar as três pelo *digest* liberou os 27 G em menos de 20 s.

```
### antes: 20G livres        33G  /var/lib/containerd
docker.io/vllm/vllm-openai:v0.12.0
docker.io/vllm/vllm-openai@sha256:6766ce0c459e24b76f3e9ba14ffc0442131ef4248c904efdcbf0d89e38be01fe
sha256:0c19f07f0c8601d5b77e5a95e188115c17e5d9ddab105462be4951c92f4ebdbb
### depois: 47G livres (liberou 27G)   5.8G  /var/lib/containerd
```

([remoção em 01](logs-analysis/remocao-v0120-sabdiia01-2026-10-02-1253.log); a remoção incompleta e o
diagnóstico de `sabdiia02`, de 2026-09-29, foram colados no chat e os logs ficaram no nó.)

**Regra prática.** Antes de baixar uma imagem do vLLM, calcule ~3,3× o tamanho comprimido e confira que
`/` termina abaixo de 85 %. Num `/` de 70 G cabe **uma** imagem recente do vLLM por nó; para trocar de
versão, remova a anterior primeiro. Para remover: pare os *pods* que a usam e apague **todas as
referências com o mesmo *digest*** (Passo 3 do
[runbook](runbooks/primeiro-arranque-v0.19.1.md)), medindo `df` antes e depois. Mover o *root* do
containerd para `/home` (PD-15) continua sendo a saída estrutural. Para cache local de modelos, use
`/home`, não `/`.

**Atualização 2026-10-28: a falta de espaço em `/` acabou.** O administrador redimensionou o LVM de 01
e 02 como já tinha feito em 03: `/` com **631 G** (534-580 G livres) e `/home` com **200 G** (77-156 G
livres). O `imageFs` do *kubelet* passou de 75,1 GB para **677,5 GB** de capacidade (622,8 GB livres em 01),
e o limiar de 15 % fica em ~102 GB. Cabem várias imagens do vLLM por nó; a regra "uma imagem por vez"
e o cálculo de folga abaixo ficam como histórico. O que mudou de lado: **`/home` encolheu de 761 G para 200
G**, com 102 G (01) e 124 G (02) já usados (Docker em `/home/utec/docker_data`). Cache local de modelos em
`/home` agora tem limite; em `/` cabe mais.

```
/dev/mapper/ol-root  631G   51G  580G   9% /        (sabdiia01)
/dev/mapper/ol-home  200G  102G   99G  51% /home
"capacityBytes": 677501730816   "availableBytes": 622752088064   (imageFs)
```

**Medida da `v0.19.1` (2026-10-02, `sabdiia01`):** `/` foi de 24 G para **54 G usados** (+30 G) e
`/var/lib/containerd` de 5,8 G para 37 G, para uma imagem de 9,0 GiB comprimida: razão de ~3,4×. Sobram
17 G livres (77 %), a **5,5 G** do ponto em que o *kubelet* reage. Nenhuma outra imagem grande cabe em
`sabdiia01` enquanto a `v0.19.1` estiver lá.

**Validade.** 2026-10-02. Razão medida em duas imagens (`v0.12.0` e `v0.19.1`); velocidade de leitura do
disco local: `[não medido]`.

## 5. Decisões

| ID | Decisão | Descartado | Por quê | Estado |
|---|---|---|---|---|
| D-01 | Imagem de referência: `vllm/vllm-openai:v0.19.1` | `v0.20.0`+ (CUDA 13, sem `sm_70`); `v0.12.0` (7 versões mais antiga, também com `sm_70`); variantes `-cu129` de `v0.20.0`+ (Dockerfile sem `7.0`) | última versão com `sm_70` no Dockerfile (AC-11) | **confirmada** em 2026-10-02 pelo primeiro arranque (AC-13) |
| D-03 | **Descartado** como modelo de produção: `Qwen/Qwen3.8-27B` com bitsandbytes 4 bits, na configuração de AC-14 | — | ~3 *tokens*/s e 12 min de arranque (AC-14) não atendem ao uso pretendido (decisão do usuário, 2026-10-13); sem GPTQ do 3.8, e o GPTQ do 3.5-27B não cabe (AC-15) | em vigor; **antes de apagar o *pod*, testar as alavancas da PD-20**; substituto: PD-19 |
| D-04 | **Escalar com réplicas de 1 GPU por nó, sem Ray**: um `Deployment` do vLLM por GPU atrás de um `Service`; modelo que caiba inteiro em 32 GB. Primeiro candidato: `Qwen/Qwen3-30B-A3B-GPTQ-Int4` (PD-19) | Ray com modelo dividido entre nós (*tensor parallel*: a rede custa mais que o ganho; *pipeline parallel*: só para modelo > 32 GB, PD-31); Ray Serve na frente das réplicas (sem medida de ganho sobre o `Service`); gpt-oss no vLLM (MXFP4 exige CC 8.0) | AC-01, AC-21, AC-22; réplicas não passam pela rede durante a geração. **Medido em 2026-10-29 (AC-23):** o mesmo 7B dividido em 2 GPUs pelo Ray rende 22-25 % menos que em 1 GPU | **provisória** (2026-10-27): o modelo depende de arranque, qualidade (AC-15) e *tool calling* (PD-25); hoje são 2 réplicas possíveis (01 e 02), porque 03 tem a produção |
| D-02 | `sabdiia01` é o nó de testes; `vllm-llama31-8b` desligado (`--replicas=0`) e imagem `v0.12.0` removida | testar em `sabdiia02` (imagem não cabia, e a remoção por nome não liberou espaço) | abriu GPU e 27 G de disco sem tirar nenhum serviço que funcionasse (AC-09) | **suspensa em 2026-10-27**: a GPU de 01 é disputada pelo Ray do administrador, que liga sem aviso (AC-19), e a `v0.19.1` foi apagada e não cabe de volta em `/` (AC-20). Volta com a PD-15 (containerd em `/home`) e um acordo sobre a GPU (PD-29) |

## 6. Configuração de referência

Primeiro arranque que funcionou (2026-10-02, `sabdiia01`, AC-13). É um teste de fumaça com modelo
pequeno, não a configuração ótima:

```
image: vllm/vllm-openai:v0.19.1
command: vllm serve Qwen/Qwen2.5-0.5B-Instruct --dtype float16 --max-model-len 4096
         --gpu-memory-utilization 0.90 --host 0.0.0.0 --port 8000
env: HF_HOME=/hf-cache (hostPath /home/utec/vllm-estudo/hf-cache); sem HF_TOKEN
recursos: nvidia.com/gpu 1, cpu 4-8, memória 16-32 Gi, /dev/shm 4 Gi em memória
```

Manifesto completo: Passo 4 de [runbooks/primeiro-arranque-v0.19.1.md](runbooks/primeiro-arranque-v0.19.1.md).

| Número do arranque | Valor |
|---|---|
| *Download* da imagem (9,6 GB) | 5 min 19 s |
| Contêiner iniciado → servidor no ar | 1 min 52 s |
| Memória do modelo | 0,93 GiB |
| *KV cache* | 26,93 GiB = 2.353.152 *tokens* |
| *CUDA graphs* | 86 grafos, 9 s, 0,32 GiB |
| GPU em uso (`nvidia-smi`) | 29.998 MiB de 32.768 |
| `/` depois da imagem | 54 G usados, 17 G livres (77 %) |

Manifesto anterior, ainda em produção: o do deepseek em AC-05.

## 7. Otimização

### 7.1 Alavancas

*(preencher com efeito medido, após a linha de base)*

Alavancas **candidatas**, a medir contra a linha de base de AC-05:

- Tirar `--enforce-eager` (*CUDA graphs*): costuma melhorar o *decode* e custa VRAM `[hipótese]`.
  Medição planejada na PD-27.
- Aumentar `--max-num-seqs`: mais *throughput* com concorrência, desde que o *KV cache* caiba.
- Versão mais nova do vLLM, se houver uma com `sm_70` (PD-03).
- Cache de modelos local em `/home` em vez do NFS: arranque a frio mais curto `[hipótese]` (PD-04).
- 755 GiB de RAM por nó permitem *offload* para CPU, a verificar na versão escolhida
  `[não verificado]`.

### 7.2 Pendências

| ID | Pergunta | Que decisão destrava | Como fechar |
|---|---|---|---|
| PD-31 | **Dividir um modelo entre dois nós vale a pena nesta rede?** Proposta do administrador: com Ray, dividir entre 2 nós um modelo que não cabe numa V100S. A divisão soma memória (64 GB), mas cada *token* passa pela rede de 1 GbE (AC-08), e o custo disso nunca foi medido aqui. Um modelo de 60 GB não carrega nem nas duas: 0,90 × 64 GB = 57,6 GB `[cálculo]` | se um modelo maior que 32 GB entra pelo multinó (Ray), por 2 GPUs no mesmo nó (PD-22) ou por *quantization*/MoE numa GPU (PD-19) | ~~(0) RTT~~ feito em 2026-10-27: 0,247 ms → *tensor parallel* entre nós descartado por cálculo (AC-21). (0b) **Rede nova (2026-10-28):** o `bond1` de 4 × 10 GbE não leva tráfego de *pod* (AC-08); RTT medido pelo `bond1` × `bond0`: 03 → 02, 0,311 × 0,348 ms; 01 → 02, 0,236 × 0,319 ms (56 trocas × 0,236 ms ≥ 13,2 ms por *token* `[cálculo]`, contra 20,3 ms de TPOT com 1 GPU). **Pôr os *pods* no `bond1` não salva o *tensor parallel*** (AC-21): a latência, não a banda, é o custo dominante; para *pipeline parallel* a banda maior ajuda pouco, porque o tráfego já é pequeno `[hipótese]`. (0c) **2026-10-28: o administrador já roda o arranjo, e ele é candidato ao MVP** (AC-19: Llama-3.1-8B, `--pipeline-parallel-size 3`, `v0.5.4`): medir como está, com a carga da B-001c, pelo [runbook B-003](runbooks/medicao-ray-pp3.md) `[não executado]`. Não é uma variável por vez (modelo, versão, nº de GPUs e `--enforce-eager` mudam juntos). ~~(1) Qwen2.5-7B com `--pipeline-parallel-size 2` entre 01 e 02 contra 1 GPU~~ **feito em 2026-10-29 (AC-23): perde 22-25 % de vazão; para modelo que cabe em 32 GB, a resposta é não.** Falta, para modelos maiores: (2) o custo num modelo que precise das 2 GPUs, contra 2 GPUs no mesmo nó (PD-22) e *quantization*/MoE numa GPU (PD-19); (3) 2 réplicas de 1 GPU medidas, se a D-04 precisar do número (hoje ~1.360 *tok*/s é cálculo). `--tensor-parallel-size 2` só se for preciso confirmar o AC-21 com número |
| PD-29 | **Atualizada 2026-10-28: o Ray está em *pods* com as 3 GPUs reservadas e a produção em `0/0` (AC-19). Modelo e paralelismo respondidos às 15:22: Llama-3.1-8B com `--pipeline-parallel-size 3`. Falta: é experimento ou serviço, por quanto tempo ocupa as GPUs, e o deepseek volta?** Antes: **O que o Ray do administrador rodou às 12:14, e quando volta a usar as GPUs?** Já se sabe (AC-19): vLLM `0.5.4`, Ray `2.38.0`, não foi o `deploy.py` pelo Serve, e às 14:20 só o *head* seguia no ar. Faltam o modelo, se foi *tensor* ou *pipeline parallel* entre 01 e 02, e se é experimento ou serviço permanente | quais GPUs ficam para o estudo e em que horários (D-02); se a divisão entre nós (contra AC-01 e AC-08) vira uma medição a fazer ou sai de cena | conversa com o administrador (mais barata); ou leitura dos logs da sessão `session_2026-10-27_12-10-38_728215_577731` em `/tmp/ray` de 01 e 02 (`Loading model weights took`, `tensor_parallel_size`) |
| PD-24 | **A refrigeração das GPUs.** **`sabdiia01` resolvido em 2026-10-22** (ajuste do administrador; B-001c sem estrangulamento, AC-17). A 2ª intervenção, na sala (10-23), não mudou a GPU (B-001d): o ajuste que valeu foi o de 10-22. Falta saber o que foi mudado, para repetir nos outros nós, e se `sabdiia01` aguenta carga de 20 min ou mais (B-002). As de `sabdiia02` e `sabdiia03` estrangulam sob carga? O que muda no servidor (perfil térmico e ventoinhas no gerenciador do servidor, posição da placa, fluxo de ar) para a GPU sustentar o *clock*? | **toda medição de desempenho depende disto**; onde rodar a linha de base; se a topologia de 2 GPUs por nó é viável termicamente (PD-22) | (1) ~~Bloco D~~ feito em 2026-10-15: limites iguais nos 3 (83/87/90 °C); `ipmitool` ausente, ventoinhas só pelo iDRAC; (1b) teste térmico curto em `sabdiia02`, hoje fria, para saber se o problema é do nó ou dos três (exige liberar espaço para a imagem `v0.19.1` em `sabdiia02`); (2) com o administrador, ajuste de refrigeração em `sabdiia01`; (3) repetir o Bloco C: o critério é `SW Thermal Slowdown` inativo e *clock* perto de 1597 MHz durante a carga |
| PD-10 | **Linha de base de concorrência na V100S (B-001):** com um modelo sem *quantization*, quanto a vazão total cresce de 1 a 64 requisições simultâneas, e quanto pioram TTFT e TPOT por usuário? (O deepseek em produção fica para depois: a API tem 1 requisição em 10 dias.) | se o vLLM serve vários usuários nesta GPU (objetivo do estudo, definido pelo usuário em 2026-10-14); contra o que medir cada alavanca | [runbooks/teste-concorrencia-vllm.md](runbooks/teste-concorrencia-vllm.md): `Qwen/Qwen2.5-7B-Instruct` em FP16 em `sabdiia01`, `vllm bench serve` dentro do *pod*, concorrência 1/4/8/16/32/64, 512 → 256 *tokens*, p50/p95/p99 |
| PD-28 | **Por que os *pods* de `sabdiia01` não resolvem nomes desde a manutenção?** De dentro do *pod*, falham `kubernetes.default.svc.cluster.local` e `huggingface.co`; o nó resolve. O `resolv.conf` do *pod* aponta para o *Service* do CoreDNS (`10.96.0.10`), e as duas réplicas do CoreDNS estão em `sabdiia03`. O nó tem 3 dias de *uptime*, e o `calico-node` dele reiniciou há 3d1h. Hipótese: o tráfego de *pod* de `sabdiia01` para *pods* de outro nó ou para IPs de *Service* não passa `[hipótese]` | se `sabdiia01` pode receber uma réplica de produção (um *pod* sem DNS de *cluster* não alcança *Services* pelo nome) e se a rede de *pods* entre nós está íntegra antes de montar o `Service` com 3 réplicas | com o administrador: estado do Calico e das rotas em `sabdiia01`; de dentro do `vllm-conc`, testar o IP do CoreDNS e um IP de *pod* de `sabdiia03` |
| PD-27 | **Quanto custa `--enforce-eager` na V100S?** Com o mesmo `Qwen/Qwen2.5-7B-Instruct` FP16, quanto caem a vazão total e o tempo por *token* com os *CUDA graphs* desligados? No arranque, os *graphs* custaram 0,32-0,44 GiB e 9-12 s (AC-13, B-001); o ganho de velocidade `[não medido]` | se vale aceitar `--enforce-eager` quando a memória aperta (como no 27B, AC-14) ou trocar de modelo; quanto a configuração do deepseek em produção (`--enforce-eager`, AC-05) deixa de ganhar | depois da PD-24 e da B-001 refeita: repetir o Bloco B de [runbooks/teste-concorrencia-vllm.md](runbooks/teste-concorrencia-vllm.md) com `--enforce-eager` como **única** mudança, concorrência 1, 8 e 64, vigiando *clock* e temperatura (AC-17); comparar vazão total e TPOT p50/p99 |
| PD-25 | **Os candidatos da PD-19 fazem *tool calling* confiável na `v0.19.1` desta GPU?** A aplicação que vai usar o vLLM ([F-023]) responde toda pergunta pedindo ao modelo uma ferramenta de consulta ao SQL Server: no mínimo duas chamadas ao modelo por pergunta. Para devolver `tool_calls`, o servidor precisa de *flags* que ligam um *parser* específico do modelo (`--enable-auto-tool-choice`, `--tool-call-parser`) `[não verificado na v0.19.1]` | o modelo do MVP (a taxa de chamadas válidas pesa mais que *tok*/s); as *flags* do manifesto; a latência por pergunta (duas chamadas mais o SQL) | (1) conferir as *flags* e os *parsers* em `vllm/engine/arg_utils.py` e na doc da *tag* `v0.19.1`, registrar em FONTES; (2) para cada candidato, ~20 perguntas do *golden set* da aplicação com as ferramentas declaradas, `temperature` 0: contar chamadas com JSON válido e ferramenta certa, medir tempo total por pergunta; (3) só depois da PD-24, para o tempo não sair da refrigeração |
| PD-11 | Os 18 reinícios iniciais do deepseek foram a `startupProbe` (60 × 10 s = 10 min) matando o *pod* durante o *download* do modelo? | como dimensionar `startupProbe` e se o modelo deve ser pré-baixado por um `Job` | a última queda recebeu `SIGTERM` (`KeyboardInterrupt: terminated`) com o carregamento em 0 %; confirmar num arranque novo cronometrado |
| PD-05 | O pool `pool-publico` é alcançável de fora? Quem consome a API hoje? | autenticação na borda (Kong) ou `--api-key`; risco aceito | conversa com o dono do ambiente; regras de MetalLB e *firewall* |
| PD-26 | **Como a aplicação nos servidores 10 e 11, fora do *cluster*, alcança o vLLM, e com que autenticação?** Um `Service` `ClusterIP` não serve; `NodePort`, `LoadBalancer` ou Ingress (Kong) expõem a API, que hoje sobe sem `--api-key` (AC-06). A arquitetura ([F-023]) promete "sem rota pública ao vLLM" sem dizer como | o tipo do `Service` e o uso de `--api-key` no manifesto de produção; se o SSE atravessa o Kong (*buffering* desligado na rota) | com a infraestrutura e o responsável pela arquitetura: caminho de rede 10/11 → *cluster*, alcance do `pool-publico` (PD-05); depois, teste de *streaming* a partir de um dos servidores 10/11 com a chave |
| PD-04 | Quanto leva carregar os *weights*: NFS (1 conexão, `rsize` 64 KiB) × cópia local em `/home`? | onde fica o cache de modelos; `startupProbe` | cronometrar o carregamento no log de arranque, nas duas origens, com o mesmo modelo (AC-08, AC-09) |
| PD-17 | Quanto a imagem `v0.19.1` consome de `/` de fato, e o que o nó faz quando falta espaço? | troca a estimativa de AC-09 por medida; argumento para a PD-15 | [runbooks/teste-queda-disco-v0.19.1.md](runbooks/teste-queda-disco-v0.19.1.md): aplica [configs/vllm-qwen38-27b.yaml](configs/vllm-qwen38-27b.yaml) em `sabdiia02` e para sozinho em 15 G livres. **Arriscado: combinar com o administrador** |
| PD-21 | Num nó do *cluster* (1 V100S), o Ollama/llama.cpp é mais rápido que o vLLM **com o mesmo modelo e a mesma carga**? | motor de produção: vLLM (forte em concorrência) × Ollama (forte em um usuário por vez nesta GPU) | o mesmo modelo inteiro em 32 GB nos dois motores (ex.: `Qwen3.8-27B` em GGUF 4 bits, F-010), 1 e N requisições simultâneas. Referência externa, **outro servidor com as mesmas placas** (as V100S foram tiradas dele para montar este *cluster*): o usuário mediu 10 → 50 *tokens*/s com `gpt-oss:120b` no Ollama, com as 2 V100S na mesma máquina, sem Kubernetes, ajustando `num_ctx`, Flash Attention e quantização q8. O ganho acompanhou a queda do *offload* para a CPU (40 % → 4 %), com 64 GB de VRAM num servidor só, arranjo que não existe aqui |
| PD-22 | **Topologia das GPUs:** manter 1 V100S por nó (até 3 cópias de modelos de até ~32 GB; tolera falha de um nó) ou juntar 2 V100S num nó (64 GB para um modelo maior, *tensor parallel* no vLLM ou divisão de camadas no Ollama; menos cópias)? | o tamanho máximo de modelo e a forma de escalar o serviço | decisão do usuário e do administrador, com base no uso (modelo grande e capaz × muitos usuários simultâneos), nos resultados da PD-20/PD-21 e em conferir se o nó comporta 2 placas (espaço, *riser*, energia). Evidência a favor de 2 por nó: PD-21 (gpt-oss-120b a ~50 *tokens*/s com 2 V100S juntas) |
| PD-20 | **Parcial (2026-10-14): concorrência não ajuda e raciocínio desligado funciona (AC-16).** Restam R1 (*CUDA graphs* via `--kv-cache-memory-bytes`) e R2 (entrada de imagem desligada). Alguma parametrização tira o `Qwen/Qwen3.8-27B` dos ~3 a 5 *tokens*/s? | se o modelo pedido volta a ser viável (reabre D-03) ou não | Passo 1b de [runbooks/teste-qwen38-27b-bnb.md](runbooks/teste-qwen38-27b-bnb.md) no *pod* em execução; depois R1 e R2, um por vez |
| PD-19 | Qual modelo entrega a velocidade necessária na V100S com saída correta? Candidatos: `Qwen/Qwen3-30B-A3B-GPTQ-Int4` (MoE, 3B ativos; **primeiro a testar**, D-04; ~16,2 GB de *weights* [F-030] `[cálculo]`, cabe numa V100S com ~12 GB para *KV cache*; especialistas no `MoeWNA16`, atenção no `gptq_gemm` de 4 bits sob alerta, AC-15), `Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8` (núcleo 8 bits, fora do alerta), `Qwen/Qwen2.5-32B-Instruct-GPTQ-Int4` (núcleo 4 bits sob alerta), `Qwen/Qwen2.5-7B-Instruct` em FP16 (controle, sem *quantization*) | o modelo de produção que substitui o Qwen3.8-27B (D-03) | definir com o usuário a velocidade mínima e o uso; testar um candidato por vez em `sabdiia01` com o mesmo bloco de AC-14 (imagem já no nó; só o modelo baixa para `/home`), conferindo *tokens*/s **e** se a resposta faz sentido (AC-15) |
| PD-13 | Por que `sabdiia03` negociou PCIe x8, tem ECC desligado, e `sabdiia01` tem *persistence mode* desligado? | se os 3 nós são equivalentes para réplicas e comparações | `nvidia-smi -q` sob carga para o PCIe; decidir ECC e *persistence* iguais nos 3. A porta a 100 Mbps de `sabdiia01` saiu desta pendência: está fora do agregado e não afeta medições (AC-08); a troca do cabo `enp65s0f1` fica com a equipe de rede |

## 8. Lições

- **Confira a premissa de hardware na visão do orquestrador.** "2 GPUs" e "2 GPUs no mesmo nó" levam a
  arquiteturas diferentes (AC-01).
- **Um *pod* em `CrashLoopBackOff` segura a GPU.** O *scheduler* conta o *request*, não o uso: uma GPU
  pode ficar parada por uma semana sem aparecer como livre (§2, `sabdiia01`).
- **"Não sobe" não é "não é compatível".** A queda atribuída à versão era de autenticação (AC-07). Leia
  `logs --previous` antes de formar hipótese.
- **O log de arranque é a evidência mais valiosa e a primeira a sumir.** A rotação do *kubelet* apagou
  o do deepseek; só sobrou porque o contêiner anterior tinha caído durante o arranque.
- **Um *bond* "no ar" pode ter uma porta degradada.** O Kubernetes e o `ip link` não mostram isso;
  `/proc/net/bonding/bond0` mostra a velocidade de cada porta (AC-08).
- **No Ollama/llama.cpp, quase todo ganho de velocidade vem de tirar camadas da CPU.** Contexto menor,
  Flash Attention e *KV cache* quantizado liberam VRAM para mais camadas na GPU. O vLLM não divide o
  modelo com a CPU por padrão; nele, `--max-model-len` não acelera, e na V100S não há FlashAttention
  (AC-13). Os parâmetros com o mesmo nome não têm o mesmo efeito nos dois motores.
- **Dividir um modelo muda onde ele cabe, não o que ele responde.** Qualidade vem do modelo; velocidade
  de um MoE vem dos poucos parâmetros ativos; a divisão só acrescenta comunicação (AC-21, AC-22).
- **O Kubernetes só conhece a GPU que ele mesmo entregou.** Processo rodando direto no *host* ocupa a
  GPU e ela continua aparecendo como livre. A pergunta "está livre?" se responde no `nvidia-smi` do nó,
  não no *scheduler* (AC-19).
- **Agregar portas não soma a banda de uma conexão.** 6 × 1 GbE em LACP continuam dando 1 Gbps para um
  único fluxo, como o de um *mount* NFS sem `nconnect` (AC-08).

## 9. Correções

| Data | Correção | Mecanismo do erro |
|---|---|---|
| 2026-10-29 | AC-21 "*pipeline parallel* custa ~5 %" → perde 22-25 % de vazão e +31 % de tempo por *token* contra 1 GPU (AC-23) | a estimativa contou só a transferência na fronteira entre as etapas, com o RTT de ICMP como custo inteiro, e ignorou a espera entre as etapas e a coordenação do Ray a cada passo |
| 2026-10-29 | Runbook B-004: o log do *head* guardou só as últimas 600 linhas e perdeu o arranque, e com ele a prova de captura dos *CUDA graphs* → logs completos em arquivo próprio | o `tail` foi dimensionado para o arranque, mas o *head* grava uma linha por requisição, e a carga empurrou o arranque para fora |
| 2026-10-28 | Bloco "produção e rede nova" titulado para `sabdiia01` rodou em `sabdiia03` e gravou o log com o nome de 01 → arquivo renomeado para `-sabdiia03-`; os blocos passam a usar `$(hostname -s)` no nome e a abortar se o nó for outro | o nome do nó estava fixo no `tee` e o bloco não conferia `hostname`: o log mentiria sobre a origem se não tivesse o cabeçalho `== $(hostname -s)` |
| 2026-10-28 | PD-15 fechada sem executar o [runbook](runbooks/mover-containerd-para-home.md): o administrador redimensionou o LVM e `/` passou a 631 G em 01 e 02; `imageFs` com 677,5 GB (AC-09) | — |
| 2026-10-28 | "*bond* de 40 G" informado → em 01 e 02 são 4 × 10 GbE (`speed=40000`), mas o `layer2` limita a 10 Gbps por destino; em 03, 20 G ativos. E o `bond1` só tem IPv6 da VLAN 302: **os *pods* continuam no `bond0` de 1 GbE** (AC-08) | velocidade somada do agregado tomada como velocidade entre dois nós; o caminho do tráfego de *pod* depende do IP que o Calico anuncia, não das placas instaladas |
| 2026-10-27 | AC-08 "*tensor* ou *pipeline parallel* entre nós fica fora de questão" → só *tensor parallel*; *pipeline parallel* passa pouco pela rede e fica como opção de capacidade (AC-21) | as duas formas de dividir o modelo foram tratadas como uma só, sem contar o tráfego de cada uma |
| 2026-10-27 | PD-30 fechada pelo bloco das 14:20 (→ AC-20): `DiskPressure` voltou a `False` às 12:40, `etcd` em `/`, `data-root` do Docker em `/home`, `v0.19.1` apagada de 01 | — |
| 2026-09-28 | Premissa "Kubernetes + Docker" → *runtime* containerd (AC-02) | premissa informada tomada como fato antes do inventário |
| 2026-09-28 | Premissa "≥ 2 GPUs" → 3 GPUs em 3 nós, 1 por nó (AC-01) | idem |
| 2026-09-28 | "V100 32 GB" → V100S-PCIE-32GB (AC-04) | nome comercial aproximado; o GFD dá o produto exato |
| 2026-09-28 | PD-06 (conteúdo de `vllms`) e PD-08 (CPU/RAM livre) fechadas pelo Bloco 1b | viraram AC-05, AC-06 e linhas da §2 |
| 2026-09-29 | "`v0.12.0` cai em *loop*, causa desconhecida" → causa é `401` em repositório *gated* (AC-07); PD-09 fechada | o sintoma (a versão nova não sobe) foi lido como indício de incompatibilidade antes de ver o log |
| 2026-09-29 | "produção consumida por usuários" → 1 requisição desde 09-18 | premissa sobre uso tomada do nome do *namespace* |
| 2026-09-29 | PD-12 fechada: o *token* do `hf-secret` é inválido (AC-07) | — |
| 2026-09-29 | "NFD indica disco não rotacional" → `lsblk` mostra `sda` com `ROTA=1`; os únicos dispositivos `ROTA=0` são os leitores ópticos `sr0`/`sr1` e o `sdb` de 0 B | *label* do NFD lido como fato sobre o disco de dados, sem conferir no *host* |
| 2026-09-29 | "PV `Released` ocupa 200 G no NFS" → a exportação inteira tem 17 G usados (AC-03) | tamanho declarado do PV tomado como espaço ocupado |
| 2026-09-29 | PD-01 fechada pelo Bloco 2 (→ §2, AC-08, AC-09); PD-07 fechada por AC-08 (rede de 1 GbE descarta multinó) | — |
| 2026-09-29 | PD-14 fechada pelo Bloco 2c (→ AC-09) | — |
| 2026-09-29 | PD-02 fechada pelo Bloco 3 (→ AC-10) | — |
| 2026-10-22 | AC-18 dizia que, com `HF_HUB_OFFLINE=1`, a API anunciaria o modelo pelo caminho no cache e recomendava `--served-model-name` → a API continuou anunciando `Qwen/Qwen2.5-7B-Instruct` (B-001c) | li `served_model_name` no log do motor e no código de `EngineArgs` e supus que a API usa o mesmo valor, sem perguntar a `/v1/models` (o texto estava marcado como inferência) |
| 2026-10-22 | Critério do Bloco E "nenhuma amostra < 1400 MHz" → contadores de `Thermal Slowdown` parados e temperatura < 83 °C | um piso de *clock* confunde a variação normal da V100S com a carga com estrangulamento; o contador mede a causa |
| 2026-10-15 | AC-17 citava o mecanismo de redução de *clock* por temperatura sem fonte → acrescentada a documentação do `nvidia-smi` (F-022) | conhecimento prévio escrito como fato, sem a fonte primária que o CLAUDE.md exige |
| 2026-10-14 | PD-23 fechada pelo Bloco C (→ AC-17). B-001 rebaixada de "linha de base" para "medida sob estrangulamento térmico" | o runbook não vigiava *clock* e temperatura durante a carga; o checklist de medições não tinha esse item (acrescentado no CLAUDE.md) |
| 2026-10-02 | PD-03 fechada pelo primeiro arranque (→ AC-13, D-01 confirmada). As hipóteses de AC-11 sobre Triton e AVX2 passaram a confirmadas | — |
| 2026-10-02 | Passo 4 interrompido por engano com Ctrl+C: o *pod* seguiu sozinho, sem freio de disco, e a segunda execução abortou com 28 G livres | o bloco só monitora; interrompê-lo não para o *download*. Runbook ganhou o Passo 4b e o aviso |
| 2026-10-02 | "`ctr images rm` deixa camadas órfãs e não deve ser usado" → funciona se as **três** referências forem removidas; em `sabdiia02` ficaram a terceira (`sha256:<id>`) e as camadas (AC-09) | filtrei as referências pelo nome da imagem; a terceira não tem nome, só o identificador |
| 2026-10-02 | "o fluxo que cair na porta de 100 Mbps anda a um décimo da velocidade" → a porta está num agregador LACP inativo e não carrega dados (AC-08) | vi `Speed` e supus o efeito, sem olhar `Aggregator ID`: no 802.3ad, porta de velocidade diferente não entra no agregado |
| 2026-10-02 | "uma conexão TCP não passa de 1 Gbps" → com `layer2`, **todo** o tráfego para um mesmo destino usa 1 porta, mesmo com várias conexões (AC-08) | política de *hash* suposta, não lida |
| 2026-09-29 | "imagem de vLLM ocupa ~15-20 G em disco" → ~3 a 3,5× o tamanho comprimido; `v0.19.1` ≈ 27-32 G (AC-09) | estimativa por diferença entre dois nós que ignorou as camadas comprimidas que o containerd também guarda |
| 2026-09-29 | Regra "remova a `v0.6.4` com `ctr images rm`" → não libera espaço e deixa camadas órfãs (AC-09) | comando do containerd recomendado sem conferir como o CRI e o GC tratam a remoção |
| 2026-09-29 | Bloco 3 do runbook: 3 execuções com `InvalidImageName` → bloco refeito com imagem fixa `nvidia/cuda:12.4.1-base-ubuntu22.04` ([F-001](FONTES.md)) | o bloco trazia um *placeholder* (`PREENCHA-...<tag-base>`) que colado vira nome inválido, e o log só gravava a última etapa, escondendo a causa |

---

## Evidências

| Arquivo em `logs-analysis/` | Prova |
|---|---|
| [B-004-ray-pp2-qwen25-7b-sabdiia01-2026-10-29-1039.log](logs-analysis/B-004-ray-pp2-qwen25-7b-sabdiia01-2026-10-29-1039.log), [testes/2026-10-29-1113-Qwen_Qwen2.5-7B-Instruct/](logs-analysis/testes/2026-10-29-1113-Qwen_Qwen2.5-7B-Instruct/), [ray-pp2-qwen25-7b.yaml](logs-analysis/ray-pp2-qwen25-7b.yaml) | Ray do estudo em 01 + 02 (`ray 2.48.0`, `cupy 13.6.0`), `2.0/2.0 GPU`; `v0.19.1`, `--pipeline-parallel-size 2`, sem `--enforce-eager`; 7,13 GiB de pesos por GPU, *KV cache* 762.928 *tokens* (93,13×); c=1 36,7 *tok*/s, TPOT 26,6 ms; c=16 324,4; c=32 510,6, TTFT p50 1,10 s; 0 falhas, 0 preempções; sem estrangulamento (máx. 56 °C); uso médio em c=32: 60 % (01) e 81 % (02); arranque do *head* perdido no log (§9) (AC-23) |
| [pull-v0191-sabdiia02-2026-10-29-1101.log](logs-analysis/pull-v0191-sabdiia02-2026-10-29-1101.log) | `image_pull_progress_timeout = '5m0s'` em 02; `ctr images pull` da `v0.19.1` em 6 min 30 s, saída 0; `/` de 101 para 114 G durante o `ctr` (84 G às 10:36) (AC-24) |
| [pronto-para-teste-sabdiia01-2026-10-29-1035.log](logs-analysis/pronto-para-teste-sabdiia01-2026-10-29-1035.log), [02](logs-analysis/pronto-para-teste-sabdiia02-2026-10-29-1036.log) | GPUs de 01 e 02 livres (0 MiB, `0 0`), sem estrangulamento; `vllms` e `vllm-estudo` vazios; MTU 1500 em 01 e 02, `ping` de 1472 *bytes* passa entre os 3; imagens `v0.19.0`/`v0.19.1` em 01 e nenhuma `v0.19.x` em 02 (§2) |
| [B-004-ray-pp2-qwen25-7b-sabdiia01-2026-10-29-1032.log](logs-analysis/B-004-ray-pp2-qwen25-7b-sabdiia01-2026-10-29-1032.log) | 1ª tentativa da B-004 abortada antes de criar qualquer *pod*: faltava o `teste-protocolo.sh` |
| [ray-docker-inventario-sabdiia01-...](logs-analysis/ray-docker-inventario-sabdiia01-2026-10-27-1214.log), [02](logs-analysis/ray-docker-inventario-sabdiia02-2026-10-27-1218.log), [03](logs-analysis/ray-docker-inventario-sabdiia03-2026-10-27-1218.log) | Docker e Podman nos 3 nós; Ray do administrador no *host* (*venv*, `root`), *head* em 01 e *worker* em 02, mesma sessão; 8.162 MiB por GPU com o Kubernetes em `0 0`; painel `0.0.0.0:8265` e GCS `*:6379`; contêineres do projeto parados; `/` 100 % em 01 e 02, *pods* `Evicted` (MetalLB, `node-exporter`); `sabdiia03` redimensionado e com `kubectl` quebrado (OIDC); 27.882 MiB em 03 (AC-19, AC-20, §2) |
| [containerd-config-sabdiia01-2026-10-27-1602.log](logs-analysis/containerd-config-sabdiia01-2026-10-27-1602.log) | o containerd de 01 ainda guarda as imagens em `/var/lib/containerd`, no `/` de 70 G (`ol-root`); o `imageFs` do *kubelet* confirma (75,1 GB de capacidade, 41,2 GB livres): PD-15 não feita. Arquivos de configuração regravados em 2026-10-26 18:39, `99-nvidia.toml` com 5226 *bytes* e três chaves ignoradas pelo containerd (§2) |
| [estado-disco-rede-sabdiia01-...](logs-analysis/estado-disco-rede-sabdiia01-2026-10-28-1419.log), [02](logs-analysis/estado-disco-rede-sabdiia02-2026-10-28-1420.log), [03](logs-analysis/estado-disco-rede-sabdiia03-2026-10-28-1421.log) | depois da manutenção: `/` 631 G e `/home` 200 G nos 3 (LVM sem folga), `imageFs` 677,5 GB, `DiskPressure False` (PD-15 fechada, AC-09); novo `bond1` 4 × 10 GbE `layer2`, só VLAN 302 IPv6, 40000 em 01/02 e 20000 em 03; IP do nó, rota *default* e Calico em `bond0.500` (1 GbE); `bond0` de 03 com MTU 9000; `enp65s0f1` de 01 ainda a 100 Mbps (AC-08); Kubernetes `v1.37.1`, containerd `2.4.2`; **as 3 GPUs com 0 MiB, inclusive 03** (§2) |
| [ray-onde-erro-sabdiia01-...](logs-analysis/ray-onde-erro-sabdiia01-2026-10-28-1712.log), [02](logs-analysis/ray-onde-erro-sabdiia02-2026-10-28-1713.log), [03](logs-analysis/ray-onde-erro-sabdiia03-2026-10-28-1713.log) | nenhum Ray/vLLM em *pod*, processo ou contêiner nos 3 nós; nada em 8000/8265/6379; GPUs 0 MiB; `vllm-deepseek-33b` e `vllm-llama31-8b` seguem `0/0`. Rede: **`bond1.20@bond1` `UP` sem endereço nos 3**; MTU igual ao das 14:19 (03 com 9000 no `bond0`); `bond1` de 03 ainda com 2 portas em outro agregador; `enp65s0f1` de 01 ainda a 100 Mbps (§2) |
| [ray-erro-rede-sabdiia01-2026-10-28-1710.log](logs-analysis/ray-erro-rede-sabdiia01-2026-10-28-1710.log) | `No resources found in vllms namespace`; `deployments.apps "ray-head" not found` (e os dois *workers*): o Ray saiu de `vllms` entre 16:51 e 17:10. Os `FALHOU` de porta são do `kubectl exec` sem *pod*, não da rede (o bloco não abortava sem *pods*) |
| [api-ray-diagnostico-sabdiia01-2026-10-28-1651.log](logs-analysis/api-ray-diagnostico-sabdiia01-2026-10-28-1651.log) | `curl: (7) ... port 8000: Connection refused`; só `gcs_server` em `:6379` (nem `:8000` nem `:8265`); *pods* do Ray `Running`, 0 reinícios, 108 min; nenhum `api_server` no *head*; 3 GPUs com 0 MiB (AC-19). O "`curl saiu com 0`" é do `echo` anterior, não do `curl` (erro do bloco) |
| [ray-k8s-modelo-sabdiia01-2026-10-28-1522.log](logs-analysis/ray-k8s-modelo-sabdiia01-2026-10-28-1522.log) | os *Deployments* do Ray só rodam `ray start` (`hostNetwork: true`, PVC `hf-cache-pvc`, `/dev/shm` 16 Gi, 1 GPU); o `api_server` do vLLM foi iniciado à parte: `Meta-Llama-3.1-8B-Instruct`, `--pipeline-parallel-size 3 --tensor-parallel-size 1`, `--enforce-eager`, `0.98`, `--max-model-len 4096`, `--max-num-seqs 16`; `ray status` 3 nós, `3.0/3.0 GPU`; `serve` sem `grpc`; GPUs 26.026/30.928/25.024 MiB a 0 %; log do *head* sem a linha de configuração (AC-19) |
| [vllms-ray-k8s-sabdiia01-2026-10-28-1511.log](logs-analysis/vllms-ray-k8s-sabdiia01-2026-10-28-1511.log) | `ray-head`, `ray-worker-2` e `ray-worker-3` (`v0.5.4`), um por nó, **cada um com `nvidia.com/gpu: 1`**, todos `1/1`; `nvidia.com/gpu 1 1` nos 3 nós; `vllm-deepseek-33b` e `vllm-llama31-8b` em `0/0` (não apagados); `Service` `192.168.50.160:8001` sem *pod*; `python3` com 5.664 MiB na GPU de 01; sem log de queda anterior nos *workers* novos (AC-19) |
| [producao-rede-nova-sabdiia01-2026-10-28-1500.log](logs-analysis/producao-rede-nova-sabdiia01-2026-10-28-1500.log) | **`vllms` sem o `vllm-deepseek-33b`**: só `ray-head` (01, `Running`) e dois `ray-worker` (03 e 02, reiniciando em `BackOff`), imagem `vllm/vllm-openai:v0.5.4` (5,48 GB, *pull* de 1m48s a 5m), criados ~14:50 (§2, AC-19, PD-29); NFS por `bond1.302` em 01; MTU 1500 e `tunl0` 1480 em 01; RTT a 02: 0,319 ms (`bond0`) × 0,236 ms (`bond1`) (AC-08, PD-31) |
| [producao-rede-nova-sabdiia03-2026-10-28-1452.log](logs-analysis/producao-rede-nova-sabdiia03-2026-10-28-1452.log) | rodado em **`sabdiia03`** (o bloco era para 01; arquivo renomeado para o nó real, §9): `kubectl` falha (OIDC), estado da produção não lido; NFS sai por `bond1.302`; MTU 9000 em `bond0`/`bond0.500` e 8980 no Calico; RTT a 02: 0,260/0,348/0,441 ms pelo `bond0` e 0,220/0,311/0,706 ms pelo `bond1` (AC-08, PD-31) |
| [rtt-sabdiia01-02-2026-10-27-1446.log](logs-analysis/rtt-sabdiia01-02-2026-10-27-1446.log) | RTT `sabdiia01` → `sabdiia02`: 0,177/0,247/0,340 ms (mín./média/máx.), 0 % de perda em 100 pacotes (AC-21) |
| [ray-pd29-pd30-sabdiia01-...](logs-analysis/ray-pd29-pd30-sabdiia01-2026-10-27-1420.log), [02](logs-analysis/ray-pd29-pd30-sabdiia02-2026-10-27-1422.log) | depois da limpeza: `DiskPressure False` desde 12:40/12:41; `/` 46 % e 70 %; `etcd` em `/`; `data-root` do Docker em `/home/utec/docker_data`; nenhuma imagem `vllm-openai`; deepseek e `speaker` do MetalLB `Running`; GPUs sem processo; Ray com só o *head* em 01, sem aplicações Serve; vLLM `0.5.4`, Ray `2.38.0`, torch `2.4.0+cu121`; `.py` com o mesmo *hash* dos versionados (AC-19, AC-20, §2) |
| [inventario-cluster-2026-09-28.txt](logs-analysis/inventario-cluster-2026-09-28.txt) | versão do K8s, nós, *runtime*, GPU Operator, GPUs alocáveis, RuntimeClasses, StorageClass e PVs (AC-01, AC-02, AC-03) |
| [inventario-vllms-2026-09-28.txt](logs-analysis/inventario-vllms-2026-09-28.txt) | *labels* GFD (GPU, *driver*, CUDA), *taints*, recursos por nó, estado e manifestos de `vllms` (AC-04, AC-05, AC-06). A primeira seção (consumidores de GPU) não foi executada: o bloco não foi colado inteiro (`syntax error near unexpected token '}'`). A ocupação veio de `Allocated resources` |
| [inventario-vllms-logs-2026-09-29.txt](logs-analysis/inventario-vllms-logs-2026-09-29.txt) | queda do `vllm-llama31-8b` por `401`/*gated* (AC-07); arranque de 09-18 do deepseek (XFormers, GPTQ, *cast* BF16→FP16) e `/metrics` (*KV cache*, 1 requisição) (AC-05); API sem credencial (AC-06). Convertido de uma captura de terminal em RTF (`bloco_c1.rtf`); a seção "arranque até o servidor subir" veio vazia por causa da rotação do log |
| [inventario-hf-token-2026-09-29-0931.log](logs-analysis/inventario-hf-token-2026-09-29-0931.log) | o *token* de `hf-secret` é inválido (`whoami` → `401`) e não baixa do repositório *gated* da Meta (AC-07) |
| [inventario-no-sabdiia01-2026-09-29-1006.log](logs-analysis/inventario-no-sabdiia01-2026-09-29-1006.log), [02](logs-analysis/inventario-no-sabdiia02-2026-09-29-1006.log), [03](logs-analysis/inventario-no-sabdiia03-2026-09-29-1004.log) | CPU sem AVX2, RAM, discos (`/` apertado, `/home` livre), montagem NFS, GPU no *host* (PCIe, ECC, *persistence*, 28.598 MiB do deepseek), *bond* com porta a 100 Mbps em 01, sem Docker (§2, AC-05, AC-08, AC-09) |
| [imagens-no-sabdiia01-...](logs-analysis/imagens-no-sabdiia01-2026-09-29-1025.log), [02](logs-analysis/imagens-no-sabdiia02-2026-09-29-1025.log), [03](logs-analysis/imagens-no-sabdiia03-2026-09-29-1024.log) | tamanho de `/var/lib/containerd` por nó; lista de imagens de 03 (`v0.6.4` = 5,62 GB); `crictl` ausente em 01 e 02; `config.yaml` do *kubelet* sem limiares de disco (AC-09) |
| [imagens-kubelet-sabdiia01-...](logs-analysis/imagens-kubelet-sabdiia01-2026-09-29-1030.log), [02](logs-analysis/imagens-kubelet-sabdiia02-2026-09-29-1031.log), [03](logs-analysis/imagens-kubelet-sabdiia03-2026-09-29-1030.log) | limiares em vigor do *kubelet* (GC 85/80 %, `imagefs.available` 15 %), iguais nos 3; imagens de vLLM por nó (`v0.12.0` 8,3 GiB em 01; `v0.6.4` 5,2 GiB em 02 e 03) (AC-09) |
| [docs-analysis/config.toml](docs-analysis/config.toml) | cópia do `/etc/containerd/config.toml` de um nó (2026-10-02): `root`, `imports` de `/etc/containerd/conf.d/*.toml`, `discard_unpacked_layers = false`, `enable_cdi = true`, `default_runtime_name = "runc"` (AC-09, PD-15). Não é a configuração mesclada: falta o que está em `conf.d` |
| [containerd-config-sabdiia01-...](logs-analysis/containerd-config-sabdiia01-2026-10-02-1145.log), [02](logs-analysis/containerd-config-sabdiia02-2026-10-02-1145.log), [03](logs-analysis/containerd-config-sabdiia03-2026-10-02-0958.log) | configuração em vigor do containerd, **idêntica nos 3 nós**: `root = '/var/lib/containerd'`, `root_path` vazio em todos os *snapshotters*, `imports` de `conf.d` com um único `99-nvidia.toml` (5124 *bytes*); arquivos com contexto SELinux (AC-09, PD-15) |
| [pre-arranque-sabdiia01-2026-10-02-1247.log](logs-analysis/pre-arranque-sabdiia01-2026-10-02-1247.log) | estado de `sabdiia01` antes do primeiro arranque: `/` com 51 G usados e 20 G livres, containerd com 33 G; GPU reservada pelo `vllm-llama31-8b` (2853 reinícios) com 0 MiB em uso; a imagem `v0.12.0` tem 3 referências com o mesmo *digest* (PD-15) |
| [B-001-concorrencia-sabdiia01-2026-10-14-1718.log](logs-analysis/B-001-concorrencia-sabdiia01-2026-10-14-1718.log) | saída completa do `vllm bench serve` nas 6 concorrências da B-001 (vazão, TTFT, TPOT, ITL em p50/p95/p99) e preempções zeradas ([B-001](medicoes/B-001-concorrencia-qwen25-7b-fp16.md)) |
| [termico-sabdiia01-...](logs-analysis/termico-sabdiia01-2026-10-15-1417.log), [02](logs-analysis/termico-sabdiia02-2026-10-15-1418.log), [03](logs-analysis/termico-sabdiia03-2026-10-15-1419.log) | limites de temperatura das 3 GPUs (83/87/90 °C, iguais), temperatura e potência paradas, nenhum motivo de redução ativo, `ipmitool` ausente (AC-17, PD-24) |
| [B-001b-diagnostico-sabdiia01-2026-10-14-1832.log](logs-analysis/B-001b-diagnostico-sabdiia01-2026-10-14-1832.log), [gpu-amostras-b001b.csv](logs-analysis/gpu-amostras-b001b.csv), [gpu-performance-b001b.txt](logs-analysis/gpu-performance-b001b.txt) | GPU de `sabdiia01` sob carga: 72 → 82 °C, *clock* de 1560 para ~400 MHz, `SW Thermal Slowdown: Active`; `cpu.stat` do *pod* sem estrangulamento relevante; requisições de 5,6 s a 21,8 s (AC-17) |
| `B-001-qwen25-7b-fp16-c{1,4,8,16,32,64}.json` | resultado de cada nível da B-001 em JSON, com desvio padrão e pico de vazão por segundo (`max_output_tokens_per_s`: 25 a 448 *tok*/s) ([B-001](medicoes/B-001-concorrencia-qwen25-7b-fp16.md)) |
| [teste-concorrencia-arranque-sabdiia01-2026-10-14-1657.log](logs-analysis/teste-concorrencia-arranque-sabdiia01-2026-10-14-1657.log) | arranque do `Qwen/Qwen2.5-7B-Instruct` FP16 na `v0.19.1`: *download* de 15 GB em 125 s, modelo 14,25 GiB, *KV cache* 13,14 GiB / 246.016 *tokens*, 86 *CUDA graphs* em 12 s, *prefix caching* ligado (PD-10) |
| [teste-concorrencia-arranque-sabdiia01-2026-10-22-1521.log](logs-analysis/teste-concorrencia-arranque-sabdiia01-2026-10-22-1521.log) | depois da intervenção do administrador: imagem já no nó, GPU livre (`0 0`), mas o *pod* cai em 3 min com `Temporary failure in name resolution` ao listar o repositório do modelo no Hugging Face |
| [teste-concorrencia-arranque-offline-sabdiia01-2026-10-22-1541.log](logs-analysis/teste-concorrencia-arranque-offline-sabdiia01-2026-10-22-1541.log) | arranque com `HF_HUB_OFFLINE=1`: `Ready` em 2 min 44 s, pesos lidos de `/home` (disco local) em 47 s, mesmo *KV cache* do dia 14 (246.016 *tokens*); nome servido = caminho no cache (AC-18). DNS: o nó resolve `huggingface.co`; de dentro do *pod* falham o nome do *cluster* e o externo; CoreDNS só em `sabdiia03`; `calico-node` de 01 reiniciado há 3d1h (PD-28) |
| [B-001d-reteste-termico-sabdiia01-2026-10-23-1635.log](logs-analysis/B-001d-reteste-termico-sabdiia01-2026-10-23-1635.log), [gpu-amostras-b001d.csv](logs-analysis/gpu-amostras-b001d.csv), [gpu-performance-b001d.txt](logs-analysis/gpu-performance-b001d.txt) | depois da intervenção na sala: mesma carga da B-001c, mesmos números (31 → 72 °C, 235,5 W médios, contador `SW Thermal Slowdown` em 0 µs antes e depois; 48,2 e 680,5 *tok*/s); 2 min depois da carga, 32 °C (AC-17) |
| [B-001c-reteste-termico-sabdiia01-2026-10-22-1552.log](logs-analysis/B-001c-reteste-termico-sabdiia01-2026-10-22-1552.log), [gpu-amostras-b001c.csv](logs-analysis/gpu-amostras-b001c.csv), [gpu-performance-b001c.txt](logs-analysis/gpu-performance-b001c.txt) | depois do ajuste de refrigeração: GPU parada a 31 °C, máx. 72 °C a 240-250 W, contador `SW Thermal Slowdown` em 0 µs; concorrência 1 a 47 *tok*/s (TPOT 20,3 ms), concorrência 32 a 680 *tok*/s (TTFT p50 1,09 s); quedas de *clock* a ~1260 MHz a cada ~12 s com potência menor, sem estrangulamento; `/v1/models` anuncia `Qwen/Qwen2.5-7B-Instruct` com o modo *offline* (AC-17, AC-18) |
| [alavancas-qwen38-2026-10-14-1625.log](logs-analysis/alavancas-qwen38-2026-10-14-1625.log) | Qwen3.8-27B + bitsandbytes com 1, 4 e 8 requisições simultâneas: vazão total ~4 *tokens*/s em todos os níveis; raciocínio desligado por `chat_template_kwargs` (AC-16) |
| [teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1509.log](logs-analysis/teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1509.log) | **`Qwen/Qwen3.8-27B` no ar** com bitsandbytes + `--enforce-eager`: `Ready` em 12 min 24 s, *KV cache* 5,0 GiB / 20.384 *tokens*, 28.728 MiB de GPU, 200 *tokens* em 71,1 s (TTFT 13,5 s), raciocínio dentro de `content` (AC-14) |
| [teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1436.log](logs-analysis/teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1436.log) | `Qwen/Qwen3.8-27B` + bitsandbytes na `v0.19.1`: linha do tempo de *download* e GPU, arquitetura reconhecida, 18,06 GiB carregados, bloco de 784 *tokens*, *warmup* de 550 s e o `CUDA out of memory` em `profile_cudagraph_memory` (AC-14) |
| [primeiro-arranque-v0.19.1-retomada-sabdiia01-2026-10-02-1413.log](logs-analysis/primeiro-arranque-v0.19.1-retomada-sabdiia01-2026-10-02-1413.log) | **a `v0.19.1` roda na V100S**: log de arranque completo (V1, `TRITON_ATTN`, *cast* BF16→FP16, *CUDA graphs*, *KV cache*), eventos do *pod* (imagem em 5 min 19 s), geração de teste, 29.998 MiB na GPU, `/` com 54 G usados (AC-13, AC-09, §6) |
| [primeiro-arranque-v0.19.1-sabdiia01-2026-10-02-1406.log](logs-analysis/primeiro-arranque-v0.19.1-sabdiia01-2026-10-02-1406.log) | segunda execução do Passo 4, abortada pela proteção: 28 G livres, porque o *pod* da tentativa interrompida já baixava a imagem (§9) |
| [remocao-v0120-sabdiia01-2026-10-02-1253.log](logs-analysis/remocao-v0120-sabdiia01-2026-10-02-1253.log) | remover as 3 referências da `v0.12.0` pelo *digest* liberou 27 G em `sabdiia01`: `/` de 51 G para 24 G usados, containerd de 33 G para 5,8 G. Mede o custo em disco de uma imagem do vLLM (AC-09) |
| [desliga-llama-sabdiia01-2026-10-02-1250.log](logs-analysis/desliga-llama-sabdiia01-2026-10-02-1250.log) | `vllm-llama31-8b` escalado para 0 réplicas; *pod* removido; `nvidia.com/gpu 0 0` em `sabdiia01`; deepseek e `open-webui` inalterados (§2) |
| [rede-bond-sabdiia01-2026-10-02-1239.log](logs-analysis/rede-bond-sabdiia01-2026-10-02-1239.log) | `bond0` de `sabdiia01`: `Transmit Hash Policy: layer2`; `enp65s0f1` a 100 Mbps no agregador 1 (inativo), as outras 5 no agregador 2; placa e *switch* anunciam 1000baseT; zero erros; só tráfego *multicast* na porta (AC-08) |
| [teste-gpu-pod-2026-09-29-1138.log](logs-analysis/teste-gpu-pod-2026-09-29-1138.log) | *pod* com `nvidia.com/gpu: 1` e sem RuntimeClass vê 1 V100S em `sabdiia02` (AC-10). Os logs de 10:49, 11:14 e 11:31 são as tentativas com *placeholder* (`InvalidImageName`, §9) |
