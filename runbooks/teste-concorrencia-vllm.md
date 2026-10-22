# Runbook — vLLM com várias requisições simultâneas na V100S (medição B-001)

**Pergunta:** numa V100S, quanto o vLLM `v0.19.1` entrega quando a concorrência sobe de 1 para 64
requisições, com um modelo que roda **sem** quantização (sem bitsandbytes nem GPTQ, AC-15, AC-16)?
É o teste do ponto forte do vLLM, e a primeira medição com percentis do estudo (PD-10, PD-19).

**Por que este modelo:** `Qwen/Qwen2.5-7B-Instruct` (público, Apache 2.0, `Qwen2ForCausalLM`, 7,6 bilhões
de parâmetros em BF16, ~15 GB em FP16; API do Hugging Face conferida em 2026-10-14). Cabe inteiro na
GPU, deixa ~10 GiB para *KV cache* e usa a arquitetura comum, com blocos de 16 *tokens*, então os
*CUDA graphs* funcionam (AC-13). É a referência limpa: o que ele mostrar é o motor, não a quantização.

**Expectativa escrita antes:** com 1 requisição, dezenas de *tokens*/s por usuário. A vazão total
cresce com a concorrência até saturar a GPU, enquanto a latência por *token* de cada usuário sobe
devagar. O contrário do Qwen3.8-27B em bitsandbytes (AC-16), cuja vazão ficou parada em ~4 *tokens*/s.

**Desenho da medição.** Uma variável muda: a concorrência (`--max-concurrency` 1, 4, 8, 16, 32, 64).
Fixos: modelo, imagem, flags do servidor, 512 *tokens* de entrada e 256 de saída por requisição
(`--ignore-eos`, todas geram exatamente 256), *prompts* aleatórios com **uma semente por nível**
(`--seed` = concorrência), para que o *prefix caching*, ligado por padrão, não reaproveite os *prompts*
do nível anterior e baixe o TTFT artificialmente; `temperature` 0,
`--generation-config vllm` (sem a amostragem do `generation_config.json`, AC-13). Uma rodada de
aquecimento antes, descartada.

**O que este runbook altera:** apaga o *pod* `vllm-qwen38`, se ainda existir, e cria o `vllm-conc`, tudo
no *namespace* `vllm-estudo`, em `sabdiia01`. Baixa ~15 GB de modelo para `/home`. Não toca em `vllms`.

**Não interrompa com Ctrl+C:** o *pod* continua sozinho. Para parar: `kubectl delete pod -n vllm-estudo vllm-conc`.

---

## Bloco A — Arranque do servidor (servidor, bash, **em `sabdiia01`**)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  livre() { df --output=avail -BG / | tail -1 | tr -dc 0-9; }
  echo "### nó: $(hostname)   início: $(date '+%F %T')   livres em /: $(livre)G"
  echo "### liberando a GPU"
  kubectl delete pod -n vllm-estudo vllm-qwen38 --ignore-not-found --wait=true
  kubectl delete pod -n vllm-estudo vllm-conc --ignore-not-found --wait=true
  echo "### GPU reservada em sabdiia01 (espera-se 0 0)"
  kubectl describe node sabdiia01 | grep -E '^  nvidia\.com/gpu +[0-9]'
  kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: vllm-conc
  namespace: vllm-estudo
  labels:
    app: vllm-conc
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: sabdiia01
  containers:
  - name: vllm
    image: vllm/vllm-openai:v0.19.1
    command: ["vllm", "serve"]
    args:
    - Qwen/Qwen2.5-7B-Instruct
    - --dtype
    - float16
    - --max-model-len
    - "8192"
    - --gpu-memory-utilization
    - "0.90"
    - --generation-config
    - vllm
    - --host
    - 0.0.0.0
    - --port
    - "8000"
    env:
    - name: HF_HOME
      value: /hf-cache
    ports:
    - containerPort: 8000
    readinessProbe:
      httpGet:
        path: /health
        port: 8000
      periodSeconds: 10
    resources:
      requests:
        cpu: "8"
        memory: 32Gi
        nvidia.com/gpu: 1
      limits:
        cpu: "16"
        memory: 64Gi
        nvidia.com/gpu: 1
    volumeMounts:
    - name: hf-cache
      mountPath: /hf-cache
    - name: shm
      mountPath: /dev/shm
  volumes:
  - name: hf-cache
    hostPath:
      path: /home/utec/vllm-estudo/hf-cache
      type: DirectoryOrCreate
  - name: shm
    emptyDir:
      medium: Memory
      sizeLimit: 8Gi
