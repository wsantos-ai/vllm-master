# Runbook — Mistral-Nemo 12B FP16 em 1 GPU: velocidade (protocolo) e qualidade, contra o T-009 do administrador

**Pergunta:** quanto o `mistralai/Mistral-Nemo-Instruct-2407` em FP16 entrega numa V100S, medido no
protocolo comum, e quanto ele acerta nas 50 perguntas da aplicação (AC-28)? **Decisão que destrava:** se o
Nemo entra como candidato do MVP ao lado do Qwen2.5-14B GPTQ-Int8 e do Qwen3-30B-A3B (PD-19). De quebra,
diz se os números do `T-009` do administrador (3 réplicas atrás de um *LoadBalancer*) são os de uma carga
dividida entre as 3 GPUs ou concentrada numa só, como parece ter acontecido no `T-010`.

| Bloco | Onde | O que faz | Altera algo? |
|---|---|---|---|
| P | `sabdiia01`, bash | Pausa `vllms` ([pausar-vllms.md](pausar-vllms.md)). **Só com o acordo do administrador** | Sim: produção fora do ar |
| 0 | `sabdiia01`, bash | Bloco 0 de [teste-protocolo-modelos.md](teste-protocolo-modelos.md) | Não |
| C | estação + `sabdiia01` | Cópia e Bloco 1 de [teste-qualidade-modelos.md](teste-qualidade-modelos.md) (o coletor e o `qualidade.sh` mudaram em 2026-11-05) | Só arquivos |
| 1 | `sabdiia01`, bash | Bloco 1 de [teste-protocolo-modelos.md](teste-protocolo-modelos.md): regrava o `teste-protocolo.sh` (a pergunta de sanidade mudou em 2026-11-05) | Só o arquivo |
| N1 | `sabdiia01`, bash | Sobe o Nemo, baixa os pesos, roda o protocolo e uma fase extra c=11, apaga o *pod* | Cria e apaga um *pod* em `vllm-estudo` |
| N2 | `sabdiia01`, bash | `qualidade.sh nemo`: 50 perguntas, nota, apaga o *pod* | Cria e apaga um *pod* em `vllm-estudo` |
| R | `sabdiia01`, bash | Restaura `vllms` ([pausar-vllms.md](pausar-vllms.md)) | Sim: produção de volta |

**Janela** `[estimativa]`: ~60 min entre P e R. O N1 leva ~35 min (download de ~24,5 GB, arranque e ~20 min
de carga); o N2, ~15 min.

---

## O que difere dos Qwen (conferido em 2026-11-05, [F-044])

| Ponto | Fonte | Consequência |
|---|---|---|
| O repositório traz os pesos duas vezes: `consolidated.safetensors` (24.495.604.224 B, formato Mistral) e 5 partes `model-0000x-of-00005.safetensors` (formato HF, mesmo total) | API do HF, `sha 04d8a905` | Baixar só `consolidated.safetensors`, `*.json` e `*.txt`. O padrão `*.safetensors` dos outros testes baixaria ~49 GB |
| Não é *gated* (`"gated": false`) | API do HF | Não precisa de *token* |
| Na `v0.19.1`, `auto` escolhe o formato da Mistral (`mistral_common`) **só se conseguir listar o repositório**; com `HF_HUB_OFFLINE=1` a listagem falha e cai no formato HF | `vllm/tokenizers/registry.py`, `vllm/transformers_utils/repo_utils.py`, `default_loader.py` da *tag* | *Flags* fixas `--tokenizer_mode mistral --config_format mistral --load_format mistral`, as da doc da `v0.19.1` (`docs/features/tool_calling.md`), e servir pelo **caminho local** (o vLLM lista o disco), com `--served-model-name` |
| *Parser* de ferramenta: `mistral` | `docs/features/tool_calling.md` da `v0.19.1` | `--enable-auto-tool-choice --tool-call-parser mistral` |
| Com o *tokenizer* Mistral, requisição com `chat_template_kwargs` é recusada: `chat_template is not supported for Mistral tokenizers.` | `vllm/tokenizers/mistral.py`, `validate_request_params` | Coletor e sanidade não mandam `enable_thinking` para modelos `mistralai/` |
| `id` de *tool call* tem de casar `^[a-zA-Z0-9]{9}$` | `mistral_common`, `validator.py` | Chamada simulada da etapa 2 com `id` `chamada01` (era `chamada-1`) só para `mistralai/` |
| `/home` de 01 tinha 33 G livres (2026-11-04); `/` tem ~580 G | §2 do estudo | Cache em `/var/lib/vllm-estudo/hf-cache` (no `/`), o mesmo dos testes com Ray |
| *Pods* de 01 sem `hostNetwork` não resolvem nomes (PD-28) | §2 | O N1 usa `hostNetwork` para baixar; o N2 só lê o cache |

