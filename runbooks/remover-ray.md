# Runbook — Eliminar o Ray do *cluster* e dos *hosts* (D-07)

**Decisão** (usuário com o administrador, 2026-11-07): o Ray sai por completo. A aplicação usa 3 réplicas
independentes do vLLM, uma por GPU (D-04, D-06), e não precisa dele. Dividir um modelo entre nós pelo Ray
rendeu menos que 1 GPU (AC-23) e respondeu sem sentido a *prompts* longos (AC-27).

**Riscos que a remoção elimina:**
- **GPU tomada sem aviso:** o Ray do *host* ocupa GPU sem o Kubernetes saber (AC-19), e a réplica do
  `vllm-server` daquele nó cai por falta de memória;
- **GPU reservada no Kubernetes:** o *DaemonSet* `ray-worker` reservava as GPUs dos 3 nós (AC-19);
- **portas abertas sem autenticação**, num nó `control-plane`: GCS `:6379`, painel `:8265`, cliente `:10001`.
  O painel e o GCS aceitam *jobs*, ou seja, execução de código (AC-19, `[não verificado na versão em uso]`).

| Bloco | Onde | O que faz | Altera algo? |
|---|---|---|---|
| K1 | `sabdiia01`, bash | Lista o que é Ray no Kubernetes (*workloads* por nome ou imagem, `Services` nas portas do Ray, CRDs do KubeRay), guarda cópia e apaga o que estiver em `vllms` ou `vllm-estudo` | Apaga o `ray-worker` e afins |
| H0 | **cada um dos 3 nós**, bash como `root` | Inventário do Ray no *host*: processos, portas, GPU, contêineres Docker e Podman, início automático (systemd, cron), *venv* | Não |
| H1 | **cada nó onde o H0 achou algo**, bash como `root` | Para o Ray, apaga os contêineres e imagens dele, desliga unidades systemd, confere portas e GPU | Sim |

**Ordem:** K1; H0 nos 3 nós; H1 onde o H0 achou algo; H0 de novo (conferência). O `vllm-server` adotado
(D-06) não é tocado: os filtros ignoram o rótulo `decisao=d-05` e a imagem `vllm/vllm-openai`.

**O que fica de fora, de propósito:**
- O projeto e o *venv* do administrador (`/home/utec/llm_lhama_prototype`) não são apagados: é código dele.
  Sem processo e sem início automático, não executa nada. Apagar é com ele.
- Uma linha de `cron` não é editada automaticamente: o H0 mostra a linha, e a remoção é manual (comando no
  fim). Editar `crontab` por script já apagou linhas vizinhas em outros ambientes `[hipótese de risco]`.
- Imagens do Ray no containerd do Kubernetes (`rayproject/ray:latest-gpu`) ficam: sem *pod*, não executam, e
  remoção de imagem do containerd só se faz por *digest* (AC-09).

---

## Expectativa (escrita antes)

- **K1:** o *DaemonSet* `vllms/ray-worker` (`rayproject/ray:latest-gpu`), sem *pods* se o Bloco P o tirou dos
  nós; nenhum `Service` nas portas do Ray (o `ray-head` com `192.168.50.160` não aparecia em 2026-11-07);
  nenhuma CRD `ray.io`. Em `vllm-estudo`, nada: o Ray do estudo é apagado pelo próprio *runbook* (AC-23).
- **H0:** em 01 e 02, os contêineres `ray-head-node` e `ray-worker-node` parados (`Exited`) e o *venv* com
  `bin/ray` (AC-19); processos e portas só se o administrador tiver ligado o Ray de novo. Em 03, nada
  `[hipótese]`. O jeito como o Ray do *host* era iniciado não está registrado: o H0 procura systemd e cron.
- **H1:** sem processo, sem porta 6379/8265/10001, sem contêiner com `ray`; a GPU só com o `vllm-server`.

---