EOF
  echo "### linha do tempo (a cada 10 s): hora | G livres em / | GPU MiB | fase | ready"
  PARADA="tempo esgotado (30 min)"
  for i in $(seq 1 180); do
    L=$(livre)
    G=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
    PH=$(kubectl get pod -n vllm-estudo vllm-conc -o jsonpath='{.status.phase}' 2>/dev/null)
    RD=$(kubectl get pod -n vllm-estudo vllm-conc -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null)
    echo "$(date +%T) | ${L}G | ${G:--} | ${PH:--} | ${RD:--}"
    if [ "$L" -le 12 ]; then PARADA="FREIO DE DISCO: ${L}G livres em /"; kubectl delete pod -n vllm-estudo vllm-conc --wait=false; break; fi
    if [ "$RD" = "true" ]; then PARADA="pod Ready"; break; fi
    if [ "$PH" = "Failed" ] || [ "$PH" = "Succeeded" ]; then PARADA="contêiner terminou (fase $PH)"; break; fi
    sleep 10
  done
  echo "### PARADA: $PARADA   em $(date '+%F %T')"
  kubectl get pod -n vllm-estudo vllm-conc -o wide
  kubectl describe pod -n vllm-estudo vllm-conc | sed -n '/^Events:/,$p'
  echo "### GPU";  nvidia-smi --query-gpu=memory.used,memory.total --format=csv
  echo "### processos na GPU (deve haver só o vLLM)";  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
  echo "### linhas-chave do arranque"
  kubectl logs -n vllm-estudo vllm-conc | grep -iE 'version|backend|dtype|KV cache|Maximum concurrency|Model loading took|CUDA graph|Graph capturing|init engine|prefix|error|Traceback|out of memory' | cut -c1-300
  echo "### log completo"
  kubectl logs -n vllm-estudo vllm-conc
} 2>&1 | tee teste-concorrencia-arranque-$(hostname -s)-$(date +%F-%H%M).log
```

Siga para o Bloco B só se `### PARADA: pod Ready`.

**Bloco A executado em 2026-10-14 16:57:** `Ready` em 4 min 5 s; modelo 14,25 GiB; *KV cache* 13,14 GiB =
246.016 *tokens* (30× a 8192 *tokens*); *CUDA graphs* capturados (12 s, 0,44 GiB); `enable_prefix_caching=True`
([log](../logs-analysis/teste-concorrencia-arranque-sabdiia01-2026-10-14-1657.log)).

**Bloco A executado em 2026-10-22 15:21 (depois da intervenção do administrador): `Failed` em 3 min.** O
*pod* não resolve nomes: `[Errno -3] Temporary failure in name resolution` ao listar o repositório no
Hugging Face. Mesmo com o modelo em cache, a `v0.19.1` consulta o Hub por um arquivo que o modelo não
tem e, sem rede, cai ([F-024](../FONTES.md);
[log](../logs-analysis/teste-concorrencia-arranque-sabdiia01-2026-10-22-1521.log)). Em 2026-10-14 o
mesmo bloco funcionou. Refeito como Bloco A2.

## Bloco A2 — Arranque *offline* e diagnóstico de DNS (servidor, bash, **em `sabdiia01`**)

Igual ao Bloco A, com uma diferença: `HF_HUB_OFFLINE=1` no contêiner, para o vLLM usar só o cache em
`/home` e não depender da rede. Não muda nada na *inference*, só o arranque. Antes, mostra o DNS do nó;
depois do *pod* pronto, testa de dentro dele um nome do *cluster* e um externo, para separar "o DNS do
*cluster* caiu" de "o *cluster* perdeu a saída para a internet". **Leva ~5 min. Só leitura, fora o
*pod* de teste.**