**Diferenças assumidas contra o `T-009`:** o administrador usou `--max-model-len 4096` e
`--gpu-memory-utilization 0.95`, e o script de carga dele não é o `vllm bench serve` do protocolo
`[não verificado]`. Este teste fica no protocolo (8192 e 0,90) para comparar com `T-001` e `T-003`. Nas
fases que a comparação usa (c=1 e c=11), o *KV cache* não limita nos dois casos: 11 × 768 = 8.448 *tokens*,
contra ~26.000 ou mais disponíveis `[cálculo]`. O que o administrador usou de formato (Mistral ou HF) também
`[não verificado]`: pergunte a ele.

---

## Expectativa (escrita antes)

- **Arranque:** pesos de ~22,8 GiB (24.495.604.224 B). *KV cache* de ~4-5 GiB, ou ~26.000-33.000
  *tokens* (160 KiB por *token*: 40 camadas × 8 cabeças KV × 128 × 2 × 2 *bytes*) `[cálculo]`;
  concorrência máxima para 8.192 *tokens* entre 3× e 4×. O `T-009` (0,95, 4096) registrou ~7 GiB.
- **Sanidade:** "Brasília". Se sair lixo, o FP16 (o modelo foi publicado em BF16) estoura `[hipótese]`.
- **c=1:** ~29-31 *tok*/s, TPOT ~33 ms. O 7B FP16 dá TPOT de 20,3 ms com 15,2 GB de pesos; 24,5 GB lidos
  por *token* dão ~1,6× isso `[cálculo]`. O `T-009` deu 27,9 *tok*/s e 35,1 ms: com 1 usuário, só uma
  réplica trabalha, então os dois números devem bater (±10 %).
- **c=11 (fase extra), o teste do `T-009`:** com 3 réplicas e a carga dividida, cada uma recebe ~11 dos 32
  usuários. Se foi isso, a nossa fase c=11 dá **~156 *tok*/s (467,7 ÷ 3) e TPOT p50 ~53 ms** (`T-009`:
  53,2 ms). TPOT bem abaixo de 53 ms aqui significa que as réplicas do administrador receberam mais carga que
  11 cada, ou seja, carga desigual.
- **c=32 em 1 GPU:** perto do limite do *KV cache* (32 × 768 = 24.576 *tokens*); pode haver preempções.
  Menos de 10 *tok*/s por usuário `[hipótese]`.
- **Qualidade:** formato ≥ 90 % se o *parser* `mistral` funcionar; formato perto de 0 % é *parser* ou
  *template*, não o modelo. Nota das duas etapas abaixo do 14B Int8 (90 %) `[hipótese: modelo menor e
  mais antigo]`.

---

## Bloco N1 — Velocidade (servidor `sabdiia01`, bash; aborta em outro nó)

