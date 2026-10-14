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
**F3** (2026-09-29, Blocos 1, 1b e 2). Logs do Bloco 2:
[sabdiia01](logs-analysis/inventario-no-sabdiia01-2026-09-29-1006.log),
[sabdiia02](logs-analysis/inventario-no-sabdiia02-2026-09-29-1006.log),
[sabdiia03](logs-analysis/inventario-no-sabdiia03-2026-09-29-1004.log).

| Item | Valor | Comando / log |
|---|---|---|
| Kubernetes | `v1.37.0` (cliente, servidor e kubelet) | `kubectl version` · [cluster](logs-analysis/inventario-cluster-2026-09-28.txt) |
| Nós | 3 Dell PowerEdge R720: `sabdiia01` (.151), `sabdiia02` (.152), `sabdiia03` (.150) em 192.168.50.0/24; todos `control-plane`, sem *taints* | `get nodes -o wide`, `describe nodes` · [vllms](logs-analysis/inventario-vllms-2026-09-28.txt) |
| SO / *kernel* | Oracle Linux Server 9.8 / `6.12.0-206.104.3.3.el9uek.x86_64` | idem |
| CPU | 2 × Xeon E5-2690 (Sandy Bridge-EP, 2,90 GHz), 8 núcleos por *socket*, HT, 32 *threads*, 2 nós NUMA. **Sem AVX2** (só `avx`) | `lscpu`; *flags* de `/proc/cpuinfo` (Bloco 2) |
| RAM | 755 GiB por nó, sem *swap* ativo | `free -h` |
| CPU livre | *requests* já alocados: 1,4 a 5,4 vCPU por nó; *control plane* pesa pouco | `describe nodes` (Allocated) |
| Disco local | 1 disco `sda` 836,6 G, `ROTA=1` (rotacional, ou volume de RAID que se declara assim `[hipótese]`). `/` 70 G com **20 G** (`sabdiia01`), 28 G (02) e 27 G (03) livres, onde ficam as imagens do containerd. `/home` 761 G com **755 G livres** em cada nó | `df -h`, `lsblk` (Bloco 2) — AC-09 |
| *Runtime* | `containerd://2.3.5`; NVIDIA Container Toolkit `1.20.0`; **Docker não instalado** (`docker: command not found` nos 3) | `get nodes -o wide`; Bloco 2 |
| Gestão de GPU | NVIDIA GPU Operator (*device plugin*, *toolkit*, GFD, NFD, DCGM *exporter*); *driver* `pre-installed` no *host* | *labels* `nvidia.com/gpu.deploy.*` |
| GPU | `Tesla-V100S-PCIE-32GB`, 32768 MiB, `compute 7.0`, família `volta`; sem MIG, sem MPS, `sharing-strategy=none` | *labels* GFD |
| *Driver* / CUDA | `580.173.02` / `13.0` nos 3 nós | *labels* `nvidia.com/cuda.*` |
| RuntimeClasses | `nvidia`, `nvidia-cdi`, `nvidia-legacy` | `get runtimeclass` |
| GPU no *host* | PCIe Gen3, largura máx. x16 nos 3; **`sabdiia03` negociou x8** com a GPU em uso. ECC ligado em 01 e 02, **desligado em 03**. *Persistence mode* **desligado em 01**, ligado em 02 e 03. Limite de potência 250 W | `nvidia-smi`, `--query-gpu` (Bloco 2) |
| Armazenamento | só `nfs-storage` (`nfs.csi.k8s.io`, `Retain`, RWX). Servidor `[2801:80:f8c:302::aa]:/SABDIIAK8S_NFS01` (IPv6), NFS 4.1, `rsize=wsize=65536`, sem `nconnect`. Exportação de 500 G com **17 G usados** (todos os PVCs somados) | `get storageclass`, `get pv`; `findmnt`, `df` (Bloco 2) |
| Rede | `bond0` 802.3ad com 6 *links* de 1 GbE; **em `sabdiia01`, `enp65s0f1` está a 100 Mbps**. VLANs `bond0.302` e `bond0.500` (IP do nó) | `/proc/net/bonding/bond0` (Bloco 2) — AC-08 |
| Rede / borda | Calico; MetalLB (pool `pool-publico`); Kong no *namespace* `kong` | *pods* e anotações |
| Observabilidade | kube-prometheus (Prometheus, Alertmanager), `dcgm-exporter`, `metrics-server` | *pods* em `monitoring` e `gpu-operator` |

### Ocupação das GPUs e o *namespace* `vllms` (2026-09-28)

