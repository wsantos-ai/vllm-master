# Runbook — Mover as imagens do Kubernetes (containerd) de `/` para `/home`

> **Dispensado em 2026-10-28, nunca executado.** O administrador redimensionou o LVM: `/` passou a 631 G e
> `/home` a 200 G nos 3 nós ([log de 01](../logs-analysis/estado-disco-rede-sabdiia01-2026-10-28-1419.log)).
> Mover as imagens para `/home` agora seria piorar. Fica como referência de montagem *bind* com o nó drenado.

**Pergunta:** depois da mudança, o containerd e o *kubelet* de `sabdiia01` guardam e contam as imagens em
`/home` (disco de 761 G de capacidade), e não mais no `/` (disco de 70 G)? Capacidade e espaço livre se
leem com `df -h`; `du -sh` mostra só quanto uma pasta ocupa. Fecha a PD-15 e destrava D-02 e PD-31
([ESTUDO-DE-CASO.md](../ESTUDO-DE-CASO.md)).

**Quem executa:** o administrador, ou o usuário com o aval dele. **Não é só leitura**: para o containerd e
o *kubelet* do nó por alguns minutos e altera `/etc/fstab`. `[não executado]`

**Expectativa escrita antes:** a cópia de ~15 G leva alguns minutos; o nó volta `Ready`; o `etcd` volta
com 3 membros `Running`; `findmnt -T /var/lib/containerd` mostra `/home/containerd` sobre
`/dev/mapper/ol-home`; o `imageFs` do *kubelet* passa de ~75 GB para ~817 GB de capacidade; `/` ganha
~15 G livres depois do Bloco 4.

## Como, e por que assim

O containerd continua configurado com `root = '/var/lib/containerd'`, mas essa pasta passa a ser uma
**montagem *bind*** de `/home/containerd`. Nada muda no `config.toml`.

| Opção | Por que não / por que sim |
|---|---|
| Trocar `root` no `config.toml` | Os arquivos de configuração foram regravados em 2026-10-26 18:39 (§2), provavelmente pelo NVIDIA Container Toolkit do GPU Operator `[hipótese]`; uma edição ali pode sumir na próxima regravação |
| **Montagem *bind*** (escolhida) | Fica em `/etc/fstab`, fora do que o GPU Operator gerencia; o containerd e o *kubelet* veem o mesmo caminho de sempre, num disco maior `[hipótese: o kubelet mede o disco do caminho montado]` |

**Riscos e como o procedimento os cobre:**

- **O `etcd` deste nó para durante a troca.** Os 3 nós são *control-plane*; com 1 membro parado, o
  *cluster* segue com 2 de 3 (maioria). O Bloco 1 aborta se o `etcd` não tiver os 3 membros `Running`.
  **Um nó por vez**, sempre.
- **Os *pods* do nó saem** (`drain`). Em `sabdiia01` não há serviço de produção. Os *pods* soltos
  `node-shell-*` (terminais do Freelens) são apagados pelo `--force`.
- **SELinux.** O `rsync -X` copia os rótulos; se o `semanage` existir, a regra de equivalência mantém os
  rótulos de `/var/lib/containerd` em `/home/containerd` mesmo depois de um `restorecon`
  `[não verificado no nó]`.
- **Docker.** Ele usa o mesmo containerd do sistema `[hipótese]`: o bloco o para antes e o religa depois,
  se estava ativo.
- **`sabdiia03` fica de fora:** drená-lo tira a produção (`vllm-deepseek-33b`) do ar. Só com plano
  próprio e aval do usuário.

