# Runbook — Teste de modelo no protocolo comum (1 GPU ou Ray)

**Pergunta:** quanto um modelo entrega na V100S, medido do mesmo jeito por qualquer pessoa da equipe, para
caber numa linha do [registro de testes](https://git.abdi.com.br/ia-abdi/vllm/vllm-config/-/blob/main/docs/registro-de-testes.md)
(`vllm-config/docs/registro-de-testes.md`). **Decisão que destrava:** que modelo e que arranjo (1 GPU por
réplica, D-04, ou modelo dividido entre nós pelo Ray, PD-31) vão para o MVP.

Protocolo fixo (ver o registro): `v0.19.x`, 512 *tokens* de entrada, 256 de saída exatos (`--ignore-eos`),
`temperature 0`, `/v1/completions`, *prompts* aleatórios, *warmup* descartado, c=1/16/32 com sementes
101/116/102, servidor com `--generation-config vllm`.

| Bloco | Onde | O que faz | Altera algo? |
|---|---|---|---|
| 0 | **cada um dos 3 nós**, bash | Confere se o ambiente está pronto: GPU livre, temperatura, disco, imagem, rede, Ray | Não, só lê |
| 1 | `sabdiia01` ou `sabdiia02`, bash | Grava o script `teste-protocolo.sh` (uma vez por nó) | Só cria o arquivo |
| 2 | o mesmo nó, bash | Roda o protocolo contra um servidor já no ar e imprime as linhas do registro | Não altera o servidor; manda carga a ele |

**Antes de rodar:** avise o administrador e as outras pessoas que testam. A carga leva ~15-30 min
`[estimativa]` e ocupa o servidor inteiro: requisições de outras pessoas nesse tempo entram na medida.

Trazer os logs para a estação (estação, PowerShell):

```powershell
foreach ($ip in "192.168.50.151","192.168.50.152","192.168.50.150") {
  scp "root@${ip}:/home/utec/vllm-estudo/*.log" "C:\www\vllm-master\logs-analysis\"
}
scp -r "root@192.168.50.151:/home/utec/vllm-estudo/testes" "C:\www\vllm-master\logs-analysis\"
```

---

## Estado do ambiente na última evidência (2026-10-28 17:13)

| Item | Estado | Evidência |
|---|---|---|
| GPUs | **3 livres**: 0 MiB e 0 % nos 3 nós; nenhum *pod* com GPU; `vllm-deepseek-33b` e `vllm-llama31-8b` em `0/0` | `ray-onde-erro-*-2026-10-28-171*.log` |
| Servidor Ray | **fora do ar**: *Deployments* `ray-*` removidos; nada em 8000/8265/6379; a última subida falhou com erro não visto | idem, AC-19 |
| Disco `/` | 534-580 G livres; a `v0.19.1` ocupa ~30 G | `estado-disco-rede-*-2026-10-28-14*.log`, AC-09 |
| Imagem `v0.19.1` | ausente em 01 e 02 (2026-10-27); 03 `[não verificado]` | AC-20 |
| Ray na imagem | **nem a `v0.19.0` nem a `v0.19.1` trazem Ray** (sem `ray` em `requirements/` nem no Dockerfile das duas *tags*) | [F-034], conferido de novo em 2026-10-29 |
| MTU | **desigual**: `bond0.500` 9000 e `tunl0` 8980 em 03; 1500 e 1480 em 01 e 02 | idem, AC-08 |
| `bond1` de 03 | 2 das 4 portas num agregador separado; VLAN nova `bond1.20` nos 3 nós, sem endereço | idem |
| Refrigeração | 01 sustenta 250 W a 72 °C (AC-17); **02 e 03 nunca medidos sob carga** | AC-17 |
| DNS nos *pods* de 01 | quebrado desde 2026-10-22 (PD-28); não afeta *pod* com `hostNetwork` | PD-28 |
| `kubectl` em 03 | falha (OIDC) | AC-19 |

**Conclusão em 2026-10-29: pronto para o teste com 1 GPU; não pronto para o teste com Ray.**

- **1 GPU:** as GPUs estavam livres e há disco. Falta reconferir hoje (Bloco 0) e baixar a imagem.
  Prefira `sabdiia01`, a única GPU com refrigeração comprovada sob carga (AC-17).
- **Ray:** três bloqueios.
  1. Não há servidor no ar, e o erro da última subida não foi visto.
  2. O MTU desigual entre 03 e 01/02 pode derrubar ou travar a comunicação NCCL/Gloo entre os nós
     `[hipótese]`: os pacotes grandes de 03 não passam em 01 e 02. O Bloco 0 testa isso com `ping` sem
     fragmentação.
  3. O erro do administrador com a `v0.19.1` não tem log. Como nenhuma das duas imagens traz Ray, a falta
     do Ray não explica a diferença entre elas. A diferença conhecida é o `transformers` v5 ([F-036]).

  Leve os três ao administrador. Um Ray só entre 01 e 02 (`--pipeline-parallel-size 2`) evita o
  problema do MTU de 03.

---

## Bloco 0 — O ambiente está pronto? (servidor, bash, **em cada um dos 3 nós**)

Só lê. Em 03, a parte do Kubernetes falha (OIDC) e o resto roda normal. A última seção imprime o
veredito do nó.

**Expectativa (escrita antes):** GPU com 0 MiB e lista de processos vazia nos 3 nós; nenhuma GPU
reservada; `SW Thermal Slowdown` inativo; `/` com mais de 100 G livres; `ping` de 1472 *bytes* sem
fragmentar passando entre todos os nós; o de 8972 *bytes* falhando de 03 para 01 e 02 (MTU 1500 neles).

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  N=$(hostname -s); echo "== $N  $(date -Is)"
  case "$N" in sabdiia01|sabdiia02|sabdiia03) ;; *) echo "ABORTA: bloco para sabdiia01..03"; exit 1;; esac
  OK=1; aviso() { echo "!! $*"; OK=0; }

  echo "### 1. GPU: memória, uso, temperatura, potência, clock"
  nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw,clocks.sm,clocks.max.sm --format=csv
  echo "### 1b. processos na GPU (vazio = livre)"
  P=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader); echo "${P:-(nenhum)}"
  [ -z "$P" ] || aviso "há processo na GPU deste nó"
  MU=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  [ "${MU:-0}" -lt 500 ] || aviso "GPU com ${MU} MiB usados"
  echo "### 1c. motivos de redução de clock agora"
  nvidia-smi -q -d PERFORMANCE | grep -iE 'thermal|slowdown|power cap|idle'
  nvidia-smi -q -d PERFORMANCE | grep -iE 'Thermal Slowdown +: Active' && aviso "estrangulamento térmico ativo"

  echo "### 2. disco"
  df -h / /home
  LIV=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
  [ "$LIV" -ge 100 ] || aviso "/ com só ${LIV} G livres (a v0.19.1 ocupa ~30 G)"

  echo "### 3. imagens do vLLM no containerd"
  ctr -n k8s.io images ls | awk 'NR==1 || /vllm-openai/' | cut -c1-160

  echo "### 4. Ray ou vLLM fora do Kubernetes, e portas 8000/8265/6379"
  ps -eo pid,user,etime,args | grep -E '[r]aylet|[g]cs_server|[v]llm|[a]pi_server' | cut -c1-200 || true
  ss -ltnp | grep -E ':(8000|8265|6379)\b' || echo "nada escutando em 8000/8265/6379"

  echo "### 5. rede: MTU e IPv4 das interfaces usadas pelos pods e pelo Ray"
  for i in bond0 bond0.500 bond1 bond1.20 bond1.302 tunl0; do
    [ -e /sys/class/net/$i ] && echo "$i: mtu $(cat /sys/class/net/$i/mtu) $(ip -4 -br addr show $i | awk '{print $3}')"
  done
  echo "### 5b. ping sem fragmentar aos outros nós (1472 = MTU 1500; 8972 = MTU 9000)"
  for ip in 192.168.50.150 192.168.50.151 192.168.50.152; do
    ip -4 addr | grep -q "inet $ip/" && continue
    for s in 1472 8972; do
      if ping -c 2 -W 1 -M do -s $s $ip >/dev/null 2>&1; then echo "$ip  $s bytes: passa"; else echo "$ip  $s bytes: FALHA"; fi
    done
    ping -c 2 -W 1 -M do -s 1472 $ip >/dev/null 2>&1 || aviso "ping de 1472 bytes a $ip falha"
  done
  M0=$(cat /sys/class/net/bond0.500/mtu 2>/dev/null); echo "MTU de bond0.500 neste nó: $M0 (01 e 02 tinham 1500, 03 tinha 9000)"

  echo "### 6. Kubernetes (falha em sabdiia03 por OIDC)"
  if kubectl version --request-timeout=10s >/dev/null 2>&1; then
    kubectl get nodes -o wide
    echo "## GPU reservada por nó (Requests Limits; 0 0 = livre)"
    kubectl describe nodes | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
    echo "## pods que pedem GPU, em qualquer namespace"
    kubectl get pods -A -o custom-columns='NS:.metadata.namespace,POD:.metadata.name,NODE:.spec.nodeName,PHASE:.status.phase,GPU:.spec.containers[*].resources.limits.nvidia\.com/gpu' | grep -v '<none>'
    echo "## namespaces vllms e vllm-estudo"
    kubectl get deploy,pods -n vllms -o wide 2>&1 | cut -c1-200
    kubectl get pods -n vllm-estudo -o wide 2>&1 | cut -c1-200
  else
    echo "kubectl indisponível neste nó"
  fi

  echo "### VEREDITO $N: $([ $OK = 1 ] && echo 'PRONTO (GPU livre, sem estrangulamento, disco ok, ping 1472 ok)' || echo 'NÃO PRONTO: ver linhas !! acima')"
} 2>&1 | tee pronto-para-teste-$(hostname -s)-$(date +%F-%H%M).log
```

**O que olhar:**

| Resultado | Leitura |
|---|---|
| `VEREDITO ... PRONTO` nos 3 nós | Pode subir o servidor (1 GPU em qualquer nó; Ray, depois do item abaixo) |
| `8972 bytes: passa` de 03 e `FALHA` para 03 | MTU desigual confirmado. Para o Ray com 03, o administrador iguala o MTU antes; senão, Ray só entre 01 e 02 |
| `1472 bytes: FALHA` | Rede entre nós com problema básico: não teste Ray |
| Alguma GPU `1` em `nvidia.com/gpu` ou processo na GPU | A GPU está com alguém: combine antes de usar |
| `nada escutando` e nenhum *pod* do Ray | Servidor Ray fora do ar: só o teste com 1 GPU é possível |

---

## Subir o servidor a testar

O Bloco 2 mede um servidor **já no ar**. Ele precisa ter:

- imagem `vllm/vllm-openai:v0.19.1` (ou `v0.19.0`, anotada na linha do registro);
- `--dtype float16 --generation-config vllm`, sem `--enforce-eager` (se precisar dele, anote: o número
  vira piso);
- `vllm` instalado no contêiner do servidor (o gerador de carga roda dentro dele, como na B-001).

**1 GPU:** use o manifesto [`vllm-config/manifestos/vllm-qwen25-7b-fp16.yaml`](https://git.abdi.com.br/ia-abdi/vllm/vllm-config/-/blob/main/manifestos/vllm-qwen25-7b-fp16.yaml)
trocando só o modelo (e `--max-model-len`, se o modelo não aceitar 8192). Ele cria o *pod*
`vllm-estudo/vllm-conc` em `sabdiia01`.

**Ray do estudo (01 + 02, Qwen2.5-7B, PP 2):** [teste-ray-pp2-qwen25-7b.md](teste-ray-pp2-qwen25-7b.md)
sobe o próprio Ray em `vllm-estudo`, roda este protocolo e apaga tudo no fim.

**Ray do administrador:** subido por ele. Os nomes abaixo (`ray-head`, `ray-worker-2`, `ray-worker-3` em `vllms`)
são os de 2026-10-28; confira no Bloco 0 e ajuste a chamada do Bloco 2 se mudarem. O Bloco 2 só lê o
servidor e manda requisições: não para, não reinicia e não edita nada em `vllms`.

---

## Bloco 1 — Grava o script do protocolo (servidor, bash, `sabdiia01` ou `sabdiia02`; uma vez por nó)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
cat > teste-protocolo.sh <<'SCRIPT'
#!/bin/bash
# Uso: bash teste-protocolo.sh <namespace> <servidor> [outros objetos com GPU...]
#   <servidor>: deploy/<nome> ou pod/<nome> onde roda o "vllm serve" (porta 8000)
#   outros: workers do Ray, para amostrar a GPU deles também
NS=$1; SRV=$2; shift 2; GPUS="$SRV $*"
[ -n "$NS" ] && [ -n "$SRV" ] || { echo "uso: bash teste-protocolo.sh <namespace> <servidor> [workers...]"; exit 1; }
X() { kubectl exec -n "$NS" "$1" -- "${@:2}"; }
XI() { kubectl exec -i -n "$NS" "$1" -- "${@:2}"; }

echo "== $(hostname -s)  $(date -Is)  alvo: $NS/$SRV  GPUs: $GPUS"
for o in $GPUS; do kubectl get -n "$NS" "$o" >/dev/null || { echo "ABORTA: $NS/$o não existe"; exit 1; }; done

echo "### 1. servidor: versão, comando, modelo"
V=$(X $SRV python3 -c 'import vllm;print(vllm.__version__)' 2>/dev/null)
echo "vllm: $V"
case "$V" in 0.19.*) ;; *) echo "ABORTA: protocolo exige v0.19.x"; exit 1;; esac
X $SRV sh -c 'for p in /proc/[0-9]*/cmdline; do tr "\0" " " < $p 2>/dev/null | grep -E "vllm serve|api_server" ; done | sort -u | cut -c1-600'
MJ=$(X $SRV python3 -c "import json,urllib.request;d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/models'))['data'][0];print(d['id']+'|'+(d.get('root') or d['id']))") || { echo "ABORTA: a API não responde em 127.0.0.1:8000 dentro de $SRV"; exit 1; }
M=${MJ%%|*}; TOK=${MJ#*|}
echo "modelo servido: $M   tokenizer (root): $TOK"
SLUG=$(echo "$M" | tr '/:' '__')
D=/home/utec/vllm-estudo/testes/$(date +%F-%H%M)-$SLUG; mkdir -p "$D"; echo "resultados em $D"

echo "### 2. linhas do arranque (pesos, KV cache, concorrência máxima)"
for o in $GPUS; do echo "## $o"; kubectl logs -n "$NS" "$o" --tail=-1 2>/dev/null | grep -E 'Model loading took|Available KV cache memory|GPU KV cache size|Maximum concurrency for|enforce_eager|Ignoring|ERROR' | cut -c1-250 | tail -15; done

echo "### 3. GPUs antes (uso deve estar perto de 0 %)"
for o in $GPUS; do echo "$o: $(X $o nvidia-smi --query-gpu=memory.used,utilization.gpu,temperature.gpu,clocks.sm,power.draw --format=csv,noheader)"; X $o nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader; done

echo "### 4. sanidade: uma pergunta simples, temperature 0"
XI $SRV python3 - "$M" <<'PY'
import json,sys,urllib.request
b=json.dumps({"model":sys.argv[1],"messages":[{"role":"user","content":"Qual é a capital do Brasil? Responda em uma frase curta."}],"max_tokens":64,"temperature":0,"chat_template_kwargs":{"enable_thinking":False}}).encode()
r=json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8000/v1/chat/completions",b,{"Content-Type":"application/json"}),timeout=300))
print("RESPOSTA:",r["choices"][0]["message"]["content"].strip()[:400].replace("\n"," "))
PY

PRE0=$(X $SRV python3 -c "import urllib.request;print(sum(float(l.split()[-1]) for l in urllib.request.urlopen('http://127.0.0.1:8000/metrics').read().decode().splitlines() if l.startswith('vllm:num_preemptions_total')))")
echo "preempções antes: $PRE0"

echo "### 5. amostras de GPU a cada ~5 s -> $D/gpu-amostras.csv"
( while true; do for o in $GPUS; do echo "$(date +%T),$o,$(X $o nvidia-smi --query-gpu=temperature.gpu,power.draw,clocks.sm,utilization.gpu,memory.used --format=csv,noheader,nounits 2>&1)"; done; sleep 5; done ) > "$D/gpu-amostras.csv" &
AM=$!; trap 'kill $AM 2>/dev/null' EXIT

B="vllm bench serve --backend openai --base-url http://127.0.0.1:8000 --endpoint /v1/completions --model $M --tokenizer $TOK --dataset-name random --random-input-len 512 --random-output-len 256 --ignore-eos --temperature 0 --percentile-metrics ttft,tpot,itl,e2el --metric-percentiles 50,95,99"
echo "### 6. warmup: c=4, 16 requisições, semente 999 (descartado)   $(date +%T)"
X $SRV sh -c "$B --seed 999 --max-concurrency 4 --num-prompts 16" 2>&1 | grep -E 'Successful|Failed' 
for F in "1 12 101" "16 256 116" "32 512 102"; do
  set -- $F
  echo "### fase c=$1, $2 requisições, semente $3   início $(date +%T)"
  X $SRV sh -c "$B --seed $3 --max-concurrency $1 --num-prompts $2" 2>&1 | tee "$D/fase-c$1.txt" | sed -n '/Serving Benchmark Result/,$p'
  grep -q 'tokens than expected' "$D/fase-c$1.txt" && echo "!! aviso de entrada fora de 512 tokens na fase c=$1"
done
kill $AM 2>/dev/null

PRE1=$(X $SRV python3 -c "import urllib.request;print(sum(float(l.split()[-1]) for l in urllib.request.urlopen('http://127.0.0.1:8000/metrics').read().decode().splitlines() if l.startswith('vllm:num_preemptions_total')))")
echo "preempções depois: $PRE1 (diferença = preempções do teste, warmup incluído)"

echo "### 7. estrangulamento depois da carga"
for o in $GPUS; do echo "## $o"; X $o nvidia-smi -q -d PERFORMANCE | grep -iE 'thermal|slowdown|power cap'; done
echo "### 8. GPU sob carga (amostras com uso >= 50 %): temp. máx., clock mín."
for o in $GPUS; do grep ",$o," "$D/gpu-amostras.csv" | awk -F', *' -v o=$o '$6+0>=50 {n++; t=$3+0; c=$5+0; if(t>mt)mt=t; if(mc==""||c<mc)mc=c} END{print o": temp máx "mt" C, clock mín "mc" MHz, amostras "n+0}'; done

echo "### 9. LINHAS PARA O REGISTRO (Tabela 3), conferidas com os totais esperados"
for c in 1 16 32; do
  f="$D/fase-c$c.txt"
  [ -s "$f" ] || { echo "c=$c: sem saída do gerador"; continue; }
  awk -v c=$c '
    /^Successful requests:/ {ok=$3} /^Failed requests:/ {fa=$3}
    /^Total input tokens:/ {ti=$4} /^Total generated tokens:/ {tg=$4}
    /^Output token throughput/ {th=$5} /^P50 TTFT/ {t50=$4} /^P99 TTFT/ {t99=$4}
    /^P50 TPOT/ {p50=$4} /^P99 TPOT/ {p99=$4}
    /^P50 E2EL/ {e50=$4} /^P99 E2EL/ {e99=$4}
    END { if (ok=="") {print "c="c": sem resultado"; exit}
      v=(ti==512*ok && tg==256*ok)?"":"!! totais fora do protocolo: entrada "ti", saída "tg"; a fase NÃO vale";
      printf "| T-xxx | %s | %s | %s | %.1f | %.0f | %.0f / %.0f | %.1f / %.1f | %.1f / %.1f | ver nota | ver seção 8 | %s |\n", c, ok, fa, th, 1000/p50, t50, t99, p50, p99, e50/1000, e99/1000, v }' "$f"
done
echo "== fim $(date -Is)   resultados em $D"
SCRIPT
chmod +x teste-protocolo.sh && bash -n teste-protocolo.sh && echo "script gravado e sem erro de sintaxe em $(hostname -s)"
```

