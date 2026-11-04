#!/bin/bash
# Teste de qualidade de um candidato: sobe o servidor em vllm-estudo, coleta as 50 perguntas, pontua e apaga.
# Roda em sabdiia01, em /home/utec/vllm-estudo/qualidade (arquivos copiados da pasta qualidade/ do estudo).
# Uso: bash qualidade.sh <candidato>
#   7b            Qwen/Qwen2.5-7B-Instruct FP16, 1 GPU (01)
#   14b-int8      Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8, 1 GPU (01)
#   30b-a3b       Qwen/Qwen3-30B-A3B-GPTQ-Int4, 1 GPU (01)
#   14b-fp16-ray  Qwen/Qwen2.5-14B-Instruct FP16, Ray PP 2 (01 + 02), mesmo desenho do P-05
#   7b-ray        Qwen/Qwen2.5-7B-Instruct FP16, Ray PP 2 (01 + 02): controle contra o "7b"
# Servidor: v0.19.1, --dtype float16 --max-model-len 8192 --gpu-memory-utilization 0.90 --generation-config vllm
#           --enable-auto-tool-choice --tool-call-parser hermes ([F-042]).
C=$1
case "$C" in
  7b)           MODELO=Qwen/Qwen2.5-7B-Instruct;             RAY=0 ;;
  14b-int8)     MODELO=Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8;  RAY=0 ;;
  30b-a3b)      MODELO=Qwen/Qwen3-30B-A3B-GPTQ-Int4;         RAY=0 ;;
  14b-fp16-ray) MODELO=Qwen/Qwen2.5-14B-Instruct;            RAY=1 ;;
  7b-ray)       MODELO=Qwen/Qwen2.5-7B-Instruct;             RAY=1 ;;
  *) echo "uso: bash qualidade.sh 7b|14b-int8|30b-a3b|14b-fp16-ray|7b-ray"; exit 1 ;;
