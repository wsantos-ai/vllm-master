# Runbook — Primeiro arranque do vLLM `v0.19.1` na V100S, em `sabdiia01`

**Pergunta:** a imagem `vllm/vllm-openai:v0.19.1` sobe, gera texto e escolhe *attention* Triton numa
Tesla V100S (`sm_70`)? Fecha a PD-03 e confirma ou derruba a decisão D-01
([ESTUDO-DE-CASO.md](../ESTUDO-DE-CASO.md#ac-11)).

**Expectativa escrita antes:** depois de liberar a GPU e a imagem `v0.12.0` de `sabdiia01`, sobram cerca
de 46 G livres em `/`; a `v0.19.1` baixa e ocupa 27 a 32 G; o *pod* fica `Ready`; o log mostra FP16,
*attention* Triton, blocos de *KV cache* e captura de *CUDA graphs*; a geração responde; nenhuma mensagem
`no kernel image is available` nem `Illegal instruction`.

**Versão anterior deste runbook** (2026-09-29) mirava `sabdiia02` e ficou bloqueada por disco (AC-09).
Esta versão, de 2026-10-02, troca de nó por decisão do usuário.

## Por que `sabdiia01`, e o que isso custa

| Passo | O que muda | Reversível? |
|---|---|---|
| Desligar `vllm-llama31-8b` (`--replicas=0`) | libera a GPU de `sabdiia01`. O *pod* cai em *loop* desde 2026-09-21 e nunca serviu nada (AC-07) | sim: `--replicas=1` |
| Remover a imagem `v0.12.0` do nó | libera ~26 G em `/` `[estimativa]`. Sem isso a `v0.19.1` não cabe | sim, mas religar o Llama exigiria baixar a `v0.12.0` de novo, e as duas imagens **não cabem juntas** |

Os dois passos **alteram o *cluster***: o primeiro mexe no *namespace* `vllms`, o segundo no disco do nó.
`sabdiia01` também é *control-plane*. Combine com o administrador.

**Conta de disco em `sabdiia01`** (`/` de 70 G; o *kubelet* reage aos 59,5 G usados, AC-09):

| Momento | Usado | Livre |
|---|---|---|
| Antes (2026-10-02 12:47) | 51 G | 20 G |
| Depois de remover a `v0.12.0` (**medido** 12:53: liberou 27 G) | 24 G | 47 G |
| Depois de baixar a `v0.19.1` (~29 G `[cálculo: 3,3× o comprimido]`) | ~53 G | ~18 G |

Estado: Passos 1, 2 e 3 **executados em 2026-10-02**. Falta o Passo 4.

A margem é curta. Por isso o Passo 4 só começa com **40 G livres ou mais** e para sozinho se o espaço
cair a **12 G livres** (58 G usados, antes dos 59,5 G).

**Rede:** a porta a 100 Mbps de `sabdiia01` está fora do agregado LACP e não carrega dados (AC-08,
conferido em 2026-10-02). O *download* sai pelas portas de 1 Gbps, como nos outros nós.

## Por que a remoção em `sabdiia02` não liberou espaço `[hipótese]`

O containerd, quando usado pelo Kubernetes, guarda **três referências** para cada imagem: o nome com
*tag* (`vllm/vllm-openai:v0.6.4`), o nome com *digest* (`...@sha256:...`) e o identificador da imagem
(`sha256:<id>`). Em `sabdiia02` foram removidas só as duas primeiras, que eram as que o filtro por nome
mostrava. A terceira deve ter continuado apontando para as camadas, e por isso nada foi liberado. O Passo
1 mostra as três referências da `v0.12.0`, e o Passo 3 remove todas pelo *digest* e mede o disco antes e
depois. Se o espaço não for liberado, o Passo 4 não começa.

---

## Passo 1 — Estado de partida (servidor, bash, **em `sabdiia01`**; só leitura)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### nó: $(hostname)   $(date '+%F %T')"
  echo "### disco";                      df -h /;  du -sh /var/lib/containerd
  echo "### GPU reservada neste nó";     kubectl describe node sabdiia01 | grep -E '^  nvidia\.com/gpu +[0-9]'
  echo "### pods com GPU";               kubectl get pods -A -o wide --field-selector spec.nodeName=sabdiia01 | grep -E 'NAMESPACE|vllm'
  echo "### deployment do Llama";        kubectl get deploy -n vllms vllm-llama31-8b
  echo "### digest da v0.12.0"
  D=$(ctr -n k8s.io images ls | awk '$1=="docker.io/vllm/vllm-openai:v0.12.0"{print $3}')
  echo "$D"
  echo "### todas as referências com esse digest (espera-se 3)"
  ctr -n k8s.io images ls | awk -v d="$D" '$3==d{print $1, $4, $5}'
  echo "### uso real da GPU";            nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv
} 2>&1 | tee pre-arranque-$(hostname -s)-$(date +%F-%H%M).log
```

O que olhar: se aparecem **três** referências com o mesmo *digest* (confirma a hipótese acima), e se a
GPU está com 0 MiB em uso.

## Passo 2 — Desligar o `vllm-llama31-8b` (servidor, bash, em `sabdiia01`; **ALTERA `vllms`**)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "### $(date '+%F %T') antes";     kubectl get deploy,pods -n vllms -o wide
  kubectl scale deploy/vllm-llama31-8b -n vllms --replicas=0
  kubectl wait --for=delete pod -l app=vllm-llama31-8b -n vllms --timeout=180s
  echo "### depois";                     kubectl get deploy,pods -n vllms -o wide
  echo "### GPU reservada em sabdiia01 (espera-se 0 0)"
  kubectl describe node sabdiia01 | grep -E '^  nvidia\.com/gpu +[0-9]'
} 2>&1 | tee desliga-llama-$(hostname -s)-$(date +%F-%H%M).log
```

Para desfazer: `kubectl scale deploy/vllm-llama31-8b -n vllms --replicas=1` (ele volta a cair em *loop*
enquanto o *token* do `hf-secret` for inválido).

## Passo 3 — Remover a imagem `v0.12.0` do nó (servidor, bash, em `sabdiia01`; **ALTERA o nó**)

Só depois do Passo 2: com o *pod* no ar, a imagem está em uso.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  livre() { df --output=avail -BG / | tail -1 | tr -dc 0-9; }
  ANTES=$(livre)
  echo "### $(date '+%F %T') antes: ${ANTES}G livres";  du -sh /var/lib/containerd
  D=$(ctr -n k8s.io images ls | awk '$1=="docker.io/vllm/vllm-openai:v0.12.0"{print $3}')
  echo "### digest: $D"
  if [ -z "$D" ]; then
    echo "### imagem v0.12.0 não encontrada: nada a remover"
  else
    echo "### removendo todas as referências com esse digest"
    ctr -n k8s.io images ls | awk -v d="$D" '$3==d{print $1}' | xargs -r ctr -n k8s.io images rm --sync
  fi
  sleep 20
  DEPOIS=$(livre)
  echo "### depois: ${DEPOIS}G livres (liberou $((DEPOIS-ANTES))G)";  df -h /;  du -sh /var/lib/containerd
  echo "### imagens de vLLM restantes";  ctr -n k8s.io images ls | awk 'NR==1 || /vllm/'
  if [ "$DEPOIS" -ge 40 ]; then echo "### OK: há espaço para o Passo 4"; else echo "### NÃO SIGA para o Passo 4: menos de 40G livres"; fi
} 2>&1 | tee remocao-v0120-$(hostname -s)-$(date +%F-%H%M).log
```

O que olhar: quantos G foram liberados. É a primeira medida real do custo em disco de uma imagem do
vLLM, e confirma ou derruba a hipótese das três referências.

## Passo 4 — Arranque e teste de geração (servidor, bash, **em `sabdiia01`**)

Cria o *namespace* `vllm-estudo` e o *pod* `vllm-teste`. Não começa com menos de 40 G livres. Durante o
*download*, mede o disco a cada 5 s e **apaga o *pod* se sobrarem 12 G ou menos**. Espera até 40 min. Ao
final, o *pod* continua no ar para inspeção (o Passo 5 remove).

| Item do *pod* | Valor | Por quê |
|---|---|---|
| Modelo | `Qwen/Qwen2.5-0.5B-Instruct` | público (sem `HF_TOKEN`, AC-07), ~1 GB |
| `--dtype` | `float16` | BF16 é recusado em CC < 8.0 (AC-11) |
| `--gpu-memory-utilization` | `0.90` | igual ao deepseek (AC-05) |
| *Eager* | não | queremos saber se *CUDA graphs* funcionam em `sm_70` |
| Cache de modelos | `hostPath` em `/home/utec/vllm-estudo/hf-cache` | disco local com 755 G livres (AC-09) |
| Exposição | nenhuma; teste por `kubectl port-forward` | AC-06 |
| Reinício | `restartPolicy: Never` | se cair, fica caído com o log |

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  livre() { df --output=avail -BG / | tail -1 | tr -dc 0-9; }
  echo "### nó: $(hostname)   início: $(date '+%F %T')   livres: $(livre)G"
  if [ "$(livre)" -lt 40 ]; then
    echo "### ABORTADO: menos de 40G livres em /. Nada foi criado."
  else
    kubectl create namespace vllm-estudo --dry-run=client -o yaml | kubectl apply -f -
    kubectl delete pod -n vllm-estudo vllm-teste --ignore-not-found
    kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: vllm-teste
  namespace: vllm-estudo
  labels:
    app: vllm-teste
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: sabdiia01
  containers:
  - name: vllm
    image: vllm/vllm-openai:v0.19.1
    command: ["vllm", "serve"]
    args:
    - Qwen/Qwen2.5-0.5B-Instruct
    - --dtype
    - float16
    - --max-model-len
    - "4096"
    - --gpu-memory-utilization
    - "0.90"
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
        memory: 16Gi
        nvidia.com/gpu: 1
      limits:
        cpu: "8"
        memory: 32Gi
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
    echo "### linha do tempo (a cada 5 s): hora | G livres em / | fase | motivo de espera | ready"
    PARADA="tempo esgotado (40 min)"
    for i in $(seq 1 480); do
      L=$(livre)
      PH=$(kubectl get pod -n vllm-estudo vllm-teste -o jsonpath='{.status.phase}' 2>/dev/null)
      ES=$(kubectl get pod -n vllm-estudo vllm-teste -o jsonpath='{.status.containerStatuses[0].state.waiting.reason}' 2>/dev/null)
      RD=$(kubectl get pod -n vllm-estudo vllm-teste -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null)
      echo "$(date +%T) | ${L}G | ${PH:--} | ${ES:--} | ${RD:--}"
      if [ "$L" -le 12 ]; then PARADA="FREIO DE DISCO: ${L}G livres"; kubectl delete pod -n vllm-estudo vllm-teste --wait=false; break; fi
      if [ "$RD" = "true" ]; then PARADA="pod Ready"; break; fi
      if [ "$PH" = "Failed" ] || [ "$PH" = "Succeeded" ]; then PARADA="contêiner terminou (fase $PH)"; break; fi
      if [ "$ES" = "ErrImagePull" ] || [ "$ES" = "ImagePullBackOff" ]; then PARADA="erro ao baixar a imagem: $ES"; break; fi
      sleep 5
    done
    echo "### PARADA: $PARADA   em $(date '+%F %T')   livres: $(livre)G"
    echo "### estado e eventos"
    kubectl get pod -n vllm-estudo vllm-teste -o wide
    kubectl describe pod -n vllm-estudo vllm-teste | sed -n '/^Events:/,$p'
    echo "### condições do nó";  kubectl describe node sabdiia01 | grep -E 'DiskPressure|^Taints'
    echo "### disco depois";     df -h /;  du -sh /var/lib/containerd
    echo "### imagens de vLLM";  ctr -n k8s.io images ls | awk 'NR==1 || /vllm/'
    if [ "$PARADA" = "pod Ready" ]; then
      echo "### teste de geração"
      kubectl port-forward -n vllm-estudo pod/vllm-teste 18000:8000 >/dev/null 2>&1 &
      PF=$!
      sleep 3
      curl -s --max-time 10 http://localhost:18000/version; echo
      curl -s --max-time 120 http://localhost:18000/v1/completions -H 'Content-Type: application/json' \
        -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","prompt":"A capital do Brasil é","max_tokens":20,"temperature":0}'; echo
      kill $PF
      echo "### GPU com o modelo carregado";  nvidia-smi --query-gpu=memory.used,memory.total --format=csv
    fi
    echo "### linhas-chave do arranque"
    kubectl logs -n vllm-estudo vllm-teste | grep -iE 'version|backend|dtype|KV cache|CUDA graph|memory|error|no kernel image|illegal'
    echo "### log de arranque completo"
    kubectl logs -n vllm-estudo vllm-teste
  fi
} 2>&1 | tee primeiro-arranque-v0.19.1-$(hostname -s)-$(date +%F-%H%M).log
```