---

## Bloco 2 — Roda o protocolo (servidor, bash, no nó do Bloco 1)

Escolha **uma** das duas linhas, conforme o servidor no ar.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
# 1 GPU: pod vllm-conc em vllm-estudo
bash teste-protocolo.sh vllm-estudo pod/vllm-conc 2>&1 | tee teste-protocolo-$(hostname -s)-$(date +%F-%H%M).log
```

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
# Ray: servidor no head, GPUs amostradas nos 3 Deployments (nomes de 2026-10-28)
bash teste-protocolo.sh vllms deploy/ray-head deploy/ray-worker-2 deploy/ray-worker-3 2>&1 | tee teste-protocolo-$(hostname -s)-$(date +%F-%H%M).log
```

**Expectativa (escrita antes):**

- **1 GPU, Qwen2.5-7B FP16:** repete o `T-001` (47 *tok*/s em c=1; 680 em c=32), com diferença de até
  ~5 %. Se não repetir, o problema é do ambiente, não do modelo.
- **Ray, *pipeline parallel* 3:** c=1 mais lento que o mesmo modelo em 1 GPU (cada *token* atravessa os 3
  nós); c=32 abaixo da soma de 3 réplicas `[hipótese, AC-21]`.

## O que olhar e como registrar

1. A seção 9 imprime as linhas da Tabela 3 do registro. **Linha com `!! totais fora do protocolo` não
   vale:** respostas curtas ou entrada fora de 512 *tokens*.
2. `Failed requests` tem de ser 0.
3. Seção 7: alguma linha `Thermal Slowdown ... Active`, ou contador crescendo? Então o número mede a
   refrigeração daquele nó (AC-17). Anote em **Observação**.
4. Tabelas 1 e 2 do registro: copie da seção 1 (versão e comando, de onde saem `--max-model-len`,
   `--gpu-memory-utilization`, `--max-num-seqs`, `--enforce-eager` e *offload*), da seção 2 (pesos, *KV
   cache*, concorrência máxima), da seção 3 (VRAM usada) e da seção 4 (sanidade).
5. Preempções: a diferença entre "depois" e "antes" vai na coluna de preempções, uma vez por teste
   (inclui o *warmup*).
6. Guarde o `.log` e a pasta `testes/<data>-<modelo>/` e ponha o caminho na coluna **Evidência**.

**Ressalvas fixas:** o gerador roda no mesmo contêiner do servidor e divide a CPU com ele, como no
`T-001`; uma rodada por nível, sem repetição.
