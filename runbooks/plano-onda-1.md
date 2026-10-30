# Runbook — Plano de testes, onda 1: quatro modelos em 1 GPU (P-01 a P-04)

**Pergunta:** quanto cada candidato da onda 1 entrega numa V100S, medido no protocolo comum, e se responde
certo. **Decisão que destrava:** a escolha do modelo de produção (PD-19). Estes quatro também são os pares
de comparação dos testes com Ray das ondas 2 e 3. O plano completo está no
[registro de testes](https://git.abdi.com.br/ia-abdi/vllm/vllm-config/-/blob/main/docs/registro-de-testes.md#9-plano-de-testes-escolha-do-modelo-de-produção), seção 9.

| Plano | Modelo | Formato | Pesos [F-040] | Par com Ray |
|---|---|---|---|---|
| P-01 | `Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8` | GPTQ 8 bits | 15,50 GiB | P-05 |
| P-02 | `Qwen/Qwen2.5-32B-Instruct-GPTQ-Int4` | GPTQ 4 bits ⚠️ | 18,02 GiB | P-06 |
| P-03 | `Qwen/Qwen3-30B-A3B-GPTQ-Int4` | GPTQ 4 bits ⚠️, MoE | 15,77 GiB | P-08 |
| P-04 | `TheBloke/deepseek-coder-33B-instruct-GPTQ` | GPTQ 4 bits ⚠️ | 16,20 GiB | P-10 |

⚠️ GPTQ de 4 bits na V100S usa o `gptq_gemm`, que a própria `v0.19.1` chama de defeituoso (AC-15): a
resposta de sanidade (seção 4 do protocolo) decide se o número vale.

**Uma variável por vez:** só o modelo muda em relação ao `T-001`. A imagem `v0.19.1`, as *flags*
(`--dtype float16 --max-model-len 8192 --gpu-memory-utilization 0.90 --generation-config vllm`), a carga e
o nó (`sabdiia01`, refrigeração comprovada, AC-17) são os mesmos.

**Diferenças em relação ao `T-001`, todas fora da medida:**
- o *pod* usa `hostNetwork`, porque o DNS dos *pods* de 01 está quebrado (PD-28) e o modelo novo precisa
  ser baixado. O gerador roda dentro do contêiner, em `127.0.0.1`, como antes;
- o contêiner baixa o modelo antes de subir o servidor (só `.safetensors`, `.json` e arquivos do
  *tokenizer*). Depois o servidor sobe com `HF_HUB_OFFLINE=1`.

## Antes de rodar

1. **Combine com o administrador** o uso da GPU de `sabdiia01` por ~4 h para os quatro modelos
   `[estimativa]`. Em 2026-10-29 14:31, o `vllm-llama31` dele ocupava 30.992 MiB nela.
2. **Bloco 0** de [teste-protocolo-modelos.md](teste-protocolo-modelos.md) em `sabdiia01`: `VEREDITO ... PRONTO`.
3. **Bloco 1** do mesmo runbook, de novo, em `sabdiia01`. Ele regrava o `teste-protocolo.sh`. Em
   2026-10-30, a pergunta de sanidade passou a desligar o raciocínio do Qwen3
   (`chat_template_kwargs: {enable_thinking: false}`). Sem isso, o P-03 gastaria os 64 *tokens* da
   resposta pensando. Para os outros modelos, a opção é ignorada pelo *template*. O bloco abaixo aborta
   se o script for o antigo.

## Expectativa (escrita antes)

- **Arranque:** 10-25 min cada `[estimativa]`, quase tudo no *download* de 16-19 GB.
- ***KV cache*:** abaixo dos 13,14 GiB do `T-001`, porque os pesos são maiores (15,5-18 GiB contra 14,25).
  P-02 com o menor (~10 GiB) `[cálculo]`.
- **c=1:** P-01, P-02 e P-04 perto ou abaixo dos 47 *tok*/s do 7B FP16 `[hipótese]`. Leem um volume de
  pesos parecido por *token* e ainda pagam a desquantização no `gptq_gemm`. P-03 (MoE, ~3B ativos por
  *token*) deve ser o mais rápido dos quatro `[hipótese]`.
- **Sanidade:** P-01 correto. P-02, P-03 e P-04 podem sair com texto sem sentido (AC-15) `[hipótese]`.

## Bloco 1 — Grava `teste-1gpu.sh` (servidor `sabdiia01`, bash; uma vez)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
cat > teste-1gpu.sh <<'SCRIPT'
#!/bin/bash
# Uso: bash teste-1gpu.sh <id do plano> <modelo do Hugging Face>
# Sobe o modelo em 1 GPU deste nó (pod vllm-estudo/vllm-conc), roda o protocolo, guarda os logs e apaga o pod.
P=$1; M=$2
[ -n "$P" ] && [ -n "$M" ] || { echo "uso: bash teste-1gpu.sh <id do plano> <modelo>"; exit 1; }
N=$(hostname -s); cd /home/utec/vllm-estudo
echo "== $N  $(date -Is)  plano $P  modelo $M"
ab() { echo "ABORTA: $*"; exit 1; }
case "$N" in sabdiia01|sabdiia02) ;; *) ab "rode em sabdiia01 ou sabdiia02 (kubectl)";; esac