**Expectativa escrita antes:** `pod Ready` em ~4 min, sem `name resolution` no log
`[hipótese, F-024: o caminho offline foi lido no código, não executado]`. No teste de DNS, se o nome do
*cluster* resolver e o externo não, a falha é de saída para a internet ou do DNS externo, assunto do
administrador.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  livre() { df --output=avail -BG / | tail -1 | tr -dc 0-9; }
  echo "### nó: $(hostname)   início: $(date '+%F %T')   livres em /: $(livre)G   uptime: $(uptime -p)"
  echo "### DNS do nó (host)"
  cat /etc/resolv.conf
  getent hosts huggingface.co || echo "NAO RESOLVE no host: huggingface.co"
  echo "### CoreDNS e Calico (pods de rede do cluster)"
  kubectl get pods -n kube-system -l k8s-app=kube-dns -o wide
  kubectl get pods -A -o wide --field-selector spec.nodeName=sabdiia01 | grep -iE 'NAME|calico|dns'
  echo "### liberando a GPU"
  kubectl delete pod -n vllm-estudo vllm-conc --ignore-not-found --wait=true
  echo "### GPU reservada em sabdiia01 (espera-se 0 0)"
  kubectl describe node sabdiia01 | grep -E '^  nvidia\.com/gpu +[0-9]'
  kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: vllm-conc
  namespace: vllm-estudo
  labels:
    app: vllm-conc
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: sabdiia01
  containers:
  - name: vllm
    image: vllm/vllm-openai:v0.19.1
    command: ["vllm", "serve"]
    args:
    - Qwen/Qwen2.5-7B-Instruct
    - --dtype
    - float16
    - --max-model-len
    - "8192"
    - --gpu-memory-utilization
    - "0.90"
    - --generation-config
    - vllm
    - --host
    - 0.0.0.0
    - --port
    - "8000"
    env:
    - name: HF_HOME
      value: /hf-cache
    - name: HF_HUB_OFFLINE
      value: "1"
    ports:
    - containerPort: 8000
    readinessProbe:
      httpGet:
        path: /health
        port: 8000
      periodSeconds: 10
    resources:
      requests:
        cpu: "8"
        memory: 32Gi
        nvidia.com/gpu: 1
      limits:
        cpu: "16"
        memory: 64Gi
        nvidia.com/gpu: 1
    volumeMounts:
    - name: hf-cache
      mountPath: /hf-cache
    - name: shm
      mountPath: /dev/shm
  volumes:
  - name: hf-cache
    hostPath:
      path: /home/utec/vllm-estudo/hf-cache
      type: DirectoryOrCreate
  - name: shm
    emptyDir:
      medium: Memory
      sizeLimit: 8Gi
EOF
  echo "### linha do tempo (a cada 10 s): hora | G livres em / | GPU MiB | fase | ready"
  PARADA="tempo esgotado (30 min)"
  for i in $(seq 1 180); do
    L=$(livre)
    G=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
    PH=$(kubectl get pod -n vllm-estudo vllm-conc -o jsonpath='{.status.phase}' 2>/dev/null)
    RD=$(kubectl get pod -n vllm-estudo vllm-conc -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null)
    echo "$(date +%T) | ${L}G | ${G:--} | ${PH:--} | ${RD:--}"
    if [ "$L" -le 12 ]; then PARADA="FREIO DE DISCO: ${L}G livres em /"; kubectl delete pod -n vllm-estudo vllm-conc --wait=false; break; fi
    if [ "$RD" = "true" ]; then PARADA="pod Ready"; break; fi
    if [ "$PH" = "Failed" ] || [ "$PH" = "Succeeded" ]; then PARADA="contêiner terminou (fase $PH)"; break; fi
    sleep 10
  done
  echo "### PARADA: $PARADA   em $(date '+%F %T')"
  kubectl get pod -n vllm-estudo vllm-conc -o wide
  kubectl describe pod -n vllm-estudo vllm-conc | sed -n '/^Events:/,$p'
  echo "### GPU";  nvidia-smi --query-gpu=memory.used,memory.total --format=csv
  echo "### processos na GPU (deve haver só o vLLM)";  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
  echo "### DNS de dentro do pod (só se ele estiver rodando)"
  kubectl exec -n vllm-estudo vllm-conc -- cat /etc/resolv.conf
  for H in kubernetes.default.svc.cluster.local huggingface.co; do
    kubectl exec -n vllm-estudo vllm-conc -- python3 -c "import socket,sys; h=sys.argv[1]
try: print(h, '->', socket.getaddrinfo(h, 443)[0][4][0])
except Exception as e: print(h, '-> FALHOU:', e)" "$H"
  done
  echo "### linhas-chave do arranque"
  kubectl logs -n vllm-estudo vllm-conc | grep -iE 'version|backend|dtype|KV cache|Maximum concurrency|Model loading took|CUDA graph|Graph capturing|init engine|prefix|offline|name resolution|error|Traceback|out of memory' | cut -c1-300
  echo "### log completo"
  kubectl logs -n vllm-estudo vllm-conc
} 2>&1 | tee teste-concorrencia-arranque-offline-$(hostname -s)-$(date +%F-%H%M).log
```

Siga para o Bloco E só se `### PARADA: pod Ready`.

