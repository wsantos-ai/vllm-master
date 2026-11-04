# Runbook — Pausar e restaurar os serviços de `vllms` (janela de teste combinada com o administrador)

**Só com o acordo do administrador.** Enquanto a pausa durar, a API de produção e o Ray dele ficam fora do
ar. Nada é apagado:

- *Deployments* e *StatefulSets* com réplicas vão a `0`;
- *DaemonSets* (os `ray-worker-*`) recebem o `nodeSelector` `vllm-estudo/pausado: "true"`, que nenhum nó
  tem, e por isso os *pods* deles saem;
- antes, o bloco grava `vllms-backup-<data>.yaml` (manifestos completos) e `vllms-replicas-<data>.txt`
  (réplicas de cada um), que o bloco de restauração lê.

*Pods* sem dono (criados à mão) não são parados: o bloco só os lista.

## Bloco P — Pausar (servidor `sabdiia01` ou `sabdiia02`, bash)

**Expectativa (escrita antes; estado de 2026-11-03, §2):** `vllm-server` vai de 3 para 0 (não há
como pausar só a réplica de um nó: a pausa derruba as 3); o *DaemonSet* `ray-worker` sai dos 3 nós;
`nvidia.com/gpu 0 0` em 01 e 02 em até ~2 min. Se a lista do passo 1 trouxer outros recursos, eles
também vão a 0 e voltam no Bloco R. (Na 1ª pausa, P-05 em 2026-11-03, eram `vllm-server`,
`vllm-llama31` e `ray-head` com 1 réplica cada, mais os `ray-worker-*`.)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  N=$(hostname -s); TS=$(date +%F-%H%M); echo "== $N  $(date -Is)  pausa de vllms"
  case "$N" in sabdiia01|sabdiia02) ;; *) echo "ABORTA: rode em sabdiia01 ou sabdiia02 (kubectl)"; exit 1;; esac

  echo "### 1. estado antes"
  kubectl get deploy,sts,ds,pods -n vllms -o wide
  kubectl describe nodes sabdiia01 sabdiia02 sabdiia03 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'

  echo "### 2. cópia de segurança"
  kubectl get deploy,sts,ds -n vllms -o yaml > vllms-backup-$TS.yaml || { echo "ABORTA: não consegui gravar a cópia"; exit 1; }
  { kubectl get deploy,sts -n vllms -o jsonpath='{range .items[*]}{.kind}/{.metadata.name} {.spec.replicas}{"\n"}{end}'
    kubectl get ds -n vllms -o jsonpath='{range .items[*]}{.kind}/{.metadata.name} ds{"\n"}{end}'; } | tr 'A-Z' 'a-z' > vllms-replicas-$TS.txt
  echo "vllms-backup-$TS.yaml: $(wc -l < vllms-backup-$TS.yaml) linhas"; echo "## vllms-replicas-$TS.txt"; cat vllms-replicas-$TS.txt
  echo "## pods sem dono (não são parados por este bloco)"
  kubectl get pods -n vllms --no-headers -o custom-columns='POD:.metadata.name,DONO:.metadata.ownerReferences[0].kind' | awk '$2=="<none>"' | grep . || echo "(nenhum)"

  echo "### 3. pausando   $(date +%T)"
  while read o r; do
    case "$r" in
      ds) kubectl patch -n vllms "$o" -p '{"spec":{"template":{"spec":{"nodeSelector":{"vllm-estudo/pausado":"true"}}}}}' ;;
      *)  [ "${r:-0}" -gt 0 ] && kubectl scale -n vllms "$o" --replicas=0 ;;
    esac
  done < vllms-replicas-$TS.txt

  echo "### 4. aguardando os pods saírem (até 5 min)"
  for i in $(seq 1 30); do
    R=$(kubectl get pods -n vllms --no-headers 2>/dev/null | grep -E 'ray|vllm')
    [ -z "$R" ] && break
    echo "$(date +%T) ainda: $(echo "$R" | awk '{print $1"("$3")"}' | tr '\n' ' ')"; sleep 10
  done

  echo "### 5. estado depois"
  kubectl get deploy,sts,ds,pods -n vllms -o wide
  kubectl describe nodes sabdiia01 sabdiia02 sabdiia03 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  P=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader); echo "processos na GPU de $N: ${P:-(nenhum)}"
  echo "Para restaurar: Bloco R de runbooks/pausar-vllms.md (lê vllms-replicas-$TS.txt)"
  echo "== fim $(date -Is)"
} 2>&1 | tee pausar-vllms-$(hostname -s)-$(date +%F-%H%M).log
```

Depois: **Bloco 0** de [teste-protocolo-modelos.md](teste-protocolo-modelos.md) em 01 e 02 (`PRONTO` nos
dois). O `nvidia-smi` acima só vê a GPU do nó onde o bloco rodou.

## Bloco R — Restaurar (servidor, bash, **no mesmo nó do Bloco P**: os arquivos ficaram nele)

Rode depois do fim do teste. O teste é que libera as GPUs: o `qualidade.sh` apaga os próprios *pods*
no fim de cada candidato, e no P-05 isso cabia ao Bloco B. O aviso do bloco mostra se sobrou algum.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  N=$(hostname -s); echo "== $N  $(date -Is)  restauração de vllms"
  case "$N" in sabdiia01|sabdiia02) ;; *) echo "ABORTA: rode em sabdiia01 ou sabdiia02 (kubectl)"; exit 1;; esac
  F=$(ls -t vllms-replicas-*.txt 2>/dev/null | head -1)
  [ -n "$F" ] || { echo "ABORTA: nenhum vllms-replicas-*.txt neste nó; rode no nó onde o Bloco P rodou"; exit 1; }
  echo "restaurando a partir de $F"; cat "$F"
  kubectl get pods -n vllm-estudo --no-headers 2>/dev/null | grep . && echo "AVISO: ainda há pods em vllm-estudo; eles seguram GPU e os do administrador podem ficar Pending"

  echo "### 1. restaurando   $(date +%T)"
  while read o r; do
    case "$r" in
      ds) kubectl patch -n vllms "$o" --type=json -p '[{"op":"remove","path":"/spec/template/spec/nodeSelector/vllm-estudo~1pausado"}]' ;;
      *)  [ "${r:-0}" -gt 0 ] && kubectl scale -n vllms "$o" --replicas="$r" ;;
    esac
  done < "$F"

  echo "### 2. estado depois de 90 s"
  sleep 90
  kubectl get deploy,sts,ds,pods -n vllms -o wide
  kubectl describe nodes sabdiia01 sabdiia02 sabdiia03 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  echo "== fim $(date -Is)"
} 2>&1 | tee restaurar-vllms-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** as réplicas voltam aos números de `vllms-replicas-*.txt` e os *pods* ficam `Running`. O
vLLM do administrador leva alguns minutos para carregar o modelo; isso é dele, não do bloco.

**Se a restauração falhar** (erro de permissão, *pod* `Pending`): a cópia completa está em
`vllms-backup-<data>.yaml`. Leve o log e a cópia ao administrador; não reaplique a cópia por conta própria.