echo "### 1. pré-condições"
[ -x teste-protocolo.sh ] || ab "falta teste-protocolo.sh (Bloco 1 de runbooks/teste-protocolo-modelos.md)"
grep -q enable_thinking teste-protocolo.sh || ab "teste-protocolo.sh antigo: rode de novo o Bloco 1 de runbooks/teste-protocolo-modelos.md"
kubectl describe node "$N" | grep -E '^  nvidia\.com/gpu +[0-9]'
R=$(kubectl describe node "$N" | awk '/^  nvidia\.com\/gpu +[0-9]/{print $2}')
if [ "$R" != 0 ]; then
  kubectl get pods -A -o custom-columns='NS:.metadata.namespace,POD:.metadata.name,NODE:.spec.nodeName,GPU:.spec.containers[*].resources.limits.nvidia\.com/gpu' | awk -v n="$N" '$3==n && $4!="<none>"'
  ab "GPU de $N reservada pelo pod acima"
fi
A=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader)
[ -z "$A" ] || ab "processo na GPU fora do Kubernetes: $A"
nvidia-smi -q -d PERFORMANCE | grep -iE 'Thermal Slowdown +: Active' && ab "GPU estrangulando por temperatura antes do teste"
kubectl get pods -n vllm-estudo --no-headers 2>/dev/null | grep . && ab "há pods em vllm-estudo; apague-os antes"
ss -ltn | grep -E ':8000\b' && ab "porta 8000 ocupada em $N"
ctr -n k8s.io images ls -q | grep -qx 'docker.io/vllm/vllm-openai:v0.19.1' || ab "imagem v0.19.1 ausente: ctr -n k8s.io images pull docker.io/vllm/vllm-openai:v0.19.1"
df -h / /home
L=$(df -BG --output=avail /home | tail -1 | tr -dc 0-9)
[ "$L" -ge 40 ] || ab "/home com só ${L} G livres (o modelo ocupa até ~20 G)"
echo "PyPI/HF a partir de $N: HTTP $(curl -s -o /dev/null -w '%{http_code}' -m 15 https://huggingface.co/api/models/$M)"

echo "### 2. manifesto e criação do pod   $(date +%T)"
kubectl create namespace vllm-estudo --dry-run=client -o yaml | kubectl apply -f -
Y=$P-vllm-conc.yaml
cat > "$Y" <<EOF
# Plano de testes $P: $M em 1 V100S de $N, vLLM v0.19.1, protocolo comum.
# Pod de teste (restartPolicy Never), apagado no fim. hostNetwork: API em $N:8000, sem autenticação, só durante o teste.
apiVersion: v1
kind: Pod
metadata: {name: vllm-conc, namespace: vllm-estudo, labels: {app: vllm-conc, plano: $P}}
spec:
  nodeSelector: {kubernetes.io/hostname: $N}
  hostNetwork: true
  restartPolicy: Never
  containers:
  - name: vllm
    image: vllm/vllm-openai:v0.19.1
    command: ["/bin/bash", "-c"]
    args:
    - |
      set -e
      HF_HUB_OFFLINE=0 python3 -c "from huggingface_hub import snapshot_download as s; print('pesos em', s('$M', allow_patterns=['*.safetensors','*.json','*.model','*.txt','*.tiktoken','*.py']))"
      exec vllm serve $M --dtype float16 --max-model-len 8192 --gpu-memory-utilization 0.90 --generation-config vllm --host 0.0.0.0 --port 8000
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
    hostPath: {path: /home/utec/vllm-estudo/hf-cache, type: DirectoryOrCreate}
  - name: shm
    emptyDir: {medium: Memory, sizeLimit: 8Gi}
EOF
kubectl apply -f "$Y"

echo "### 3. aguardando o servidor (até 60 min)   $(date +%T)"
T0=$(date +%s); PRONTO=0
while [ $(( $(date +%s) - T0 )) -lt 3600 ]; do
  S=$(kubectl get pod -n vllm-estudo vllm-conc -o jsonpath='{.status.phase}/{.status.containerStatuses[0].ready}' 2>/dev/null)
  [ "$S" = "Running/true" ] && { PRONTO=1; break; }
  case "$S" in Failed*|Succeeded*) echo "o pod terminou: $S"; break;; esac
  echo "$(date +%T) $S | $(kubectl logs -n vllm-estudo vllm-conc --tail=1 2>/dev/null | cut -c1-160)"
  sleep 60
done
echo "pronto=$PRONTO depois de $(( ($(date +%s) - T0) / 60 )) min   $(date +%T)"
du -sh /home/utec/vllm-estudo/hf-cache/hub/models--$(echo "$M" | sed 's#/#--#') 2>/dev/null

if [ $PRONTO = 1 ]; then
  echo "### 4. protocolo   $(date +%T)"
  bash teste-protocolo.sh vllm-estudo pod/vllm-conc
else
  echo "### 4. FALHOU A SUBIDA: eventos"
  kubectl describe pod -n vllm-estudo vllm-conc | grep -A15 '^Events:'