**Bloco A2 executado em 2026-10-22 15:41:** `Ready` em 2 min 44 s; mesmos números do dia 14 (14,25 GiB de
modelo, *KV cache* de 246.016 *tokens*, *CUDA graphs* em 12 s); pesos lidos de `/home` em 47 s. O modo
*offline* funcionou (AC-18). O log do motor mostra o caminho no cache como nome do modelo; por
precaução, os Blocos E e F leem o nome em `/v1/models` em vez de fixá-lo (a API respondeu
`Qwen/Qwen2.5-7B-Instruct` no Bloco E). DNS de dentro do *pod*: falham **o nome do *cluster* e o externo**; o
nó resolve `huggingface.co` (PD-28)
([log](../logs-analysis/teste-concorrencia-arranque-offline-sabdiia01-2026-10-22-1541.log)).

## Bloco B — Medição de concorrência (servidor, bash, **em `sabdiia01`**)

O gerador `vllm bench serve` roda **dentro do próprio *pod***, falando com `127.0.0.1:8000`: a rede não
entra na latência. Ele divide a CPU com o servidor (16 vCPU de limite), anotado como ressalva. Leva uns
20 a 40 min. Os resultados em JSON ficam em `/home/utec/vllm-estudo/hf-cache/bench/`.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### $(date '+%F %T')";  kubectl get pod -n vllm-estudo vllm-conc -o wide
  echo "### GPU antes (só o vLLM deve aparecer)"
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
  B="vllm bench serve --backend openai --base-url http://127.0.0.1:8000 --endpoint /v1/completions --model Qwen/Qwen2.5-7B-Instruct --dataset-name random --random-input-len 512 --random-output-len 256 --ignore-eos --temperature 0 --metric-percentiles 50,95,99"
  echo "### aquecimento (descartado): concorrência 4, 16 requisições, semente 999"
  kubectl exec -n vllm-estudo vllm-conc -- sh -c "$B --seed 999 --max-concurrency 4 --num-prompts 16" | tail -5
  for C in 1 4 8 16 32 64; do
    N=$((C * 8)); [ "$N" -lt 32 ] && N=32
    echo "############ concorrência $C, $N requisições, semente $C, $(date +%T) ############"
    kubectl exec -n vllm-estudo vllm-conc -- sh -c "$B --seed $C --max-concurrency $C --num-prompts $N --save-result --result-dir /hf-cache/bench --result-filename B-001-qwen25-7b-fp16-c$C.json"
    echo "### preempções acumuladas"
    kubectl exec -n vllm-estudo vllm-conc -- sh -c 'python3 -c "import urllib.request;print([l for l in urllib.request.urlopen(\"http://127.0.0.1:8000/metrics\").read().decode().splitlines() if l.startswith(\"vllm:num_preemptions_total\")])"'
  done
  echo "### GPU depois";  nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv
  echo "### arquivos de resultado";  ls -l /home/utec/vllm-estudo/hf-cache/bench/
} 2>&1 | tee B-001-concorrencia-$(hostname -s)-$(date +%F-%H%M).log
```

O que olhar, em cada nível de concorrência, na tabela que o `vllm bench serve` imprime:

- **`Output token throughput (tok/s)`:** a vazão total do servidor. Deve crescer com a concorrência até
  saturar.
- **TPOT / ITL (p50, p95, p99):** o tempo entre *tokens* que cada usuário sente. `1000 / TPOT em ms` dá os
  *tokens*/s por usuário.
- **TTFT (p50, p95, p99):** a espera até o primeiro *token*. Cresce quando as requisições entram em fila.
- **Preempções:** se subirem, o *KV cache* não comportou a concorrência.

Traga o log e os JSON (`scp` de `/home/utec/vllm-estudo/hf-cache/bench/*.json` de `sabdiia01`). O
resultado vira `medicoes/B-001-...md`.

**Bloco B executado em 2026-10-14 17:18:** resultado em
[medicoes/B-001-concorrencia-qwen25-7b-fp16.md](../medicoes/B-001-concorrencia-qwen25-7b-fp16.md). A vazão
escala 13×, mas os valores absolutos parecem estrangulados. Diagnóstico no Bloco C.

## Bloco C — Diagnóstico B-001b: a GPU ou a CPU está estrangulando? (servidor, bash, **em `sabdiia01`**)

Só leitura, mais uma rodada curta de carga: concorrência 1, 12 requisições, semente 101, uns 3 a 6 min.
Durante a carga, grava a cada 2 s temperatura, potência, *clock* e uso da GPU, e tira 3 fotos dos
motivos de redução de *clock* (`nvidia-smi -q -d PERFORMANCE`). Antes e depois, lê os contadores de
estrangulamento de CPU do *pod* (`cpu.stat` do *cgroup*).

**Expectativa escrita antes:** se for **temperatura**, o `clocks.sm` cai abaixo do `clocks.max.sm` com a
temperatura subindo, e a foto de PERFORMANCE mostra um motivo térmico ativo. Se for **CPU**, o
`nr_throttled` e o `throttled_usec` do *cgroup* sobem muito durante a rodada, e a GPU fica com uso baixo
e *clock* alto.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### $(date '+%F %T')";  kubectl get pod -n vllm-estudo vllm-conc -o wide
  echo "### CPU do pod: estrangulamento ANTES"
  kubectl exec -n vllm-estudo vllm-conc -- cat /sys/fs/cgroup/cpu.stat
  echo "### GPU parada"
  nvidia-smi --query-gpu=temperature.gpu,power.draw,power.limit,clocks.sm,clocks.max.sm,clocks.mem,utilization.gpu,pstate --format=csv
  nvidia-smi --query-gpu=timestamp,temperature.gpu,power.draw,clocks.sm,clocks.max.sm,utilization.gpu,pstate --format=csv -l 2 > gpu-amostras-b001b.csv &
  SMI=$!
  ( sleep 30; echo "=== foto 1 (30 s) ==="; nvidia-smi -q -d PERFORMANCE
    sleep 60; echo "=== foto 2 (90 s) ==="; nvidia-smi -q -d PERFORMANCE
    sleep 60; echo "=== foto 3 (150 s) ==="; nvidia-smi -q -d PERFORMANCE ) > gpu-performance-b001b.txt &
  FOT=$!
  echo "### rodada de carga: concorrência 1, 12 requisições"
  kubectl exec -n vllm-estudo vllm-conc -- sh -c "vllm bench serve --backend openai --base-url http://127.0.0.1:8000 --endpoint /v1/completions --model Qwen/Qwen2.5-7B-Instruct --dataset-name random --random-input-len 512 --random-output-len 256 --ignore-eos --temperature 0 --metric-percentiles 50,95,99 --seed 101 --max-concurrency 1 --num-prompts 12" | sed -n '/Serving Benchmark Result/,$p'
  wait $FOT
  kill $SMI
  echo "### CPU do pod: estrangulamento DEPOIS"
  kubectl exec -n vllm-estudo vllm-conc -- cat /sys/fs/cgroup/cpu.stat
  echo "### quantas threads o processo do vLLM abriu"
  for P in $(pgrep -f 'VLLM::EngineCore|vllm serve'); do echo "pid $P: $(ls /proc/$P/task | wc -l) threads"; done
  echo "### GPU durante a carga (amostras a cada 2 s)"
  cat gpu-amostras-b001b.csv
  echo "### motivos de redução de clock (3 fotos)"
  cat gpu-performance-b001b.txt
} 2>&1 | tee B-001b-diagnostico-$(hostname -s)-$(date +%F-%H%M).log
```

**Bloco C executado em 2026-10-14 18:32:** a GPU estrangula por temperatura (82 °C, *clock* de 1560 para
~400 MHz, `SW Thermal Slowdown: Active`); a CPU não é a causa ([AC-17](../ESTUDO-DE-CASO.md#ac-17)).

## Bloco D — Retrato térmico dos 3 nós (servidor, bash, **em cada um dos 3 nós**)

Só leitura, sem carga. Mostra as temperaturas de referência da GPU (a partir de quanto ela reduz o
*clock*), o estado atual e, se o `ipmitool` estiver instalado, as ventoinhas e sensores do servidor.
Serve para comparar os nós e para levar ao administrador (PD-24).

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### nó: $(hostname)   $(date '+%F %T')"
  echo "### GPU agora"
  nvidia-smi --query-gpu=temperature.gpu,power.draw,clocks.current.sm,clocks.max.sm,utilization.gpu,memory.used,pstate --format=csv
  echo "### limites de temperatura da GPU"
  nvidia-smi -q -d TEMPERATURE
  echo "### motivos de redução de clock agora"
  nvidia-smi -q -d PERFORMANCE | sed -n '/Clocks Event Reasons$/,/Display Clock/p'
  echo "### ventoinhas e temperaturas do servidor (ipmitool)"
  if command -v ipmitool >/dev/null; then ipmitool sdr type Fan; ipmitool sdr type Temperature; else echo "ipmitool nao instalado"; fi
} 2>&1 | tee termico-$(hostname -s)-$(date +%F-%H%M).log
```

**Bloco D executado em 2026-10-15:** limites iguais nos 3 nós (`GPU Max Operating Temp : 83 C`,
`Slowdown 87 C`, `Shutdown 90 C`); paradas, 01 a 67 °C, 02 a 31 °C, 03 a 60 °C; `ipmitool` ausente
nos 3 ([AC-17](../ESTUDO-DE-CASO.md#ac-17)).

O que olhar: a linha `GPU Slowdown Temp` (ou equivalente) de cada nó; a temperatura parada de cada GPU;
e, se houver `ipmitool`, a rotação das ventoinhas. Uma GPU bem refrigerada fica bem abaixo da
temperatura de redução mesmo com carga.

## Bloco E — Reteste térmico depois da intervenção do administrador (B-001c) (servidor, bash, **em `sabdiia01`**)

Em 2026-10-22 o administrador informou que revisou `sabdiia01` e fez ajustes de refrigeração (PD-24,
passo 2). Este bloco confere se a GPU agora sustenta o *clock* sob carga. **Só siga para o Bloco F se
ele passar.**

Duas fases de carga, com amostras da GPU a cada 2 s e uma foto dos motivos de redução de *clock* a cada
2 min durante toda a carga:

1. **Igual ao Bloco C** (concorrência 1, 12 requisições, semente 101): comparação direta com o antes.
2. **Carga pesada contínua** (concorrência 32, 512 requisições, semente 102): a GPU fica perto dos 250 W
   por vários minutos. O Bloco C durou só 3 min com uma requisição por vez; uma GPU que aguenta isso
   pode ainda estrangular depois de 5-10 min a plena potência.

Leva de 10 a 25 min. Se o *pod* `vllm-conc` não estiver `Ready` (o nó pode ter sido reiniciado), o bloco
para logo no início: rode o Bloco A e depois este.

**Expectativa escrita antes (critério da PD-24):** nas amostras com GPU em uso, *clock* do SM perto de
1597 MHz (nenhuma amostra abaixo de 1400 MHz), temperatura abaixo de 83 °C e **nenhuma foto com
`Slowdown ... : Active`**. Na fase 1, cada requisição em ~5-6 s, como a primeira da B-001b com a GPU
ainda fria (antes da intervenção: de 5,6 s para 21,8 s).

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### nó: $(hostname)   $(date '+%F %T')"
  kubectl get pod -n vllm-estudo vllm-conc -o wide
  RD=$(kubectl get pod -n vllm-estudo vllm-conc -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null)
  if [ "$RD" != "true" ]; then
    echo "### ABORTADO: o pod vllm-conc não está Ready. Rode o Bloco A e depois repita este bloco."
  else
    echo "### processos na GPU (deve haver só o vLLM)"
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
    echo "### GPU parada"
    nvidia-smi --query-gpu=temperature.gpu,power.draw,power.limit,clocks.sm,clocks.max.sm,utilization.gpu,pstate --format=csv
    nvidia-smi -q -d PERFORMANCE
    nvidia-smi --query-gpu=timestamp,temperature.gpu,power.draw,clocks.sm,clocks.max.sm,utilization.gpu,pstate --format=csv -l 2 > gpu-amostras-b001c.csv &
    SMI=$!
    touch carga-b001c.ativa
    ( n=0; while [ -f carga-b001c.ativa ]; do sleep 120; n=$((n+1)); echo "=== foto $n ($(date +%T)) ==="; nvidia-smi -q -d PERFORMANCE; done ) > gpu-performance-b001c.txt &
    FOT=$!
    M=$(kubectl exec -n vllm-estudo vllm-conc -- python3 -c "import json,urllib.request;print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/models'))['data'][0]['id'])")
    echo "### nome do modelo servido (lido em /v1/models): $M"
    B="vllm bench serve --backend openai --base-url http://127.0.0.1:8000 --endpoint /v1/completions --model $M --dataset-name random --random-input-len 512 --random-output-len 256 --ignore-eos --temperature 0 --metric-percentiles 50,95,99"
    echo "### fase 1, igual ao Bloco C: concorrência 1, 12 requisições, semente 101   início $(date +%T)"
    kubectl exec -n vllm-estudo vllm-conc -- sh -c "$B --seed 101 --max-concurrency 1 --num-prompts 12" | sed -n '/Serving Benchmark Result/,$p'
    echo "### fase 2, carga contínua: concorrência 32, 512 requisições, semente 102   início $(date +%T)"
    kubectl exec -n vllm-estudo vllm-conc -- sh -c "$B --seed 102 --max-concurrency 32 --num-prompts 512" | sed -n '/Serving Benchmark Result/,$p'
    echo "### fim da carga   $(date +%T)"
    rm -f carga-b001c.ativa
    wait $FOT
    kill $SMI
    echo "### RESUMO: amostras com a GPU em uso (utilization >= 90 %)"
    awk -F', ' 'NR>1 && $6+0>=90 {n++; t=$2+0; c=$4+0; if(n==1||t>tmax)tmax=t; if(n==1||c<cmin)cmin=c; s+=c; if(c<1400)baixo++} END {printf "amostras: %d | temp. max: %d C | clock min: %d MHz | clock medio: %.0f MHz | amostras com clock < 1400 MHz: %d\n", n, tmax, cmin, (n?s/n:0), baixo+0}' gpu-amostras-b001c.csv
    echo "### RESUMO: fotos com algum Slowdown ativo: $(grep -c '=== foto' gpu-performance-b001c.txt) fotos no total; linhas ativas abaixo (vazio = nenhuma)"
    grep -E '=== foto|Slowdown.*: Active' gpu-performance-b001c.txt
    echo "### GPU durante a carga (amostras a cada 2 s)"
    cat gpu-amostras-b001c.csv
    echo "### motivos de redução de clock (fotos a cada 2 min)"
    cat gpu-performance-b001c.txt
  fi
} 2>&1 | tee B-001c-reteste-termico-$(hostname -s)-$(date +%F-%H%M).log
```

O que olhar: as duas linhas `### RESUMO` e os contadores (`Clocks Event Reasons Counters`) nas fotos.
**Passou** se a temperatura máxima ficou abaixo de 83 °C, nenhuma linha `Slowdown ... : Active` e o
contador `SW Thermal Slowdown` não cresceu. A contagem de amostras abaixo de 1400 MHz é só indício: a
V100S varia o *clock* com a carga sem estrangular (critério corrigido depois da execução, §9).

**Bloco E executado em 2026-10-22 15:52: passou.** Parada a 31 °C; máx. 72 °C a 240-250 W; contador
`SW Thermal Slowdown` em 0 µs. 33 amostras abaixo de 1400 MHz, a cada ~12 s e com potência menor, sem
estrangulamento. Concorrência 1: 47,0 *tok*/s; concorrência 32: 680,4 *tok*/s
([AC-17](../ESTUDO-DE-CASO.md#ac-17); [log](../logs-analysis/B-001c-reteste-termico-sabdiia01-2026-10-22-1552.log)).

## Bloco F — Medição B-002: concorrência 1 a 64 com a GPU refrigerada (servidor, bash, **em `sabdiia01`**)

**Só depois de o Bloco E passar.** É o Bloco B repetido sem mudar nada no servidor nem na carga (mesmas
sementes, mesmos níveis), para comparar com a B-001. Duas diferenças, só de registro: os resultados
ganham o nome `B-002-...` (não sobrescrevem os da B-001) e a GPU é amostrada a cada 2 s durante toda a
medição, como pede o checklist de medições. Leva de 20 a 40 min.

**Expectativa escrita antes:** com concorrência 1, ~30-45 *tokens*/s por usuário (o *warmup* da B-001,
ainda frio, teve ITL p50 de 29 ms, ~34 *tok*/s), contra 10,7 na B-001. A vazão total continua subindo até
64, e os valores absolutos ficam de 2 a 4 vezes acima dos da B-001 `[hipótese]`.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### $(date '+%F %T')";  kubectl get pod -n vllm-estudo vllm-conc -o wide
  echo "### GPU antes (só o vLLM deve aparecer)"
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
  nvidia-smi --query-gpu=temperature.gpu,power.draw,clocks.sm,clocks.max.sm,utilization.gpu,pstate --format=csv
  echo "### contadores de redução de clock ANTES"
  nvidia-smi -q -d PERFORMANCE | sed -n '/Clocks Event Reasons Counters/,/HW Power Braking/p'
  nvidia-smi --query-gpu=timestamp,temperature.gpu,power.draw,clocks.sm,clocks.max.sm,utilization.gpu,pstate --format=csv -l 2 > gpu-amostras-b002.csv &
  SMI=$!
  touch carga-b002.ativa
  ( n=0; while [ -f carga-b002.ativa ]; do sleep 120; n=$((n+1)); echo "=== foto $n ($(date +%T)) ==="; nvidia-smi -q -d PERFORMANCE; done ) > gpu-performance-b002.txt &
  FOT=$!
  M=$(kubectl exec -n vllm-estudo vllm-conc -- python3 -c "import json,urllib.request;print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/models'))['data'][0]['id'])")
  echo "### nome do modelo servido (lido em /v1/models): $M"
  B="vllm bench serve --backend openai --base-url http://127.0.0.1:8000 --endpoint /v1/completions --model $M --dataset-name random --random-input-len 512 --random-output-len 256 --ignore-eos --temperature 0 --metric-percentiles 50,95,99"
  echo "### aquecimento (descartado): concorrência 4, 16 requisições, semente 999"
  kubectl exec -n vllm-estudo vllm-conc -- sh -c "$B --seed 999 --max-concurrency 4 --num-prompts 16" | tail -5
  for C in 1 4 8 16 32 64; do
    N=$((C * 8)); [ "$N" -lt 32 ] && N=32
    echo "############ concorrência $C, $N requisições, semente $C, $(date +%T) ############"
    kubectl exec -n vllm-estudo vllm-conc -- sh -c "$B --seed $C --max-concurrency $C --num-prompts $N --save-result --result-dir /hf-cache/bench --result-filename B-002-qwen25-7b-fp16-c$C.json"
    echo "### preempções acumuladas"
    kubectl exec -n vllm-estudo vllm-conc -- sh -c 'python3 -c "import urllib.request;print([l for l in urllib.request.urlopen(\"http://127.0.0.1:8000/metrics\").read().decode().splitlines() if l.startswith(\"vllm:num_preemptions_total\")])"'
  done
  echo "### fim da carga   $(date +%T)"
  rm -f carga-b002.ativa
  wait $FOT
  kill $SMI
  echo "### RESUMO: amostras com a GPU em uso (utilization >= 90 %)"
  awk -F', ' 'NR>1 && $6+0>=90 {n++; t=$2+0; c=$4+0; if(n==1||t>tmax)tmax=t; if(n==1||c<cmin)cmin=c; s+=c; if(c<1400)baixo++} END {printf "amostras: %d | temp. max: %d C | clock min: %d MHz | clock medio: %.0f MHz | amostras com clock < 1400 MHz: %d\n", n, tmax, cmin, (n?s/n:0), baixo+0}' gpu-amostras-b002.csv
  echo "### RESUMO: fotos com algum Slowdown ativo: $(grep -c '=== foto' gpu-performance-b002.txt) fotos no total; linhas ativas abaixo (vazio = nenhuma)"
  grep -E '=== foto|Slowdown.*: Active' gpu-performance-b002.txt
  echo "### contadores de redução de clock DEPOIS (compare com ANTES: SW Thermal Slowdown deve ficar igual)"
  nvidia-smi -q -d PERFORMANCE | sed -n '/Clocks Event Reasons Counters/,/HW Power Braking/p'
  echo "### GPU depois";  nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv
  echo "### arquivos de resultado";  ls -l /home/utec/vllm-estudo/hf-cache/bench/
  echo "### GPU durante a medição (amostras a cada 2 s)"
  cat gpu-amostras-b002.csv
  echo "### motivos de redução de clock (fotos a cada 2 min)"
  cat gpu-performance-b002.txt
} 2>&1 | tee B-002-concorrencia-$(hostname -s)-$(date +%F-%H%M).log
```

Traga o log e os JSON `B-002-*.json` de `/home/utec/vllm-estudo/hf-cache/bench/` por `scp`. Se o contador
`SW Thermal Slowdown` crescer entre ANTES e DEPOIS, ou alguma foto mostrar `Slowdown` ativo, a B-002 também
fica sob suspeita térmica.

## Limpeza (servidor, bash, qualquer nó com `kubectl`)

```bash
kubectl delete pod -n vllm-estudo vllm-conc
```