| Nó | GPU | Ocupante | Estado |
|---|---|---|---|
| `sabdiia01` | **livre desde 2026-10-02 12:50** | `vllm-llama31-8b` (`v0.12.0`, `meta-llama/Llama-3.1-8B-Instruct`) **desligado com `--replicas=0`** pelo usuário, depois de 2853 reinícios em 10 dias (`401` no Hugging Face, AC-07). O *deployment* continua existindo | reservada pelo *pod* em *loop* até então; para religar: `kubectl scale deploy/vllm-llama31-8b -n vllms --replicas=1` |
| `sabdiia02` | **livre** | `open-webui` (sem GPU) | `CreateContainerConfigError`: referencia o Secret `open-webui-secret`, que não existe no *namespace* |
| `sabdiia03` | alocada | `vllm-deepseek-33b`: `vllm/vllm-openai:v0.6.4`, `TheBloke/deepseek-coder-33B-instruct-GPTQ` | `Running` desde 2026-09-18 após 18 reinícios. `/metrics` em 2026-09-29: `request_success_total` = **1** (75 *tokens* de entrada, 158 de saída) |

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

### AC-17 — A V100S de `sabdiia01` estrangula por temperatura: sob carga contínua, o *clock* cai de 1560 para ~400 MHz em 2 min {#ac-17}

**O que é.** A GPU de `sabdiia01` fica a 72 °C parada, só com o modelo carregado. Sob carga ela chega a
82 °C, e o *driver* reduz o *clock* para segurar a temperatura (`SW Thermal Slowdown: Active`). Em 2 min o
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

**Regra prática.** Antes de qualquer medição, vigie `clocks.current.sm`, `temperature.gpu` e
`nvidia-smi -q -d PERFORMANCE` **durante a carga**. Medição com `SW Thermal Slowdown` ativo não vale como
número do motor. Para servir de verdade, `sabdiia01` precisa de refrigeração corrigida (PD-24, com o
administrador). Ao avaliar 2 GPUs no mesmo nó (PD-22), conte com mais calor no chassi.

**Validade.** `sabdiia01`, 2026-10-14, uma rodada de 3 min com concorrência 1. Temperatura sob carga de
`sabdiia02` e `sabdiia03`: `[não medido]`. Configuração de ventoinhas e fluxo de ar do servidor:
`[não verificado]`.

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
`nconnect` não ajudaria na saída; (2) *tensor* ou *pipeline parallel* entre nós fica fora de questão
`[hipótese]`. Em `sabdiia01`, a porta `enp65s0f1` negociou 100 Mbps, mas o LACP a pôs num agregador à
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

**Regra prática.** Descarte paralelismo multinó enquanto a rede for 1 GbE. Para arranque rápido, compare
NFS × cópia local em `/home` (AC-09, PD-04). A porta a 100 Mbps **não invalida medições em `sabdiia01`**;
trocar o cabo devolve a sexta porta (PD-13). Num *bond* LACP, confira `Aggregator ID` além de `Speed`.

**Validade.** 2026-10-02, `sabdiia01`. Vazão de saída medida uma vez, com `ssh` (n = 1). Política de
*hash* do *switch* (tráfego de entrada) e banda real do NFS: `[não medido]`. `Transmit Hash Policy` de 02 e 03: `[não verificado]`.

### AC-09 — `/` tem 20-28 G livres e guarda as imagens; `/home` tem 755 G livres em cada nó {#ac-09}

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
| D-02 | `sabdiia01` é o nó de testes; `vllm-llama31-8b` desligado (`--replicas=0`) e imagem `v0.12.0` removida | testar em `sabdiia02` (imagem não cabia, e a remoção por nome não liberou espaço) | abriu GPU e 27 G de disco sem tirar nenhum serviço que funcionasse (AC-09) | em vigor desde 2026-10-02 |

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
- Aumentar `--max-num-seqs`: mais *throughput* com concorrência, desde que o *KV cache* caiba.
- Versão mais nova do vLLM, se houver uma com `sm_70` (PD-03).
- Cache de modelos local em `/home` em vez do NFS: arranque a frio mais curto `[hipótese]` (PD-04).
- 755 GiB de RAM por nó permitem *offload* para CPU, a verificar na versão escolhida
  `[não verificado]`.

### 7.2 Pendências