O que olhar:

- **Linha do tempo:** quanto o disco caiu durante o *download* (o custo real da imagem), quanto tempo em
  `ContainerCreating` e quanto em `Running` até `ready=true` (PD-04, PD-11).
- **`### PARADA`:** `pod Ready` é o sucesso. `FREIO DE DISCO` significa que a imagem não coube.
- ***Backend* de *attention*:** confirma ou derruba "Triton" em AC-11.
- **Erros:** `no kernel image is available for execution on the device` = imagem sem `sm_70`;
  `Illegal instruction` = binário exige instrução que a CPU não tem (AVX2).
- **Geração:** a resposta JSON precisa trazer texto em `choices[0].text`.

**Se parar por `FREIO DE DISCO` e o espaço continuar caindo:** o containerd seguiu o *download* sem o
*pod*. Avise o administrador. Último recurso, em `sabdiia01`: `systemctl restart containerd` interrompe
os *downloads* `[não verificado neste ambiente]`.

## Passo 4b — Retomar um arranque interrompido (servidor, bash, em `sabdiia01`)

**Não interrompa o Passo 4 com Ctrl+C.** Isso para só o monitoramento: o *pod* continua existindo e o
*kubelet* segue baixando a imagem, sem freio de disco. Para parar de verdade, use
`kubectl delete pod -n vllm-estudo vllm-teste`.

