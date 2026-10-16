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

## Limpeza (servidor, bash, qualquer nó com `kubectl`)

```bash
kubectl delete pod -n vllm-estudo vllm-conc
```