Antes: Blocos P, 0, C e 1 (tabela acima). **Não interrompa com Ctrl+C**: o *pod* segue segurando a GPU;
para parar, `kubectl delete pod -n vllm-estudo vllm-conc`.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  Mistral-Nemo 12B FP16, 1 GPU: protocolo + fase c=11"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  grep -q 'startswith("mistralai/")' teste-protocolo.sh 2>/dev/null || { echo "ABORTA: teste-protocolo.sh ausente ou antigo; rode o Bloco 1 de teste-protocolo-modelos.md"; exit 1; }

  echo "### 1. pré-condições"
  kubectl describe nodes sabdiia01 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  R=$(kubectl describe nodes sabdiia01 | awk '/^  nvidia\.com\/gpu +[0-9]/{s+=$2} END{print s+0}')
  [ "$R" = 0 ] || { echo "ABORTA: GPU de 01 reservada no Kubernetes (vllms pausado? Bloco P)"; exit 1; }
  A=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader)
  [ -z "$A" ] || { echo "ABORTA: processo na GPU de 01: $A"; exit 1; }
  kubectl get pods -n vllm-estudo --no-headers 2>/dev/null | grep . && { echo "ABORTA: há pods em vllm-estudo"; exit 1; }
  ctr -n k8s.io images ls -q | grep -qx 'docker.io/vllm/vllm-openai:v0.19.1' || { echo "ABORTA: imagem ausente: ctr -n k8s.io images pull docker.io/vllm/vllm-openai:v0.19.1"; exit 1; }
  ss -ltn | grep -E ':8000\b' && { echo "ABORTA: porta 8000 ocupada em 01"; exit 1; }
  LIV=$(df -BG --output=avail / | tail -1 | tr -dc 0-9); df -h /
  [ "$LIV" -ge 40 ] || { echo "ABORTA: / com só ${LIV} G livres (o Nemo ocupa ~25 G)"; exit 1; }
  nvidia-smi -q -d PERFORMANCE | grep -iE 'thermal|slowdown|power cap'

  echo "### 2. manifesto e criação   $(date +%T)"
  kubectl create namespace vllm-estudo --dry-run=client -o yaml | kubectl apply -f -
  cat > nemo-vllm-conc.yaml <<'EOF'
# Mistral-Nemo 12B FP16 em 1 V100S de sabdiia01, vLLM v0.19.1, protocolo comum. Pod de teste (restartPolicy Never),
# apagado no fim do Bloco N1 de runbooks/teste-mistral-nemo.md. hostNetwork só para baixar os pesos (PD-28):
# a API fica em sabdiia01:8000, SEM autenticação, enquanto o bloco roda.
apiVersion: v1
kind: Pod
metadata: {name: vllm-conc, namespace: vllm-estudo, labels: {app: vllm-conc, teste: nemo}}
spec:
  nodeSelector: {kubernetes.io/hostname: sabdiia01}
  hostNetwork: true
  restartPolicy: Never
  containers:
  - name: vllm
    image: vllm/vllm-openai:v0.19.1
    command: ["/bin/bash", "-c"]
    args:
    - |
      set -e
      P=$(python3 -c "from huggingface_hub import snapshot_download as s; print(s('mistralai/Mistral-Nemo-Instruct-2407', local_files_only=True))" 2>/dev/null || HF_HUB_OFFLINE=0 python3 -c "from huggingface_hub import snapshot_download as s; print(s('mistralai/Mistral-Nemo-Instruct-2407', allow_patterns=['consolidated.safetensors','*.json','*.txt']))"); echo "pesos em $P"; ls -laL "$P"
      exec vllm serve "$P" --served-model-name mistralai/Mistral-Nemo-Instruct-2407 --dtype float16 --max-model-len 8192 --gpu-memory-utilization 0.90 --generation-config vllm --tokenizer_mode mistral --config_format mistral --load_format mistral --enable-auto-tool-choice --tool-call-parser mistral --host 0.0.0.0 --port 8000
    env:
    - {name: HF_HOME, value: /hf-cache}
    - {name: HF_HUB_OFFLINE, value: "1"}
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
    hostPath: {path: /var/lib/vllm-estudo/hf-cache, type: DirectoryOrCreate}
  - name: shm
    emptyDir: {medium: Memory, sizeLimit: 8Gi}