## Bloco K1 — Ray no Kubernetes (servidor `sabdiia01`, bash)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  D-07 K1: Ray no Kubernetes, inventário e remoção"
  case "$(hostname -s)" in sabdiia01|sabdiia02) ;; *) echo "ABORTA: kubectl só em 01 ou 02"; exit 1;; esac
  TS=$(date +%F-%H%M); B=ray-k8s-copia-$TS.yaml; : > $B; chmod 600 $B
  RX='(^|[-_/ ])ray([-_:/ ]|$)|rayproject'

  echo "### 1. CRDs do KubeRay"
  kubectl get crd 2>/dev/null | grep -i 'ray\.io' || echo "nenhuma CRD ray.io"

  echo "### 2. workloads com ray no nome ou na imagem (fora do estudo: decisao!=d-05)"
  W=$(kubectl get deploy,sts,ds,job -A -o jsonpath='{range .items[*]}{.kind}|{.metadata.namespace}|{.metadata.name}|{.spec.template.spec.containers[*].image}|{.metadata.labels.decisao}{"\n"}{end}' | awk -F'|' -v rx="$RX" 'tolower($3" "$4) ~ rx && $5!="d-05"')
  echo "${W:-(nenhum)}"

  echo "### 3. Services com ray no nome ou nas portas do Ray (6379, 8265, 10001)"
  S=$(kubectl get svc -A -o jsonpath='{range .items[*]}Service|{.metadata.namespace}|{.metadata.name}|{.spec.type} {.spec.ports[*].port}|{.metadata.labels.decisao}{"\n"}{end}' | awk -F'|' -v rx="$RX" '(tolower($3) ~ rx || $4 ~ /(^| )(6379|8265|10001)( |$)/) && $5!="d-05"')
  echo "${S:-(nenhum)}"

  echo "### 4. cópia e remoção (só em vllms e vllm-estudo)   $(date +%T)"
  printf '%s\n%s\n' "$W" "$S" | grep . | while IFS='|' read -r K NS N _; do
    case "$NS" in
      vllms|vllm-estudo)
        echo "--- $K $NS/$N" >> $B; kubectl get "$K" "$N" -n "$NS" -o yaml >> $B
        kubectl delete "$K" "$N" -n "$NS" --wait=true --timeout=120s ;;
      *) echo "AVISO: $K $NS/$N está fora de vllms e vllm-estudo: não apagado; leve ao administrador" ;;
    esac
  done
  echo "cópia: $B ($(grep -c '^kind:' $B) objetos)"

  echo "### 5. conferência   $(date +%T)"
  # o delete do DaemonSet volta antes de os pods saírem (em 2026-11-07 seguiam Terminating 20 s depois)
  kubectl wait --for=delete pod -A -l app=ray-worker --timeout=180s 2>&1 | tail -3
  kubectl get pods -A -o wide | grep -iE "$RX" || echo "nenhum pod com ray"
  kubectl describe nodes sabdiia01 sabdiia02 sabdiia03 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  kubectl get deploy,ds,svc -n vllms -o wide
  echo "== fim $(date -Is)"
} 2>&1 | tee ray-k8s-remocao-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** a seção 4 apaga o `ray-worker` (e o que mais as seções 2 e 3 listarem em `vllms` ou
`vllm-estudo`); a seção 5 diz `nenhum pod com ray`; o `vllm-server` continua listado.

## Bloco H0 — Ray no *host*: inventário (cada um dos 3 nós, bash como `root`; só leitura)