| ID | Pergunta | Que decisão destrava | Como fechar |
|---|---|---|---|
| PD-24 | **A refrigeração das GPUs.** A de `sabdiia01` estrangula por temperatura (AC-17). As de `sabdiia02` e `sabdiia03` também, sob carga? O que muda no servidor (perfil térmico e ventoinhas no gerenciador do servidor, posição da placa, fluxo de ar) para a GPU sustentar o *clock*? | **toda medição de desempenho depende disto**; onde rodar a linha de base; se a topologia de 2 GPUs por nó é viável termicamente (PD-22) | (1) Bloco D do [runbook](runbooks/teste-concorrencia-vllm.md): temperaturas e ventoinhas nos 3 nós, só leitura; (2) com o administrador, ajuste de refrigeração em `sabdiia01`; (3) repetir o Bloco C: o critério é `SW Thermal Slowdown` inativo e *clock* perto de 1597 MHz durante a carga |
| PD-10 | **Linha de base de concorrência na V100S (B-001):** com um modelo sem *quantization*, quanto a vazão total cresce de 1 a 64 requisições simultâneas, e quanto pioram TTFT e TPOT por usuário? (O deepseek em produção fica para depois: a API tem 1 requisição em 10 dias.) | se o vLLM serve vários usuários nesta GPU (objetivo do estudo, definido pelo usuário em 2026-10-14); contra o que medir cada alavanca | [runbooks/teste-concorrencia-vllm.md](runbooks/teste-concorrencia-vllm.md): `Qwen/Qwen2.5-7B-Instruct` em FP16 em `sabdiia01`, `vllm bench serve` dentro do *pod*, concorrência 1/4/8/16/32/64, 512 → 256 *tokens*, p50/p95/p99 |
| PD-11 | Os 18 reinícios iniciais do deepseek foram a `startupProbe` (60 × 10 s = 10 min) matando o *pod* durante o *download* do modelo? | como dimensionar `startupProbe` e se o modelo deve ser pré-baixado por um `Job` | a última queda recebeu `SIGTERM` (`KeyboardInterrupt: terminated`) com o carregamento em 0 %; confirmar num arranque novo cronometrado |
| PD-05 | O pool `pool-publico` é alcançável de fora? Quem consome a API hoje? | autenticação na borda (Kong) ou `--api-key`; risco aceito | conversa com o dono do ambiente; regras de MetalLB e *firewall* |
| PD-04 | Quanto leva carregar os *weights*: NFS (1 conexão, `rsize` 64 KiB) × cópia local em `/home`? | onde fica o cache de modelos; `startupProbe` | cronometrar o carregamento no log de arranque, nas duas origens, com o mesmo modelo (AC-08, AC-09) |
| PD-15 | **Bloqueia o primeiro arranque.** Onde colocar as imagens: mover o *root* do containerd para `/home` (755 G livres), ou liberar as camadas órfãs da `v0.6.4` em `sabdiia02` (~16 G)? | se dá para baixar a `v0.19.1` (27-32 G em disco) | com o administrador: (a) `root` do containerd em `/home`, com o nó drenado e o containerd reiniciado; ou (b) descobrir o que segura as camadas órfãs (*leases*) e deixar o GC do containerd coletá-las. O `config.toml` do nó ([cópia](docs-analysis/config.toml), 2026-10-02) confirma `root = "/var/lib/containerd"`, `root_path = ""` no `overlayfs` (tudo sob o `root`) e `discard_unpacked_layers = false`, que é o que faz a imagem ocupar ~3× (guarda as camadas comprimidas depois de desempacotar). Ligar essa opção reduziria o custo por imagem em cerca de um terço `[hipótese, não testado]`. **Hipótese nova (2026-10-02) para as camadas "órfãs" de `sabdiia02`:** o containerd guarda três referências por imagem (*tag*, *digest* e `sha256:<id>`), e só duas foram removidas; a terceira ainda seguraria as camadas. O Passo 1 do runbook confirmou em `sabdiia01` que a `v0.12.0` tem **três referências com o mesmo *digest*** (*tag*, *digest* e `sha256:0c19f07f...`). Falta o Passo 3 confirmar que remover as três libera o espaço; se liberar, o mesmo comando resolve os ~16 G de `sabdiia02`. A configuração em vigor é idêntica nos 3 nós (2026-10-02), então a mudança é a mesma em todos; os arquivos têm contexto SELinux, a conferir com `getenforce` antes de mover dados para `/home` |
| PD-17 | Quanto a imagem `v0.19.1` consome de `/` de fato, e o que o nó faz quando falta espaço? | troca a estimativa de AC-09 por medida; argumento para a PD-15 | [runbooks/teste-queda-disco-v0.19.1.md](runbooks/teste-queda-disco-v0.19.1.md): aplica [configs/vllm-qwen38-27b.yaml](configs/vllm-qwen38-27b.yaml) em `sabdiia02` e para sozinho em 15 G livres. **Arriscado: combinar com o administrador** |
| PD-21 | Num nó do *cluster* (1 V100S), o Ollama/llama.cpp é mais rápido que o vLLM **com o mesmo modelo e a mesma carga**? | motor de produção: vLLM (forte em concorrência) × Ollama (forte em um usuário por vez nesta GPU) | o mesmo modelo inteiro em 32 GB nos dois motores (ex.: `Qwen3.8-27B` em GGUF 4 bits, F-010), 1 e N requisições simultâneas. Referência externa, **outro servidor com as mesmas placas** (as V100S foram tiradas dele para montar este *cluster*): o usuário mediu 10 → 50 *tokens*/s com `gpt-oss:120b` no Ollama, com as 2 V100S na mesma máquina, sem Kubernetes, ajustando `num_ctx`, Flash Attention e quantização q8. O ganho acompanhou a queda do *offload* para a CPU (40 % → 4 %), com 64 GB de VRAM num servidor só, arranjo que não existe aqui |
| PD-22 | **Topologia das GPUs:** manter 1 V100S por nó (até 3 cópias de modelos de até ~32 GB; tolera falha de um nó) ou juntar 2 V100S num nó (64 GB para um modelo maior, *tensor parallel* no vLLM ou divisão de camadas no Ollama; menos cópias)? | o tamanho máximo de modelo e a forma de escalar o serviço | decisão do usuário e do administrador, com base no uso (modelo grande e capaz × muitos usuários simultâneos), nos resultados da PD-20/PD-21 e em conferir se o nó comporta 2 placas (espaço, *riser*, energia). Evidência a favor de 2 por nó: PD-21 (gpt-oss-120b a ~50 *tokens*/s com 2 V100S juntas) |
| PD-20 | **Parcial (2026-10-14): concorrência não ajuda e raciocínio desligado funciona (AC-16).** Restam R1 (*CUDA graphs* via `--kv-cache-memory-bytes`) e R2 (entrada de imagem desligada). Alguma parametrização tira o `Qwen/Qwen3.8-27B` dos ~3 a 5 *tokens*/s? | se o modelo pedido volta a ser viável (reabre D-03) ou não | Passo 1b de [runbooks/teste-qwen38-27b-bnb.md](runbooks/teste-qwen38-27b-bnb.md) no *pod* em execução; depois R1 e R2, um por vez |
| PD-19 | Qual modelo entrega a velocidade necessária na V100S com saída correta? Candidatos: `Qwen/Qwen3-30B-A3B-GPTQ-Int4` (MoE, 3B ativos), `Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8` (núcleo 8 bits, fora do alerta), `Qwen/Qwen2.5-32B-Instruct-GPTQ-Int4` (núcleo 4 bits sob alerta), `Qwen/Qwen2.5-7B-Instruct` em FP16 (controle, sem *quantization*) | o modelo de produção que substitui o Qwen3.8-27B (D-03) | definir com o usuário a velocidade mínima e o uso; testar um candidato por vez em `sabdiia01` com o mesmo bloco de AC-14 (imagem já no nó; só o modelo baixa para `/home`), conferindo *tokens*/s **e** se a resposta faz sentido (AC-15) |
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
- **Agregar portas não soma a banda de uma conexão.** 6 × 1 GbE em LACP continuam dando 1 Gbps para um
  único fluxo, como o de um *mount* NFS sem `nconnect` (AC-08).