esac
NS=vllm-estudo
Q=/home/utec/vllm-estudo/qualidade
D=$Q/resultados/$(date +%F-%H%M)-$C
echo "== $(hostname -s)  $(date -Is)  teste de qualidade: $C ($MODELO, Ray=$RAY)"
[ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este script é para sabdiia01"; exit 1; }
cd $Q || exit 1
for f in gabarito-qualidade.json coletar-respostas.py pontuar-respostas.py; do
  [ -s $f ] || { echo "ABORTA: falta $Q/$f (Bloco 1 do runbook teste-qualidade-modelos.md)"; exit 1; }
done
mkdir -p "$D"; echo "resultados em $D"

echo "### 1. pré-condições"
NOS=sabdiia01; [ $RAY = 1 ] && NOS="sabdiia01 sabdiia02"
kubectl describe nodes $NOS | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
R=$(kubectl describe nodes $NOS | awk '/^  nvidia\.com\/gpu +[0-9]/{s+=$2} END{print s+0}')
[ "$R" = 0 ] || { echo "ABORTA: GPU reservada no Kubernetes em $NOS"; exit 1; }
A=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader)
[ -z "$A" ] || { echo "ABORTA: processo na GPU de 01 fora do Kubernetes: $A"; exit 1; }
kubectl get pods -n $NS --no-headers 2>/dev/null | grep . && { echo "ABORTA: há pods em $NS; apague-os antes"; exit 1; }
ctr -n k8s.io images ls -q | grep -qx 'docker.io/vllm/vllm-openai:v0.19.1' || { echo "ABORTA: imagem v0.19.1 ausente em 01: ctr -n k8s.io images pull docker.io/vllm/vllm-openai:v0.19.1"; exit 1; }
if [ $RAY = 1 ]; then
  ss -ltn | grep -E ':(6379|8000|10001)\b' && { echo "ABORTA: porta 6379/8000/10001 já ocupada em 01"; exit 1; }
  ping -c 2 -W 1 -M do -s 1472 192.168.50.152 >/dev/null || { echo "ABORTA: ping de 1472 bytes sem fragmentar a 02 falha"; exit 1; }
  CP=$(curl -s -o /dev/null -w '%{http_code}' -m 15 https://pypi.org/simple/ray/); echo "PyPI a partir de 01: HTTP $CP"
  [ "$CP" = 200 ] || { echo "ABORTA: 01 não alcança o PyPI (o Ray é instalado ao iniciar)"; exit 1; }
fi
df -h / /home

echo "### 2. manifesto e criação   $(date +%T)"
kubectl create namespace $NS --dry-run=client -o yaml | kubectl apply -f -
# Pesos: usa o cache; só baixa se faltar (HF_HUB_OFFLINE=1 no resto do pod).
BAIXA="python3 -c \"from huggingface_hub import snapshot_download as s; print('pesos em', s('__MODELO__', local_files_only=True))\" || HF_HUB_OFFLINE=0 python3 -c \"from huggingface_hub import snapshot_download as s; print('pesos em', s('__MODELO__', allow_patterns=['*.safetensors','*.json','*.model','*.txt','*.tiktoken','*.py']))\""
FLAGS="--dtype float16 --max-model-len 8192 --gpu-memory-utilization 0.90 --generation-config vllm --enable-auto-tool-choice --tool-call-parser hermes --host 0.0.0.0 --port 8000"
if [ $RAY = 0 ]; then
  SRV=vllm-qual; GPODS=$SRV
  cat > $D/manifesto.yaml <<'EOF'
# Teste de qualidade, 1 GPU em sabdiia01. vLLM v0.19.1. Pod de teste (restartPolicy Never), apagado no fim.
# Sem Service: a coleta roda dentro do pod, em 127.0.0.1:8000.
apiVersion: v1
kind: Pod
metadata: {name: vllm-qual, namespace: vllm-estudo, labels: {app: vllm-qual, teste: qualidade}}
spec:
  nodeSelector: {kubernetes.io/hostname: sabdiia01}
  restartPolicy: Never
  containers:
  - name: vllm
    image: vllm/vllm-openai:v0.19.1
    command: ["/bin/bash", "-c"]
    args:
    - |
      set -e
      __BAIXA__
      exec vllm serve __MODELO__ __FLAGS__
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
else
  SRV=qual-ray-head; GPODS="qual-ray-head qual-ray-worker"
  cat > $D/manifesto.yaml <<'EOF'
# Teste de qualidade, Ray do estudo (vllm-estudo), PP 2: head em sabdiia01, worker em sabdiia02. Desenho do P-05.
# vLLM v0.19.1, Ray 2.48.0. Pods de teste (restartPolicy Never), apagados no fim.
# hostNetwork: API em 192.168.50.151:8000 e GCS do Ray em :6379, sem autenticação, só durante o teste.
apiVersion: v1
kind: Pod
metadata: {name: qual-ray-worker, namespace: vllm-estudo, labels: {app: qual-ray, teste: qualidade}}
spec:
  nodeSelector: {kubernetes.io/hostname: sabdiia02}
  hostNetwork: true
  restartPolicy: Never
  containers:
  - name: ray
    image: vllm/vllm-openai:v0.19.1
    command: ["/bin/bash", "-c"]
    args:
    - |
      set -e
      python3 -c "import ray" 2>/dev/null || uv pip install --system "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0" || python3 -m pip install "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0"
      __BAIXA__
      until timeout 3 bash -c '</dev/tcp/192.168.50.151/6379'; do echo "aguardando o head..."; sleep 5; done
      exec ray start --address=192.168.50.151:6379 --node-ip-address=192.168.50.152 --num-gpus=1 --object-store-memory=4000000000 --block
    env:
    - {name: HF_HOME, value: /hf-cache}
    - {name: HF_HUB_OFFLINE, value: "1"}
    - {name: VLLM_HOST_IP, value: "192.168.50.152"}
    - {name: NCCL_SOCKET_IFNAME, value: bond0.500}
    - {name: GLOO_SOCKET_IFNAME, value: bond0.500}
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
    emptyDir: {medium: Memory, sizeLimit: 16Gi}
---
apiVersion: v1
kind: Pod
metadata: {name: qual-ray-head, namespace: vllm-estudo, labels: {app: qual-ray, teste: qualidade}}
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
      python3 -c "import ray" 2>/dev/null || uv pip install --system "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0" || python3 -m pip install "ray[cgraph,default]==2.48.0" "cupy-cuda12x==13.6.0"
      __BAIXA__
      ray start --head --node-ip-address=192.168.50.151 --port=6379 --num-gpus=1 --object-store-memory=4000000000
      until python3 -c "import ray, sys; ray.init(address='auto', logging_level='ERROR'); sys.exit(0 if ray.cluster_resources().get('GPU', 0) >= 2 else 1)" 2>/dev/null; do sleep 10; done
      ray status
      exec vllm serve __MODELO__ --pipeline-parallel-size 2 --distributed-executor-backend ray __FLAGS__
    env:
    - {name: HF_HOME, value: /hf-cache}
    - {name: HF_HUB_OFFLINE, value: "1"}
    - {name: VLLM_HOST_IP, value: "192.168.50.151"}
    - {name: NCCL_SOCKET_IFNAME, value: bond0.500}
    - {name: GLOO_SOCKET_IFNAME, value: bond0.500}
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
    emptyDir: {medium: Memory, sizeLimit: 16Gi}
EOF
fi
# Troca as marcas internas do modelo (não é para editar à mão). Substituição do bash: o texto de BAIXA tem "||".
MF=$(cat "$D/manifesto.yaml"); MF=${MF//__BAIXA__/"$BAIXA"}; MF=${MF//__FLAGS__/"$FLAGS"}; MF=${MF//__MODELO__/"$MODELO"}
printf '%s\n' "$MF" > "$D/manifesto.yaml"
grep -q '__' "$D/manifesto.yaml" && { echo "ABORTA: marca não substituída no manifesto"; grep -n '__' "$D/manifesto.yaml"; exit 1; }
grep -nE 'vllm serve|snapshot_download' "$D/manifesto.yaml" | cut -c1-260
kubectl apply -f "$D/manifesto.yaml" || exit 1

echo "### 3. aguardando o servidor (até 60 min)   $(date +%T)"
T0=$(date +%s); PRONTO=0
while [ $(( $(date +%s) - T0 )) -lt 3600 ]; do
  H=$(kubectl get pod -n $NS $SRV -o jsonpath='{.status.phase}/{.status.containerStatuses[0].ready}' 2>/dev/null)
  [ "$H" = "Running/true" ] && { PRONTO=1; break; }
  case "$H" in Failed*|Succeeded*) echo "o servidor terminou: $H"; break;; esac
  for p in $GPODS; do case "$(kubectl get pod -n $NS $p -o jsonpath='{.status.phase}' 2>/dev/null)" in Failed|Succeeded) echo "$p terminou"; break 2;; esac; done
  echo "$(date +%T) $SRV=$H | $(kubectl logs -n $NS $SRV --tail=1 2>/dev/null | cut -c1-160)"
  sleep 30
