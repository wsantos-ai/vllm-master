# Runbook — `Qwen/Qwen3.8-27B` com bitsandbytes 4 bits na V100S

**Pergunta (PD-16):** o modelo pedido sobe na `v0.19.1` com `--quantization bitsandbytes` numa V100S de
32 GB? Quanto de GPU usa, quanto demora para carregar e a que velocidade gera?
Contexto: [AC-12](../ESTUDO-DE-CASO.md#ac-12), [AC-13](../ESTUDO-DE-CASO.md#ac-13).

**Expectativa escrita antes:** o *download* de 55,6 GB leva uns 30 min (a imagem veio a ~30 MB/s); o
carregamento quantiza para 4 bits e ocupa perto de 14 a 18 GB de GPU só de *weights*; o *pod* fica
`Ready`; a geração responde, mais devagar que um modelo em FP16. Pontos em que pode cair: o `transformers`
5.5.4 não reconhecer a configuração do modelo, o bitsandbytes não suportar esta arquitetura multimodal,
ou falta de memória.

## Histórico das tentativas

| # | Quando | Mudança em relação à anterior | Resultado |
|---|---|---|---|
| 1 | 2026-10-02 14:36 | — (`--quantization bitsandbytes`, `--dtype float16`, `--max-model-len 8192`, `0.90`) | carregou em 18,06 GiB; **caiu** aos 22 min com `CUDA out of memory` em `profile_cudagraph_memory` (AC-14) |
| 2 | 2026-10-02 15:09 | **só** `--enforce-eager` | **`pod Ready`** em 12 min 24 s; *KV cache* 5,0 GiB = 20.384 *tokens*; 200 *tokens* em 71,1 s (~3 *tokens*/s); raciocínio veio dentro de `content` (AC-14) |

**Tentativa 2, o bloco abaixo.** Uma variável muda: `--enforce-eager`. No código da `v0.19.1`, a etapa
que estourou só roda quando `enforce_eager` é falso ([F-014](../FONTES.md)).

**Expectativa da tentativa 2, escrita antes:** sem *download* (o modelo já está em `/home`, 53 G); o
carregamento chega de novo a ~18 GiB; a etapa de *CUDA graphs* é pulada; o *KV cache* fica com o que
sobrar de 0,90 × 31,73 GiB depois do pico de ~25 GiB visto na tentativa 1, ou seja, uns 3 GiB
`[cálculo]`. Dois desfechos possíveis: `pod Ready` com *KV cache* pequeno, ou erro dizendo que o *KV
cache* não comporta 8192 *tokens*. Nesse caso a tentativa 3 muda uma coisa só: desligar a entrada de
imagens ou reduzir `--max-model-len`. O *warmup* pode levar de novo uns 9 min.

**Já conferido (2026-10-02):** a imagem `v0.19.1` traz `bitsandbytes 0.49.2`, `transformers 5.5.4` e
`torch 2.10.0+cu129`; a flag `--quantization bitsandbytes` está na documentação da versão ([F-013](../FONTES.md)).

| Item | Valor | Por quê |
|---|---|---|
| Nó | `sabdiia01` | já tem a imagem `v0.19.1`; nenhum *download* de imagem (D-02) |
| *Pod* | `vllm-qwen38`, `restartPolicy: Never`, sem `livenessProbe` | se cair, fica parado com o log; nada mata o *pod* durante o carregamento longo |
| Cache do modelo | `/home/utec/vllm-estudo/hf-cache` no nó (755 G livres) | 55,6 GB não cabem em `/`, que tem 17 G livres |
| `--max-model-len` | `8192` | o contexto nativo é 262.144 e não caberia no *KV cache* |
| `HF_TOKEN` | nenhum | modelo público; o *token* do *cluster* é inválido (AC-07) |
| Exposição | nenhuma; teste por `kubectl port-forward` | AC-06 |
| Memória do *pod* | 32 a 96 Gi | o carregamento passa os *weights* pela RAM antes de quantizar |

**O que este bloco altera:** apaga o *pod* de teste `vllm-teste` (libera a GPU de `sabdiia01`) e cria o
`vllm-qwen38`, tudo no *namespace* `vllm-estudo`. Não toca em `vllms`. Baixa 55,6 GB da internet para
`/home` do nó.

**Não interrompa com Ctrl+C:** o *pod* e o *download* continuam sozinhos. Para parar, use
`kubectl delete pod -n vllm-estudo vllm-qwen38`.

---

## Passo 1 — Arranque e teste (servidor, bash, **em `sabdiia01`**)

Espera até 100 min. A cada 15 s grava: G livres em `/`, tamanho do cache do modelo, memória da GPU e
estado do *pod*. Para sozinho se `/` cair a 12 G livres.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  livre() { df --output=avail -BG / | tail -1 | tr -dc 0-9; }
  echo "### nó: $(hostname)   início: $(date '+%F %T')   livres em /: $(livre)G"
  echo "### /home";  df -h /home
  if [ "$(livre)" -lt 14 ]; then
    echo "### ABORTADO: menos de 14G livres em /. Nada foi alterado."
  else
    echo "### liberando a GPU: apagando o pod de teste anterior"
    kubectl delete pod -n vllm-estudo vllm-teste --ignore-not-found --wait=true
    kubectl delete pod -n vllm-estudo vllm-qwen38 --ignore-not-found --wait=true
    kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: vllm-qwen38
  namespace: vllm-estudo
  labels:
    app: vllm-qwen38
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: sabdiia01
  containers:
  - name: vllm
    image: vllm/vllm-openai:v0.19.1
    command: ["vllm", "serve"]
    args:
    - Qwen/Qwen3.8-27B
    - --quantization
    - bitsandbytes
    - --dtype
    - float16
    - --max-model-len
    - "8192"
    - --gpu-memory-utilization
    - "0.90"
    - --enforce-eager
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
        cpu: "4"
        memory: 32Gi
        nvidia.com/gpu: 1
      limits:
        cpu: "8"
        memory: 96Gi
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
      sizeLimit: 4Gi
EOF
    echo "### linha do tempo (a cada 15 s): hora | G livres em / | cache do modelo | GPU MiB | fase | ready"
    PARADA="tempo esgotado (100 min)"
    for i in $(seq 1 400); do
      L=$(livre)
      C=$(du -sh /home/utec/vllm-estudo/hf-cache 2>/dev/null | cut -f1)
      G=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
      PH=$(kubectl get pod -n vllm-estudo vllm-qwen38 -o jsonpath='{.status.phase}' 2>/dev/null)
      RD=$(kubectl get pod -n vllm-estudo vllm-qwen38 -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null)
      echo "$(date +%T) | ${L}G | ${C:--} | ${G:--} | ${PH:--} | ${RD:--}"
      if [ "$L" -le 12 ]; then PARADA="FREIO DE DISCO: ${L}G livres em /"; kubectl delete pod -n vllm-estudo vllm-qwen38 --wait=false; break; fi
      if [ "$RD" = "true" ]; then PARADA="pod Ready"; break; fi
      if [ "$PH" = "Failed" ] || [ "$PH" = "Succeeded" ]; then PARADA="contêiner terminou (fase $PH)"; break; fi
      sleep 15
    done
    echo "### PARADA: $PARADA   em $(date '+%F %T')"
    echo "### estado e eventos"
    kubectl get pod -n vllm-estudo vllm-qwen38 -o wide
    kubectl describe pod -n vllm-estudo vllm-qwen38 | sed -n '/^Events:/,$p'
    echo "### estado do contêiner (código de saída, OOMKilled)"
    kubectl get pod -n vllm-estudo vllm-qwen38 -o jsonpath='{.status.containerStatuses[0].state}{"\n"}{.status.containerStatuses[0].lastState}{"\n"}'
    echo "### disco e cache";  df -h / /home;  du -sh /home/utec/vllm-estudo/hf-cache
    echo "### GPU";            nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv
    if [ "$PARADA" = "pod Ready" ]; then
      echo "### teste de geração (chat, 200 tokens, tempo total no fim)"
      kubectl port-forward -n vllm-estudo pod/vllm-qwen38 18000:8000 >/dev/null 2>&1 &
      PF=$!
      sleep 3
      curl -s --max-time 10 http://localhost:18000/v1/models; echo
      curl -s --max-time 600 -w '\n### tempo total da requisição: %{time_total} s\n' http://localhost:18000/v1/chat/completions \
        -H 'Content-Type: application/json' \
        -d '{"model":"Qwen/Qwen3.8-27B","messages":[{"role":"user","content":"Explique em três frases o que é um servidor de inferência de LLM."}],"max_tokens":200,"temperature":0}'
      echo "### métricas do vLLM depois da requisição"
      curl -s --max-time 10 http://localhost:18000/metrics | grep -E '^vllm:(time_to_first_token_seconds_sum|time_per_output_token_seconds_sum|time_per_output_token_seconds_count|generation_tokens_total|prompt_tokens_total|e2e_request_latency_seconds_sum)'
      kill $PF
      echo "### GPU depois da geração";  nvidia-smi --query-gpu=memory.used,memory.total --format=csv
    fi
    echo "### linhas-chave do arranque"
    kubectl logs -n vllm-estudo vllm-qwen38 | grep -iE 'version|backend|quantiz|bitsandbytes|dtype|architecture|KV cache|Model loading took|Time spent downloading|CUDA graph|init engine|error|Traceback|out of memory|not supported' | cut -c1-400
    echo "### log completo"
    kubectl logs -n vllm-estudo vllm-qwen38
  fi
} 2>&1 | tee teste-qwen38-27b-bnb-$(hostname -s)-$(date +%F-%H%M).log
```

O que olhar:

- **`### PARADA`:** `pod Ready` é o sucesso. `contêiner terminou (fase Failed)` traz a causa no log:
  procure a última exceção.