## Bloco 1 — servidor `sabdiia02`, bash: conferir e drenar `sabdiia01`

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)"
  echo "== nós"; kubectl get nodes -o wide
  echo "== etcd (precisa de 3 Running)"; kubectl get pods -n kube-system -l component=etcd -o wide
  N=$(kubectl get pods -n kube-system -l component=etcd --no-headers | grep -c ' Running ')
  if [ "$N" -ne 3 ]; then echo "ABORTA: etcd com $N membros Running"; exit 1; fi
  echo "== pods em sabdiia01 antes"; kubectl get pods -A -o wide --field-selector spec.nodeName=sabdiia01
  echo "== drain"; kubectl drain sabdiia01 --ignore-daemonsets --delete-emptydir-data --force --timeout=300s
  echo "== nós depois"; kubectl get nodes
} 2>&1 | tee mover-containerd-1-drain-sabdiia01-$(date +%F-%H%M).log
```

Siga para o Bloco 2 só se o log terminar com `node/sabdiia01 drained`.

## Bloco 2 — servidor `sabdiia01`, bash, como `root`: copiar e montar

Pare no primeiro erro (`set -e`). **Não interrompa com Ctrl+C**: se o bloco abortar no meio, use o
Bloco R (reverter).

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
(
  set -e
  echo "== $(hostname -s)  $(date -Is)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  findmnt -T /var/lib/containerd -o SOURCE -n | grep -q ol-root || { echo "ABORTA: /var/lib/containerd já não está no /"; exit 1; }
  [ ! -e /home/containerd ] || { echo "ABORTA: /home/containerd já existe"; exit 1; }
  command -v rsync >/dev/null || { echo "ABORTA: rsync não instalado (dnf install -y rsync)"; exit 1; }
  echo "== SELinux: $(getenforce)"
  echo "== antes"; df -h / /home; du -sh /var/lib/containerd
  D=$(systemctl is-active docker || true); echo "== docker estava: $D"
  echo "== parando kubelet, docker e containerd"
  systemctl stop kubelet
  systemctl stop docker docker.socket 2>/dev/null || true
  systemctl stop containerd
  echo "== copiando"; mkdir -p /home/containerd
  rsync -aHAX --numeric-ids /var/lib/containerd/ /home/containerd/
  echo "== trocando a pasta pela montagem"
  mv /var/lib/containerd /var/lib/containerd.old
  mkdir /var/lib/containerd
  grep -q '^/home/containerd ' /etc/fstab || echo '/home/containerd /var/lib/containerd none bind 0 0' >> /etc/fstab
  systemctl daemon-reload
  mount /var/lib/containerd
  if command -v semanage >/dev/null; then semanage fcontext -a -e /var/lib/containerd /home/containerd || true; restorecon -RF /home/containerd; else echo "semanage ausente: ficam os rótulos copiados pelo rsync -X"; fi
  echo "== religando"
  systemctl start containerd
  [ "$D" = active ] && systemctl start docker || true
  systemctl start kubelet
  echo "== depois"
  systemctl is-active containerd kubelet
  findmnt -T /var/lib/containerd -o TARGET,SOURCE,FSTYPE
  grep containerd /etc/fstab
  df -h / /home
  ctr -n k8s.io containers ls -q | wc -l
) 2>&1 | tee mover-containerd-2-sabdiia01-$(date +%F-%H%M).log
```

## Bloco 3 — servidor `sabdiia02`, bash: conferir e devolver o nó

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)"
  kubectl wait --for=condition=Ready node/sabdiia01 --timeout=300s
  echo "== etcd"; kubectl get pods -n kube-system -l component=etcd -o wide
  echo "== imageFs de sabdiia01 (esperado ~817 GB de capacidade)"; kubectl get --raw /api/v1/nodes/sabdiia01/proxy/stats/summary | grep -A4 '"imageFs"'
  echo "== uncordon"; kubectl uncordon sabdiia01
  echo "== pods em sabdiia01 fora de Running"; kubectl get pods -A -o wide --field-selector spec.nodeName=sabdiia01 | grep -v ' Running '
} 2>&1 | tee mover-containerd-3-uncordon-sabdiia01-$(date +%F-%H%M).log
```

## Bloco 4 — servidor `sabdiia01`, bash: liberar o `/` (um dia depois, se tudo estiver bem)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)"
  findmnt -T /var/lib/containerd -o SOURCE -n | grep -q ol-home || { echo "ABORTA: a montagem não está ativa"; exit 1; }
  df -h /; du -sh /var/lib/containerd.old
  rm -rf /var/lib/containerd.old
  df -h /
} 2>&1 | tee mover-containerd-4-limpeza-sabdiia01-$(date +%F-%H%M).log
```

## Bloco R — servidor `sabdiia01`, bash: reverter

Use se o Bloco 2 abortar no meio, ou se o nó não voltar `Ready` no Bloco 3. Só funciona antes do Bloco 4.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)"
  systemctl stop kubelet; systemctl stop docker docker.socket 2>/dev/null; systemctl stop containerd
  umount /var/lib/containerd 2>/dev/null
  sed -i '\|^/home/containerd /var/lib/containerd none bind|d' /etc/fstab; systemctl daemon-reload
  if [ -d /var/lib/containerd.old ]; then rmdir /var/lib/containerd 2>/dev/null; mv /var/lib/containerd.old /var/lib/containerd; fi
  systemctl start containerd; systemctl start kubelet
  systemctl is-active containerd kubelet
  findmnt -T /var/lib/containerd -o TARGET,SOURCE
} 2>&1 | tee mover-containerd-R-sabdiia01-$(date +%F-%H%M).log
```

Depois do Bloco R, rode `kubectl uncordon sabdiia01` a partir de `sabdiia02`. `/home/containerd` fica
como cópia parada, e pode ser apagada.

## Depois

Repetir em `sabdiia02` com os mesmos blocos, trocando os papéis (drenar 02 a partir de 01), **só depois**
de `sabdiia01` passar um dia estável. Registrar no estudo: PD-15 fechada, AC-09 (nova folga), §2 (disco).