Rode com `sudo -i` antes, em `sabdiia01`, `sabdiia02` e `sabdiia03`.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  D-07 H0: Ray no host, inventário (só leitura)"
  case "$(hostname -s)" in sabdiia01|sabdiia02|sabdiia03) ;; *) echo "ABORTA: nó desconhecido"; exit 1;; esac
  [ "$(id -u)" = 0 ] || { echo "ABORTA: rode como root (sudo -i)"; exit 1; }
  RX='(^|[-_/ ])ray([-_:/ ]|$)|rayproject'

  echo "### 1. processos do Ray"
  P=$(pgrep -af 'gcs_server|raylet|ray::|ray/dashboard|default_worker\.py|bin/ray ' | cut -c1-250); echo "${P:-(nenhum)}"

  echo "### 2. portas do Ray (6379 GCS, 8265 painel, 10001 cliente)"
  ss -ltnp | grep -E ':(6379|8265|10001)\b' || echo "(nenhuma)"

  echo "### 3. GPU"
  G=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>&1); echo "${G:-(nenhum processo na GPU)}"

  echo "### 4. contêineres e imagens com ray (Docker e Podman)"
  for E in docker podman; do
    command -v $E >/dev/null || { echo "$E: não instalado"; continue; }
    echo "$E: serviço $(systemctl is-active $E 2>&1); $($E ps -aq 2>&1 | grep -c .) contêineres no total"
    $E ps -a --format '{{.Names}}|{{.Image}}|{{.Status}}' 2>/dev/null | awk -F'|' -v rx="$RX" 'tolower($1" "$2) ~ rx' | while IFS='|' read -r N I ST; do
      echo "$E contêiner: $N | $I | $ST | restart=$($E inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$N" 2>/dev/null)"
    done
    $E images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}' 2>/dev/null | awk -v rx="$RX" 'tolower($1) ~ rx {print "'$E' imagem: " $0}'
  done

  echo "### 5. início automático"
  systemctl list-unit-files --no-pager --no-legend 2>/dev/null | awk 'tolower($1) ~ /ray/' | sed 's/^/systemd: /'
  grep -rlE 'ray start|llm_lhama' /etc/systemd /lib/systemd /usr/lib/systemd 2>/dev/null | sed 's/^/systemd (conteúdo): /'
  for U in $(ls /var/spool/cron/crontabs 2>/dev/null); do crontab -l -u "$U" 2>/dev/null | grep -nE 'ray|llm_lhama' | sed "s/^/cron de $U, linha /"; done
  grep -rnE 'ray start|llm_lhama' /etc/cron* /etc/rc.local 2>/dev/null | sed 's/^/sistema: /'

  echo "### 6. projeto e venv do administrador"
  ls -ld /home/utec/llm_lhama_prototype /home/utec/llm_lhama_prototype/venv 2>&1
  ls -l /home/utec/llm_lhama_prototype/venv/bin/ray 2>&1
  echo "== fim $(date -Is)"
} 2>&1 | tee ray-host-inventario-$(hostname -s)-$(date +%F-%H%M).log
```

**Leitura:** qualquer linha nas seções 1, 2, 4 ou 5 pede o H1 nesse nó. Uma linha de `cron` se remove à mão:
`crontab -e -u <usuário da linha>` e apague só aquela linha (o H0 mostra o número). `restart=always` ou
`unless-stopped` num contêiner quer dizer que ele volta sozinho quando o Docker reinicia: o H1 o apaga.

## Bloco H1 — Ray no *host*: remoção (cada nó onde o H0 achou algo, bash como `root`)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  D-07 H1: Ray no host, remoção (acordo com o administrador)"
  case "$(hostname -s)" in sabdiia01|sabdiia02|sabdiia03) ;; *) echo "ABORTA: nó desconhecido"; exit 1;; esac
  [ "$(id -u)" = 0 ] || { echo "ABORTA: rode como root (sudo -i)"; exit 1; }
  RX='(^|[-_/ ])ray([-_:/ ]|$)|rayproject'; TS=$(date +%F-%H%M); PX='gcs_server|raylet|ray::|ray/dashboard|default_worker\.py|bin/ray '

  echo "### 1. ray stop pelo venv do administrador"
  R=/home/utec/llm_lhama_prototype/venv/bin/ray
  if [ -x $R ]; then timeout 120 $R stop --force 2>&1 | tail -5; else echo "sem $R"; fi

  echo "### 2. processos que sobraram"
  P=$(pgrep -f "$PX")
  if [ -n "$P" ]; then
    ps -o pid,user,etime,cmd -p $(echo $P | tr ' ' ',') | cut -c1-200
    kill $P 2>/dev/null; sleep 10
    P=$(pgrep -f "$PX"); [ -n "$P" ] && { echo "ainda vivos, SIGKILL: $P"; kill -9 $P; }
  else
    echo "(nenhum)"
  fi

  echo "### 3. contêineres e imagens com ray (cópia do inspect antes)"
  df -h /home | tail -1
  for E in docker podman; do
    command -v $E >/dev/null || continue
    for N in $($E ps -a --format '{{.Names}}|{{.Image}}' 2>/dev/null | awk -F'|' -v rx="$RX" 'tolower($1" "$2) ~ rx {print $1}'); do
      $E inspect "$N" > ray-conteiner-$E-$N-$TS.json 2>/dev/null
      $E update --restart=no "$N" >/dev/null 2>&1
      $E rm -f "$N" && echo "$E: contêiner $N apagado (cópia em ray-conteiner-$E-$N-$TS.json)"
    done
    for I in $($E images --format '{{.Repository}}:{{.Tag}}|{{.ID}}' 2>/dev/null | awk -F'|' -v rx="$RX" 'tolower($1) ~ rx {print $2}' | sort -u); do
      $E rmi -f "$I" >/dev/null 2>&1 && echo "$E: imagem $I apagada"
    done
  done
  df -h /home | tail -1

  echo "### 4. início automático por systemd"
  for U in $(systemctl list-unit-files --no-pager --no-legend 2>/dev/null | awk 'tolower($1) ~ /ray/ {print $1}'); do
    systemctl cat "$U" > ray-unit-$U-$TS.txt 2>/dev/null
    systemctl disable --now "$U" && echo "systemd: $U desligada (conteúdo em ray-unit-$U-$TS.txt)"
  done
  for U in $(ls /var/spool/cron/crontabs 2>/dev/null); do
    crontab -l -u "$U" 2>/dev/null | grep -nE 'ray|llm_lhama' | sed "s/^/AVISO: cron de $U, linha /; s/\$/  -> remova à mão: crontab -e -u $U/"
  done

  echo "### 5. conferência   $(date +%T)"
  P=$(pgrep -af "$PX" | cut -c1-200); echo "${P:-nenhum processo do Ray}"
  ss -ltnp | grep -E ':(6379|8265|10001)\b' || echo "nenhuma porta do Ray"
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
  echo "== fim $(date -Is)"
} 2>&1 | tee ray-host-remocao-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** a seção 5 mostra `nenhum processo do Ray` e `nenhuma porta do Ray`, e na GPU só o
`vllm-server` (ou nada); nenhum `AVISO: cron` sobrando depois da remoção manual. Rode o H0 de novo para
fechar.

## Trazer os logs (estação, PowerShell)

Um nó por vez; o `scp` pede o usuário.

```powershell
$u = Read-Host "Usuário com que você entra nos nós"
foreach ($ip in "192.168.50.151", "192.168.50.152", "192.168.50.150") {
  scp "${u}@${ip}:/home/utec/vllm-estudo/ray-*.log" "C:\www\vllm-master\logs-analysis\"
}
```

Com `Permission denied` (os blocos H rodam como `root`), rode no nó: `chmod a+r /home/utec/vllm-estudo/ray-*.log`.
As cópias `ray-k8s-copia-*.yaml`, `ray-conteiner-*.json` e `ray-unit-*.txt` ficam nos nós: podem conter
variáveis de ambiente com segredo e não vêm para o repositório.

## Depois

- AC-19 ganha a validade "Ray removido em <data>" com os logs; D-07 passa a confirmada.
- O Bloco P de [pausar-vllms.md](pausar-vllms.md) perde o papel (não há mais `ray-worker`), e os *runbooks*
  de Ray do estudo ficam como registro histórico.