- **Linha do tempo:** o cache do modelo crescendo até ~52 G (*download*), depois a GPU subindo
  (quantização e carga). Dá o tempo de cada fase.
- **GPU MiB com o modelo carregado**, e o tamanho do *KV cache* no log: dizem quanto contexto e quanta
  concorrência cabem.
- **Geração:** `usage.completion_tokens` dividido pelo tempo total dá a ordem de grandeza de *tokens* por
  segundo. É **uma** requisição: não é medição, só indica se a velocidade é utilizável.

## Passo 1b — Alavancas que não exigem reiniciar o *pod* (servidor, bash, qualquer nó com `kubectl`)

Usa o `vllm-qwen38` que já está no ar (tentativa 2). Mede duas coisas, sem mudar nada no *pod*:

1. **Concorrência.** Com 1, 4 e 8 requisições simultâneas, quantos *tokens*/s cada usuário vê e quantos o
   servidor entrega no total. O bitsandbytes descompacta os pesos a cada passo; com mais requisições no
   mesmo lote, esse custo se divide `[hipótese]`.
2. **Raciocínio desligado** na requisição (`chat_template_kwargs` com `enable_thinking: false`). Não muda
   *tokens*/s, mas encurta o tempo até a resposta útil. O bloco confere antes se o *template* do modelo
   usa `enable_thinking`.