## 9. Correções

| Data | Correção | Mecanismo do erro |
|---|---|---|
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
| [B-001b-diagnostico-sabdiia01-2026-10-14-1832.log](logs-analysis/B-001b-diagnostico-sabdiia01-2026-10-14-1832.log), [gpu-amostras-b001b.csv](logs-analysis/gpu-amostras-b001b.csv), [gpu-performance-b001b.txt](logs-analysis/gpu-performance-b001b.txt) | GPU de `sabdiia01` sob carga: 72 → 82 °C, *clock* de 1560 para ~400 MHz, `SW Thermal Slowdown: Active`; `cpu.stat` do *pod* sem estrangulamento relevante; requisições de 5,6 s a 21,8 s (AC-17) |
| `B-001-qwen25-7b-fp16-c{1,4,8,16,32,64}.json` | resultado de cada nível da B-001 em JSON, com desvio padrão e pico de vazão por segundo (`max_output_tokens_per_s`: 25 a 448 *tok*/s) ([B-001](medicoes/B-001-concorrencia-qwen25-7b-fp16.md)) |
| [teste-concorrencia-arranque-sabdiia01-2026-10-14-1657.log](logs-analysis/teste-concorrencia-arranque-sabdiia01-2026-10-14-1657.log) | arranque do `Qwen/Qwen2.5-7B-Instruct` FP16 na `v0.19.1`: *download* de 15 GB em 125 s, modelo 14,25 GiB, *KV cache* 13,14 GiB / 246.016 *tokens*, 86 *CUDA graphs* em 12 s, *prefix caching* ligado (PD-10) |
| [alavancas-qwen38-2026-10-14-1625.log](logs-analysis/alavancas-qwen38-2026-10-14-1625.log) | Qwen3.8-27B + bitsandbytes com 1, 4 e 8 requisições simultâneas: vazão total ~4 *tokens*/s em todos os níveis; raciocínio desligado por `chat_template_kwargs` (AC-16) |
| [teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1509.log](logs-analysis/teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1509.log) | **`Qwen/Qwen3.8-27B` no ar** com bitsandbytes + `--enforce-eager`: `Ready` em 12 min 24 s, *KV cache* 5,0 GiB / 20.384 *tokens*, 28.728 MiB de GPU, 200 *tokens* em 71,1 s (TTFT 13,5 s), raciocínio dentro de `content` (AC-14) |
| [teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1436.log](logs-analysis/teste-qwen38-27b-bnb-sabdiia01-2026-10-02-1436.log) | `Qwen/Qwen3.8-27B` + bitsandbytes na `v0.19.1`: linha do tempo de *download* e GPU, arquitetura reconhecida, 18,06 GiB carregados, bloco de 784 *tokens*, *warmup* de 550 s e o `CUDA out of memory` em `profile_cudagraph_memory` (AC-14) |
| [primeiro-arranque-v0.19.1-retomada-sabdiia01-2026-10-02-1413.log](logs-analysis/primeiro-arranque-v0.19.1-retomada-sabdiia01-2026-10-02-1413.log) | **a `v0.19.1` roda na V100S**: log de arranque completo (V1, `TRITON_ATTN`, *cast* BF16→FP16, *CUDA graphs*, *KV cache*), eventos do *pod* (imagem em 5 min 19 s), geração de teste, 29.998 MiB na GPU, `/` com 54 G usados (AC-13, AC-09, §6) |
| [primeiro-arranque-v0.19.1-sabdiia01-2026-10-02-1406.log](logs-analysis/primeiro-arranque-v0.19.1-sabdiia01-2026-10-02-1406.log) | segunda execução do Passo 4, abortada pela proteção: 28 G livres, porque o *pod* da tentativa interrompida já baixava a imagem (§9) |
| [remocao-v0120-sabdiia01-2026-10-02-1253.log](logs-analysis/remocao-v0120-sabdiia01-2026-10-02-1253.log) | remover as 3 referências da `v0.12.0` pelo *digest* liberou 27 G em `sabdiia01`: `/` de 51 G para 24 G usados, containerd de 33 G para 5,8 G. Mede o custo em disco de uma imagem do vLLM (AC-09) |
| [desliga-llama-sabdiia01-2026-10-02-1250.log](logs-analysis/desliga-llama-sabdiia01-2026-10-02-1250.log) | `vllm-llama31-8b` escalado para 0 réplicas; *pod* removido; `nvidia.com/gpu 0 0` em `sabdiia01`; deepseek e `open-webui` inalterados (§2) |
| [rede-bond-sabdiia01-2026-10-02-1239.log](logs-analysis/rede-bond-sabdiia01-2026-10-02-1239.log) | `bond0` de `sabdiia01`: `Transmit Hash Policy: layer2`; `enp65s0f1` a 100 Mbps no agregador 1 (inativo), as outras 5 no agregador 2; placa e *switch* anunciam 1000baseT; zero erros; só tráfego *multicast* na porta (AC-08) |
| [teste-gpu-pod-2026-09-29-1138.log](logs-analysis/teste-gpu-pod-2026-09-29-1138.log) | *pod* com `nvidia.com/gpu: 1` e sem RuntimeClass vê 1 V100S em `sabdiia02` (AC-10). Os logs de 10:49, 11:14 e 11:31 são as tentativas com *placeholder* (`InvalidImageName`, §9) |
