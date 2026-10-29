# Runbook — Medição B-003: o Llama-3.1-8B dividido em 3 nós pelo Ray (*pipeline parallel* 3)

**Pergunta:** quanto entrega, em *tokens*/s e em tempo por *token*, o arranjo que o administrador quer levar
ao MVP? É o `meta-llama/Meta-Llama-3.1-8B-Instruct` no vLLM `0.5.4` com `--pipeline-parallel-size 3`, um
pedaço por nó, executor Ray ([AC-19](../ESTUDO-DE-CASO.md#ac-19)). **Decisão que destrava:** se o Ray com
divisão entre nós vira o arranjo do MVP ou se fica D-04 (réplicas de 1 GPU por nó, sem Ray). Fecha a parte
medível da PD-31.

**Quem executa:** o usuário, **avisando o administrador antes**. A carga ocupa a API do Ray por ~20-40 min
`[estimativa]`, e ninguém mais deve usá-la nesse tempo: requisições de fora entram na medida.

## Desenho

- **Carga igual à B-001c** (mesmo gerador `vllm bench serve` da `v0.19.1`, mesmas *flags*): *prompts*
  aleatórios de 512 *tokens*, 256 de saída exatos (`--ignore-eos`), `temperature 0`, p50/p95/p99.
  Mesmas sementes da B-001c nas fases comparáveis: **c=1, 12 requisições, semente 101** e **c=32, 512
  requisições, semente 102**. Uma fase a mais, **c=16** (o `--max-num-seqs 16` do servidor do Ray), com
  semente 116. *Warmup* de 16 requisições a c=4, semente 999, como no Bloco B.
- **Gerador:** *pod* `bench-ray` em `vllm-estudo`, **sem GPU**, com `hostNetwork: true`, em `sabdiia01`, o
  mesmo nó do *head*. Com `hostNetwork`, a requisição não passa pela rede de *pods* de 01, que tem o
  problema de DNS da PD-28 `[hipótese de que contornaria]`, e vai ao IP do próprio nó.
- **Tokenizer:** copiado do *head* do Ray, só lendo os arquivos (`cat`), para o gerador contar *tokens*
  igual ao servidor. O modelo é *gated*, e o *pod* do estudo não tem *token* válido (AC-07); com a cópia,
  `HF_HUB_OFFLINE=1`.
- **Temperatura:** amostras de temperatura, *clock*, potência e uso das 3 GPUs a cada ~5 s, lidas de dentro
  dos *pods* do Ray. No fim, os contadores de `nvidia-smi -q -d PERFORMANCE` (AC-17).

**O que NÃO é uma variável só.** Contra a B-001c (`Qwen2.5-7B-Instruct`, `v0.19.1`, 1 GPU, *CUDA graphs*),
mudam quatro coisas: modelo, versão, número de GPUs e `--enforce-eager`. A B-003 mede **o arranjo do
administrador como ele está**, não o efeito isolado da divisão. A comparação justa (o mesmo Llama-3.1-8B
na `v0.19.1` em 1 GPU) exige uma GPU livre, que hoje não existe (AC-19). Registre a B-003 com essa ressalva.

## Expectativa (escrita antes)

- **c=1:** tempo por *token* (TPOT) **maior** que os 20,3 ms da B-001c. O *token* atravessa os 3 nós um
  depois do outro, e `--enforce-eager` tira os *CUDA graphs* `[hipótese]`.
- **c=32:** vazão total **abaixo** dos 680 *tok*/s da B-001c. O servidor do Ray aceita só 16 sequências por
  vez; as outras 16 esperam na fila, e isso aparece no TTFT `[hipótese]`.
- GPUs de 02 e 03 com uso **abaixo** de 01 sob carga, com cada estágio esperando o anterior `[hipótese]`.
- Se o c=32 passar de 680 *tok*/s, a expectativa estava errada e o arranjo merece medida justa com o
  mesmo modelo em 1 GPU antes de qualquer decisão.

## Bloco — servidor `sabdiia01`, bash (aborta em outro nó)

Não para nem altera nada do Ray: lê arquivos do *head* e manda requisições à API. Cria e, no fim, apaga o
*pod* `bench-ray` (só em `vllm-estudo`). O primeiro uso baixa a `v0.19.1` em 01 (~30 G em `/`, 580 G livres
desde 2026-10-28, AC-09).

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  API=http://192.168.50.151:8000
  M=meta-llama/Meta-Llama-3.1-8B-Instruct
  RAY="ray-head ray-worker-2 ray-worker-3"

  echo "### 1. a API do Ray responde e serve o modelo?"
  curl -s -m 10 "$API/v1/models" | head -c 600; echo
  curl -s -m 10 "$API/v1/models" | grep -q "$M" || { echo "ABORTA: a API do Ray não serve $M"; exit 1; }

  echo "### 1b. a v0.5.4 respeita ignore_eos e devolve usage? (esperado: completion_tokens 256)"
  U=$(curl -s -m 180 "$API/v1/completions" -H 'Content-Type: application/json' \
    -d '{"model":"meta-llama/Meta-Llama-3.1-8B-Instruct","prompt":"Diga oi.","max_tokens":256,"temperature":0,"ignore_eos":true}' \
    | grep -oE '"usage": *\{[^}]*\}')
  echo "$U"
  echo "$U" | grep -qE '"completion_tokens": *256' || { echo "ABORTA: a resposta não teve 256 tokens; ignore_eos não respeitado, e a vazão sairia inflada"; exit 1; }

  echo "### 2. GPUs antes (uso deve estar em 0 %: ninguém mais usando a API)"
  for d in $RAY; do echo "$d: $(kubectl exec -n vllms deploy/$d -- nvidia-smi --query-gpu=temperature.gpu,clocks.sm,power.draw,utilization.gpu,memory.used --format=csv,noheader 2>&1)"; done

  echo "### 3. tokenizer do Llama, lido do head do Ray (só leitura)"
  P=$(kubectl get pods -n vllms -l app=ray-head -o jsonpath='{.items[0].metadata.name}')
  TD=$(kubectl exec -n vllms "$P" -- sh -c 'dirname "$(find /root/.cache/huggingface -path "*Meta-Llama-3.1-8B-Instruct*" -name tokenizer.json | head -1)"')
  echo "pod: $P   pasta: $TD"
  mkdir -p llama31-tok
  for f in tokenizer.json tokenizer_config.json special_tokens_map.json config.json generation_config.json; do
    kubectl exec -n vllms "$P" -- cat "$TD/$f" > "llama31-tok/$f"
  done
  ls -la llama31-tok
  [ -s llama31-tok/tokenizer.json ] || { echo "ABORTA: tokenizer não copiado"; exit 1; }

  echo "### 4. pod gerador de carga, sem GPU, em sabdiia01"
  kubectl create namespace vllm-estudo --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: bench-ray
  namespace: vllm-estudo
spec:
  nodeSelector:
    kubernetes.io/hostname: sabdiia01
  hostNetwork: true
  restartPolicy: Never
  containers:
  - name: bench
    image: vllm/vllm-openai:v0.19.1
    command: ["sleep", "infinity"]
    env:
    - name: HF_HUB_OFFLINE
      value: "1"
    resources:
      requests: {cpu: "4", memory: 8Gi}
      limits: {cpu: "8", memory: 16Gi}
EOF
  echo "aguardando o pod (o primeiro uso baixa a imagem): $(date +%T)"
  kubectl wait -n vllm-estudo --for=condition=Ready pod/bench-ray --timeout=1800s || {
    kubectl describe pod -n vllm-estudo bench-ray | tail -20; echo "ABORTA: pod gerador não ficou Ready"; exit 1; }
  echo "Ready: $(date +%T)"; df -h /
  kubectl cp llama31-tok vllm-estudo/bench-ray:/tmp/llama31-tok
  echo "### 5. o gerador funciona sem GPU e tem as flags usadas?"
  kubectl exec -n vllm-estudo bench-ray -- sh -c 'vllm bench serve --help 2>&1 | grep -oE -- "--(tokenizer|base-url|ignore-eos|max-concurrency) " | sort -u'

  B="vllm bench serve --backend openai --base-url $API --endpoint /v1/completions --model $M --tokenizer /tmp/llama31-tok --dataset-name random --random-input-len 512 --random-output-len 256 --ignore-eos --temperature 0 --metric-percentiles 50,95,99"

  echo "### 6. amostras das 3 GPUs a cada ~5 s -> gpu-amostras-b003.csv"
  ( while true; do for d in $RAY; do echo "$(date +%T),$d,$(kubectl exec -n vllms deploy/$d -- nvidia-smi --query-gpu=temperature.gpu,power.draw,clocks.sm,utilization.gpu,memory.used --format=csv,noheader 2>&1)"; done; sleep 5; done ) > gpu-amostras-b003.csv &
  AM=$!

  echo "### 7. warmup: c=4, 16 requisições, semente 999   $(date +%T)"
  kubectl exec -n vllm-estudo bench-ray -- sh -c "$B --seed 999 --max-concurrency 4 --num-prompts 16" | tail -8

  for F in "1 12 101" "16 256 116" "32 512 102"; do
    set -- $F
    echo "### fase c=$1, $2 requisições, semente $3   início $(date +%T)"
    kubectl exec -n vllm-estudo bench-ray -- sh -c "$B --seed $3 --max-concurrency $1 --num-prompts $2 --save-result --result-dir /tmp/bench --result-filename B-003-ray-pp3-c$1.json" | sed -n '/Serving Benchmark Result/,$p'
  done

  kill $AM 2>/dev/null
  echo "### 8. GPUs depois e contadores de estrangulamento"
  for d in $RAY; do
    echo "## $d: $(kubectl exec -n vllms deploy/$d -- nvidia-smi --query-gpu=temperature.gpu,clocks.sm,power.draw,utilization.gpu --format=csv,noheader 2>&1)"
    kubectl exec -n vllms deploy/$d -- nvidia-smi -q -d PERFORMANCE 2>&1 | grep -iE 'thermal|slowdown|power cap'
  done
  echo "### máximos das amostras (temperatura, clock mínimo) por GPU"
  for d in $RAY; do grep ",$d," gpu-amostras-b003.csv | awk -F', *' -v d=$d '$3+0>0 {n++; t=$3+0; c=$5+0; if(t>mt)mt=t; if(mc==""||c<mc)mc=c} END{print d": temp máx "mt" C, clock mín "mc" MHz, amostras válidas "n}'; done

  echo "### 9. resultados JSON para a estação e limpeza do pod gerador"
  mkdir -p B-003-bench; kubectl cp vllm-estudo/bench-ray:/tmp/bench B-003-bench; ls -la B-003-bench
  kubectl delete pod -n vllm-estudo bench-ray --wait=false
  echo "== fim $(date -Is)"
} 2>&1 | tee B-003-ray-pp3-$(hostname -s)-$(date +%F-%H%M).log
```

Traga para `logs-analysis/` o `.log`, o `gpu-amostras-b003.csv` e a pasta `B-003-bench/`.

## O que olhar

| Fase | Compare com a B-001c | O que decide |
|---|---|---|
| c=1 | TPOT p50 (20,3 ms) e *tok*/s (47,0) | se um usuário sozinho sente o arranjo mais lento |
| c=16 | — | o teto do servidor do Ray (`--max-num-seqs 16`) |
| c=32 | vazão total (680,4 *tok*/s) e TTFT p99 | quantos usuários simultâneos o arranjo aguenta |

**Confira os totais antes de qualquer número** (o tamanho é garantido pelo gerador: entrada montada com
o *tokenizer* do Llama e conferida depois de decodificar, saída com `max_tokens 256` + `ignore_eos` [F-032]):

| Fase | `Total input tokens` esperado | `Total generated tokens` esperado |
|---|---|---|
| c=1 (12) | 6.144 | 3.072 |
| c=16 (256) | 131.072 | 65.536 |
| c=32 (512) | 262.144 | 131.072 |

`Total generated tokens` abaixo do esperado = respostas curtas (`ignore_eos` não respeitado) e vazão inflada:
a fase não vale. No log, o aviso `tokens than expected after decoding and re-encoding` indica entrada fora de 512.

Confira também: alguma requisição falhou (`Failed requests`)? Alguma GPU estrangulou (contador de
`SW Thermal Slowdown` ativo, *clock* mínimo bem abaixo dos ~1500 MHz)? Se sim, o número é da
refrigeração daquele nó, não do arranjo (AC-17).