**Expectativa escrita antes:** com 1 requisição, ~3 *tokens*/s (AC-14). Com 4 e 8, a vazão total sobe
bem mais que a de cada usuário cai. A resposta sem raciocínio não traz `</think>`.

Leva até uns 15 min. Medidas com poucas requisições e sem repetição: **ordem de grandeza, não medição
[B-xxx]**.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### $(date '+%F %T')";  kubectl get pod -n vllm-estudo vllm-qwen38 -o wide
  echo "### o template de chat do modelo usa enable_thinking?"
  kubectl exec -n vllm-estudo vllm-qwen38 -- sh -c 'grep -l "enable_thinking" /hf-cache/hub/models--Qwen--Qwen3.8-27B/snapshots/*/* 2>/dev/null || echo "enable_thinking NAO encontrado"'
  kubectl port-forward -n vllm-estudo pod/vllm-qwen38 18000:8000 >/dev/null 2>&1 &
  PF=$!
  sleep 3
  echo "### resposta com o raciocínio desligado (100 tokens)"
  curl -s --max-time 900 -w '\n### tempo: %{time_total} s\n' http://localhost:18000/v1/chat/completions -H 'Content-Type: application/json' \
    -d '{"model":"Qwen/Qwen3.8-27B","messages":[{"role":"user","content":"Explique em três frases o que é um servidor de inferência de LLM."}],"max_tokens":100,"temperature":0,"chat_template_kwargs":{"enable_thinking":false}}'
  echo "### concorrência: N requisições simultâneas de 100 tokens, raciocínio desligado"
  echo "### N | tokens gerados | segundos | tokens/s total | tokens/s por usuário"
  for N in 1 4 8; do
    rm -f resp_qwen38_*.json
    T0=$(date +%s.%N)
    PIDS=""
    for i in $(seq 1 $N); do
      curl -s --max-time 900 http://localhost:18000/v1/chat/completions -H 'Content-Type: application/json' \
        -d "{\"model\":\"Qwen/Qwen3.8-27B\",\"messages\":[{\"role\":\"user\",\"content\":\"Pergunta $i: descreva com detalhes como funciona o KV cache em modelos de linguagem.\"}],\"max_tokens\":100,\"temperature\":0,\"chat_template_kwargs\":{\"enable_thinking\":false}}" > resp_qwen38_$i.json &
      PIDS="$PIDS $!"
    done
    wait $PIDS
    T1=$(date +%s.%N)
    TOK=$(cat resp_qwen38_*.json | grep -o '"completion_tokens":[0-9]*' | cut -d: -f2 | awk '{s+=$1} END {print s+0}')
    awk -v n=$N -v t=$TOK -v a=$T0 -v b=$T1 'BEGIN {d=b-a; printf "%d | %d | %.1f | %.2f | %.2f\n", n, t, d, t/d, t/d/n}'
  done
  echo "### métricas do vLLM ao final"
  curl -s --max-time 10 http://localhost:18000/metrics | grep -E '^vllm:(generation_tokens_total|num_preemptions_total|request_success_total)'
  kill $PF
  echo "### linhas do motor durante o teste"
  kubectl logs -n vllm-estudo vllm-qwen38 --since=20m | grep -E 'Avg generation throughput' | tail -20
} 2>&1 | tee alavancas-qwen38-$(date +%F-%H%M).log
```

## Alavancas que exigem reiniciar o *pod* (uma por vez, depois do Passo 1b)

| # | Mudança | O que pode ganhar | Base |
|---|---|---|---|
| R1 | Tirar `--enforce-eager` e fixar o *KV cache* com `--kv-cache-memory-bytes 4294967296` (4 GiB) | **voltar a ter *CUDA graphs***, o que pode acelerar cada *token* `[hipótese]`: a CPU é de 2012 e, em modo *eager*, cada passo lança muitos *kernels* pequenos | com `kv_cache_memory_bytes` definido, `determine_available_memory` retorna antes da etapa que estourou na tentativa 1 ([F-014]); flag `--kv-cache-memory-bytes` conferida na `v0.19.1` em 2026-10-13. Risco: a captura dos grafos não caber em memória |
| R2 | `--limit-mm-per-prompt '{"image": 0, "video": 0}'` | libera a memória que o codificador de imagens reserva (o pico de ~25 GiB incluía uma imagem de tamanho máximo, AC-14): mais *KV cache* ou espaço para R1 | flag e formato JSON conferidos na `v0.19.1`; se o modelo deixa de carregar o codificador com isso: `[não verificado]` |
| R3 | `--max-num-seqs` (padrão 256) | só limita a concorrência; não acelera | — |

Os blocos de R1 e R2 são o mesmo do Passo 1 com um argumento a mais; monte depois do resultado do 1b.

## Passo 2 — Limpeza (servidor, bash, qualquer nó com `kubectl`)

Libera a GPU. O modelo fica em cache em `/home` do nó (55,6 GB), e um novo arranque não baixa de novo.

```bash
kubectl delete pod -n vllm-estudo vllm-qwen38
```

Para apagar também o modelo do disco (em `sabdiia01`): `rm -rf /home/utec/vllm-estudo/hf-cache/hub/models--Qwen--Qwen3.8-27B`.