done
echo "pronto=$PRONTO depois de $(( ($(date +%s) - T0) / 60 )) min"
kubectl get pods -n $NS -o wide

if [ $PRONTO = 1 ]; then
  X() { kubectl exec -i -n $NS $SRV -- "$@"; }
  echo "### 4. servidor: versão, comando, parser de tool call"
  X python3 -c 'import vllm;print("vllm", vllm.__version__)'
  X sh -c 'for p in /proc/[0-9]*/cmdline; do tr "\0" " " < $p 2>/dev/null | grep -E "vllm serve" ; done | sort -u | cut -c1-600'
  kubectl logs -n $NS $SRV --tail=-1 | grep -iE 'tool|Model loading took|GPU KV cache size|Maximum concurrency' | grep -vE 'POST /v1|GET /' | cut -c1-250 | head -20
  echo "### 5. coleta: 50 perguntas x 2 chamadas, 1 de cada vez   $(date +%T)"
  X sh -c 'cat > /tmp/gabarito-qualidade.json' < gabarito-qualidade.json
  X python3 - /tmp/gabarito-qualidade.json < coletar-respostas.py > "$D/respostas.jsonl"
  echo "linhas gravadas: $(wc -l < "$D/respostas.jsonl") (esperado 51)   $(date +%T)"
  echo "### 6. nota"
  X sh -c 'cat > /tmp/respostas.jsonl' < "$D/respostas.jsonl"
  X python3 - /tmp/gabarito-qualidade.json /tmp/respostas.jsonl < pontuar-respostas.py > "$D/resultado.md"
  cat "$D/resultado.md"
  if [ "$C" = 7b-ray ]; then
    B=$(ls -d $Q/resultados/*-7b 2>/dev/null | tail -1)
    echo "### 6b. controle: 7b-ray x $B"
    if [ -s "$B/respostas.jsonl" ]; then
      X sh -c 'cat > /tmp/base.jsonl' < "$B/respostas.jsonl"
      X python3 - /tmp/gabarito-qualidade.json /tmp/base.jsonl --comparar /tmp/respostas.jsonl < pontuar-respostas.py > "$D/controle.md"
      cat "$D/controle.md"
    else
      echo "sem coleta do 7b em 1 GPU: rode antes 'bash qualidade.sh 7b'"
    fi
  fi
  echo "### 7. estrangulamento de 01 depois da coleta (a nota não depende dele; a latência sim)"
  nvidia-smi -q -d PERFORMANCE | grep -iE 'thermal|slowdown|power cap'
else
  echo "### 4. FALHOU A SUBIDA: eventos"
  kubectl describe pod -n $NS $GPODS | grep -A15 '^Events:'
fi

echo "### 8. logs dos pods em $D"
for p in $GPODS; do
  kubectl logs -n $NS $p > "$D/$p.log" 2>&1
  echo "## $p ($(wc -l < "$D/$p.log") linhas): fim"; tail -15 "$D/$p.log" | cut -c1-250
done

echo "### 9. limpeza: apaga os pods e libera as GPUs   $(date +%T)"
kubectl delete pod -n $NS $GPODS --wait=true --timeout=180s
kubectl describe nodes $NOS | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
echo "== fim $(date -Is)   resultados em $D"