fi

echo "### 5. log completo do pod em arquivo próprio; aqui, o arranque e o fim"
LP=$P-vllm-conc-$N-$(date +%F-%H%M).log
kubectl logs -n vllm-estudo vllm-conc > "$LP" 2>&1
echo "## $(wc -l < "$LP") linhas em $LP: arranque"
grep -vE 'GET /health|POST /v1/|GET /metrics|loggers.py' "$LP" | head -200
echo "## fim"; tail -15 "$LP"

echo "### 6. limpeza: apaga o pod e libera a GPU   $(date +%T)"
kubectl delete pod -n vllm-estudo vllm-conc --wait=true --timeout=180s
kubectl describe node "$N" | grep -E '^  nvidia\.com/gpu +[0-9]'
df -h /home
echo "== fim $(date -Is)"
SCRIPT
chmod +x teste-1gpu.sh && bash -n teste-1gpu.sh && echo "teste-1gpu.sh gravado e sem erro de sintaxe em $(hostname -s)"
```

## Bloco 2 — Um modelo por vez (servidor `sabdiia01`, bash)

Rode **um** bloco, traga o log, e só então passe ao próximo. Cada um leva ~30-60 min `[estimativa]`: ~15 min
de carga, mais o *download* e o arranque. O *pod* é apagado no fim de cada um.

**P-01**
```bash
cd /home/utec/vllm-estudo && bash teste-1gpu.sh P-01 Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8 2>&1 | tee P-01-$(hostname -s)-$(date +%F-%H%M).log
```

**P-02**
```bash
cd /home/utec/vllm-estudo && bash teste-1gpu.sh P-02 Qwen/Qwen2.5-32B-Instruct-GPTQ-Int4 2>&1 | tee P-02-$(hostname -s)-$(date +%F-%H%M).log
```

**P-03**
```bash
cd /home/utec/vllm-estudo && bash teste-1gpu.sh P-03 Qwen/Qwen3-30B-A3B-GPTQ-Int4 2>&1 | tee P-03-$(hostname -s)-$(date +%F-%H%M).log
```

**P-04**
```bash
cd /home/utec/vllm-estudo && bash teste-1gpu.sh P-04 TheBloke/deepseek-coder-33B-instruct-GPTQ 2>&1 | tee P-04-$(hostname -s)-$(date +%F-%H%M).log
```

**Não interrompa com Ctrl+C.** O *pod* continua e segura a GPU. Se precisar parar:
`kubectl delete pod -n vllm-estudo vllm-conc`.

## Trazer os logs (estação, PowerShell)

```powershell
scp "root@192.168.50.151:/home/utec/vllm-estudo/P-0*.log" "C:\www\vllm-master\logs-analysis\"
scp "root@192.168.50.151:/home/utec/vllm-estudo/P-0*-vllm-conc.yaml" "C:\www\vllm-master\logs-analysis\"
scp -r "root@192.168.50.151:/home/utec/vllm-estudo/testes" "C:\www\vllm-master\logs-analysis\"
```

## O que olhar

| Onde | O que | Leitura |
|---|---|---|
| Seção 3 | `pronto=1` | Subiu. Com `pronto=0`, a seção 5 mostra o erro |
| Protocolo, `### 2` | `Model loading took`, `GPU KV cache size`, nenhum `enforce_eager` | Pesos e *KV cache* para a Tabela 2 |
| Protocolo, `### 2` | aviso do `gptq_gemm` "buggy" (P-02, P-03, P-04) | Esperado em 4 bits (AC-15); anote em Observação |
| Protocolo, `### 4` | `RESPOSTA:` | Tem de dizer Brasília, em frase coerente. Texto sem sentido = o modelo **falha no eliminatório**, mesmo com bons números |
| Protocolo, `### 9` | linhas da Tabela 3 | Sem `!! totais fora do protocolo` |
| Protocolo, `### 7` e `### 8` | `Thermal Slowdown` | Ativo = o número é da refrigeração |

**Falhas prováveis na subida** (seção 5):

| Mensagem | Causa provável | O que fazer |
|---|---|---|
| erro de rede no `snapshot_download` | 01 sem acesso ao Hugging Face | Ver a linha `HTTP` da seção 1 (esperado 200) |
| `CUDA out of memory` / `No available memory for the cache blocks` | Pesos + ativações não deixam espaço para o *KV cache* com 8192 | Anote. Repetir com `--max-model-len 4096` é desvio do protocolo: registre na Observação |
| `Unsupported` / `not supported` ligado a GPTQ ou MoE | Falta *kernel* para `sm_70` | O modelo sai do plano por incompatível. Guarde o log |
| `FA2 is only supported on devices with compute capability >= 8` | Aviso normal (AC-13) | Nada |

## Depois de cada modelo

1. Registre como `T-xxx` nas Tabelas 1-3 do registro e anote o ID na coluna **Teste** do plano (seção 9).
2. Ponha o caminho do log na coluna **Evidência**.
3. O modelo fica em `/home/utec/vllm-estudo/hf-cache` de 01 (~16-19 GB). Vale guardar até a escolha final.
   Confira o espaço em `/home` na seção 6.