Aconteceu em 2026-10-02: a primeira tentativa foi interrompida por engano depois de criar o *pod*. Às
14:06 o Passo 4 foi rodado de novo e abortou com "menos de 40G livres" (28 G), porque a imagem já tinha
consumido 19 G. O bloco abaixo **não recria o *pod***: acompanha o que já existe, com o mesmo freio, e
faz o teste e a gravação do log.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  livre() { df --output=avail -BG / | tail -1 | tr -dc 0-9; }
  echo "### nó: $(hostname)   retomada: $(date '+%F %T')   livres: $(livre)G"
  echo "### pod existente";   kubectl get pod -n vllm-estudo vllm-teste -o wide
  echo "### criado em";       kubectl get pod -n vllm-estudo vllm-teste -o jsonpath='{.metadata.creationTimestamp}'; echo
  echo "### imagens de vLLM"; ctr -n k8s.io images ls | awk 'NR==1 || /vllm/'
  if ! kubectl get pod -n vllm-estudo vllm-teste >/dev/null 2>&1; then
    echo "### o pod vllm-teste não existe: nada a retomar"
  else
    echo "### linha do tempo (a cada 5 s): hora | G livres em / | fase | motivo de espera | ready"
    PARADA="tempo esgotado (40 min)"
    for i in $(seq 1 480); do
      L=$(livre)
      PH=$(kubectl get pod -n vllm-estudo vllm-teste -o jsonpath='{.status.phase}' 2>/dev/null)
      ES=$(kubectl get pod -n vllm-estudo vllm-teste -o jsonpath='{.status.containerStatuses[0].state.waiting.reason}' 2>/dev/null)
      RD=$(kubectl get pod -n vllm-estudo vllm-teste -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null)
      echo "$(date +%T) | ${L}G | ${PH:--} | ${ES:--} | ${RD:--}"
      if [ "$L" -le 12 ]; then PARADA="FREIO DE DISCO: ${L}G livres"; kubectl delete pod -n vllm-estudo vllm-teste --wait=false; break; fi
      if [ "$RD" = "true" ]; then PARADA="pod Ready"; break; fi
      if [ "$PH" = "Failed" ] || [ "$PH" = "Succeeded" ]; then PARADA="contêiner terminou (fase $PH)"; break; fi
      if [ "$ES" = "ErrImagePull" ] || [ "$ES" = "ImagePullBackOff" ]; then PARADA="erro ao baixar a imagem: $ES"; break; fi
      sleep 5
    done
    echo "### PARADA: $PARADA   em $(date '+%F %T')   livres: $(livre)G"
    echo "### estado e eventos"
    kubectl get pod -n vllm-estudo vllm-teste -o wide
    kubectl describe pod -n vllm-estudo vllm-teste | sed -n '/^Events:/,$p'
    echo "### início e fim do contêiner"
    kubectl get pod -n vllm-estudo vllm-teste -o jsonpath='{.status.containerStatuses[0].state}'; echo
    echo "### condições do nó";  kubectl describe node sabdiia01 | grep -E 'DiskPressure|^Taints'
    echo "### disco depois";     df -h /;  du -sh /var/lib/containerd
    echo "### imagens de vLLM";  ctr -n k8s.io images ls | awk 'NR==1 || /vllm/'
    if [ "$PARADA" = "pod Ready" ]; then
      echo "### teste de geração"
      kubectl port-forward -n vllm-estudo pod/vllm-teste 18000:8000 >/dev/null 2>&1 &
      PF=$!
      sleep 3
      curl -s --max-time 10 http://localhost:18000/version; echo
      curl -s --max-time 120 http://localhost:18000/v1/completions -H 'Content-Type: application/json' \
        -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","prompt":"A capital do Brasil é","max_tokens":20,"temperature":0}'; echo
      kill $PF
      echo "### GPU com o modelo carregado";  nvidia-smi --query-gpu=memory.used,memory.total --format=csv
    fi
    echo "### linhas-chave do arranque"
    kubectl logs -n vllm-estudo vllm-teste | grep -iE 'version|backend|dtype|KV cache|CUDA graph|memory|error|no kernel image|illegal'
    echo "### log de arranque completo"
    kubectl logs -n vllm-estudo vllm-teste
  fi
} 2>&1 | tee primeiro-arranque-v0.19.1-retomada-$(hostname -s)-$(date +%F-%H%M).log
```

## Passo 5 — Limpeza, quando terminar a inspeção (servidor, bash, qualquer nó com `kubectl`)

Libera a GPU de `sabdiia01`. Mantém o *namespace*, a imagem `v0.19.1` no nó e o cache do modelo em
`/home` para os próximos testes.

```bash
kubectl delete pod -n vllm-estudo vllm-teste
```

Traga os logs dos Passos 1 a 4 com o `scp` do topo do [runbook de inventário](inventario-do-ambiente.md):
ficam em `/home/utec/vllm-estudo/` de `sabdiia01`.