EOF
  kubectl apply -f nemo-vllm-conc.yaml || exit 1

  echo "### 3. aguardando o servidor (até 45 min; baixa ~24,5 GB na 1ª vez)   $(date +%T)"
  T0=$(date +%s); PRONTO=0
  while [ $(( $(date +%s) - T0 )) -lt 2700 ]; do
    H=$(kubectl get pod -n vllm-estudo vllm-conc -o jsonpath='{.status.phase}/{.status.containerStatuses[0].ready}' 2>/dev/null)
    [ "$H" = "Running/true" ] && { PRONTO=1; break; }
    case "$H" in Failed*|Succeeded*) echo "o servidor terminou: $H"; break;; esac
    echo "$(date +%T) $H | $(du -sh /var/lib/vllm-estudo/hf-cache/hub/models--mistralai--Mistral-Nemo-Instruct-2407 2>/dev/null | cut -f1) | $(kubectl logs -n vllm-estudo vllm-conc --tail=1 2>/dev/null | cut -c1-150)"
    sleep 30
  done
  echo "pronto=$PRONTO depois de $(( ($(date +%s) - T0) / 60 )) min"

  if [ $PRONTO = 1 ]; then
    echo "### 4. arranque: formato, tokenizer, pesos, KV cache"
    kubectl logs -n vllm-estudo vllm-conc --tail=-1 | grep -iE 'pesos em|consolidated|tokenizer_mode|config_format|load_format|tool|Model loading took|Available KV cache memory|GPU KV cache size|Maximum concurrency|WARNING|ERROR' | grep -vE 'POST /v1|GET /' | cut -c1-250 | head -30

    echo "### 5. protocolo comum (c=1/16/32)   $(date +%T)"
    bash teste-protocolo.sh vllm-estudo pod/vllm-conc

    echo "### 6. fase extra c=11, 176 requisições, semente 111 (a carga de 1 réplica no T-009, se dividida por 3)   $(date +%T)"
    D=$(ls -d /home/utec/vllm-estudo/testes/*-mistralai_Mistral-Nemo-Instruct-2407 | tail -1); echo "pasta: $D"
    TOK=$(kubectl exec -n vllm-estudo vllm-conc -- python3 -c "import json,urllib.request;print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/models'))['data'][0]['root'])")
    echo "tokenizer (root): $TOK"
    nvidia-smi --query-gpu=timestamp,temperature.gpu,power.draw,clocks.sm,utilization.gpu,memory.used --format=csv -l 2 > "$D/gpu-c11.csv" & AM=$!
    B="vllm bench serve --backend openai --base-url http://127.0.0.1:8000 --endpoint /v1/completions --model mistralai/Mistral-Nemo-Instruct-2407 --tokenizer $TOK --dataset-name random --random-input-len 512 --random-output-len 256 --ignore-eos --temperature 0 --percentile-metrics ttft,tpot,itl,e2el --metric-percentiles 50,95,99"
    kubectl exec -n vllm-estudo vllm-conc -- sh -c "$B --seed 111 --max-concurrency 11 --num-prompts 176" 2>&1 | tee "$D/fase-c11.txt" | sed -n '/Serving Benchmark Result/,$p'
    kill $AM 2>/dev/null
    awk -F', *' 'NR>1 && $5+0>=50 {n++; if($2>mt)mt=$2; if(mc==""||$4+0<mc)mc=$4+0; if($3+0>mp)mp=$3+0} END{print "c=11 sob carga: temp máx "mt" C, clock mín "mc" MHz, potência máx "mp" W, amostras "n+0}' "$D/gpu-c11.csv"
    nvidia-smi -q -d PERFORMANCE | grep -iE 'thermal|slowdown|power cap'
    cp nemo-vllm-conc.yaml "$D/manifesto.yaml"
  else
    echo "### 4. FALHOU A SUBIDA: eventos"
    kubectl describe pod -n vllm-estudo vllm-conc | grep -A15 '^Events:'
  fi

  echo "### 7. log do pod e limpeza   $(date +%T)"
  L=nemo-vllm-conc-pod-$(date +%F-%H%M).log; kubectl logs -n vllm-estudo vllm-conc > "$L" 2>&1
  echo "log do pod: $L ($(wc -l < "$L") linhas); fim:"; tail -20 "$L" | cut -c1-250
  kubectl delete pod -n vllm-estudo vllm-conc --wait=true --timeout=180s
  kubectl describe nodes sabdiia01 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  du -sh /var/lib/vllm-estudo/hf-cache/hub/models--mistralai--Mistral-Nemo-Instruct-2407
  echo "== fim $(date -Is)"
} 2>&1 | tee nemo-protocolo-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** `pronto=1`, a seção 5 imprime as três linhas do registro sem `AVISO`, e a seção 6 mostra
`Successful requests: 176` e `Failed requests: 0`.

## Bloco N2 — Qualidade (servidor `sabdiia01`, bash)

Usa os pesos que o N1 deixou em `/var/lib/vllm-estudo/hf-cache`; aborta se não estiverem lá.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
bash qualidade/qualidade.sh nemo 2>&1 | tee qualidade-nemo-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** seção 4 com `--tool-call-parser mistral`, seção 5 com `linhas gravadas: 51` e a tabela de
notas na seção 6.

## Depois: Bloco R e trazer os logs

Bloco R de [pausar-vllms.md](pausar-vllms.md), no mesmo nó do Bloco P. Depois, na estação (PowerShell):

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
scp "${u}@192.168.50.151:/home/utec/vllm-estudo/nemo-*.log" "${u}@192.168.50.151:/home/utec/vllm-estudo/qualidade-nemo-*.log" "C:\www\vllm-master\logs-analysis\"
scp -r "${u}@192.168.50.151:/home/utec/vllm-estudo/testes" "C:\www\vllm-master\logs-analysis\"
scp -r "${u}@192.168.50.151:/home/utec/vllm-estudo/qualidade/resultados" "C:\www\vllm-master\logs-analysis\qualidade\"
```

Com `Permission denied`, rode no 01, como `root`:
`chmod -R a+rX /home/utec/vllm-estudo/testes /home/utec/vllm-estudo/qualidade /home/utec/vllm-estudo/*.log`.

## O que olhar

| Onde | O que | Leitura |
|---|---|---|
| N1 seção 4 | `pesos em .../snapshots/04d8a905...` e nenhuma linha de `model-0000` | Formato Mistral, só o `consolidated` |
| N1 seção 4 | `ERROR` com `mistral_common`, `tekken` ou `params.json` | O formato Mistral não sobe na `v0.19.1` desta imagem. Plano B, `[não executado]`: formato HF pela doc (`--tokenizer_mode hf --config_format hf --load_format hf --tool-call-parser mistral --chat-template examples/tool_chat_template_mistral_parallel.jinja`), que exige baixar as 5 partes HF (+24,5 GB) e conferir se o `.jinja` está na imagem. Traga o log antes |
| N1 seção 5, item 4 | `RESPOSTA:` | Sanidade. Lixo = FP16 estourando `[hipótese]`; pare |
| N1 seção 5, item 9 | linhas da Tabela 3 | `AVISO: totais fora do protocolo` invalida a fase. Com o *tokenizer* Mistral no gerador, é o primeiro suspeito |
| N1 seção 6 | TPOT p50 e vazão de c=11 | Compare com a tabela abaixo |
| N1 seções 5 e 6 | `Thermal Slowdown ... Active` ou contador crescendo | O número mede a refrigeração (AC-17), não o modelo |
| N2 seção 6 | formato, consulta, resposta | Compare com AC-28: 14B Int8 90 %, 30B-A3B 92 %, 7B 67 % |

**Comparação com o administrador** (preencher com os números do N1):

| Fase | T-009 (adm., 3 réplicas, 4096, 0,95) | Nemo 1 GPU (este teste) | Leitura |
|---|---|---|---|
| c=1 | 27,9 *tok*/s; TPOT 35,1 ms; TTFT p50 195 ms | | devem bater (±10 %) |
| c=11 (= 32 ÷ 3) | — | | × 3 contra a linha de baixo |
| c=32 | 467,7 *tok*/s; 19 por usuário; TPOT 53,2 ms; TTFT p50 1.525 ms | | 1 GPU com 32: não comparável ao T-009, comparável ao `T-003` (14B Int8: 194,6) |

## Registro

- Tabelas 1 a 3 do registro em `vllm-config`, com um ID novo. **Antes, resolva o ID duplicado `T-007`**
  (P-05 no plano, Llama 8B do administrador nas tabelas).
- A fase c=11 vai na Tabela 3 com observação "fase extra, fora do protocolo".
- O resultado de qualidade entra em AC-28 (novo candidato); a comparação com o `T-009`, numa linha de §9 do
  registro ou num achado, conforme o resultado.
