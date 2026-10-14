# Runbook — Evidenciar a queda do arranque da `v0.19.1` por falta de disco

**Pergunta:** o que acontece, de fato, quando se tenta subir `vllm/vllm-openai:v0.19.1` em `sabdiia02`
com o `/` atual? Transforma a estimativa de AC-09 (27 a 32 G em disco) em evidência medida, para a
PD-15.

**Expectativa escrita antes:** o *pod* fica em `ContainerCreating` baixando a imagem, o espaço livre em
`/` cai de 28 G em direção ao limite, e o teste é **interrompido pelo próprio bloco** ao chegar a 15 G
livres, sem a imagem ter terminado. O *pod* nunca chega a `Running`.

## Risco, em uma frase

Este teste consome de propósito o disco de sistema de um nó que também é *control-plane*. Sem o freio do
bloco, o *download* levaria `/` a 85 % (o *kubelet* passa a apagar imagens e expulsar *pods* de
`sabdiia02`) e possivelmente a 100 % (o etcd desse nó para de gravar). **Combine com o administrador antes
de rodar.**

Como o risco é limitado:

| Medida | Efeito |
|---|---|
| Freio em **15 G livres** (79 % de `/`) | para antes dos 85 % em que o *kubelet* reage; sobra margem de 4,5 G para camadas já em trânsito |
| O bloco roda **em `sabdiia02`** | mede o disco local a cada 5 s, sem depender da rede |
| Apaga o `Deployment` ao parar | sem isso o *kubelet* repete o *download* indefinidamente (`ImagePullBackOff`) |
| Vigia o disco por mais 3 min depois de parar | mostra se o *download* realmente parou |

**O que não foi verificado:** se apagar o `Deployment` cancela na hora um *download* em andamento. Se o
espaço continuar caindo depois da parada, veja "Emergência" abaixo.

---

## Passo 1 — Levar os manifestos para o nó (estação Windows, PowerShell)

```powershell
scp "C:\www\vllm-master\configs\vllm-qwen38-27b.yaml" "C:\www\vllm-master\configs\vllm-qwen38-27b-service.yaml" "root@192.168.50.152:/home/utec/vllm-estudo/"
```

## Passo 2 — Aplicar, vigiar e parar (servidor, bash, **em `sabdiia02`**)

Cole o bloco inteiro. Ele termina sozinho: por freio de disco, por erro de imagem, por `Ready`
(improvável) ou em 40 min.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  livre() { df --output=avail -BG / | tail -1 | tr -dc 0-9; }
  echo "### nó: $(hostname)   início: $(date '+%F %T')"
  echo "### antes";  df -h /;  du -sh /var/lib/containerd /var/lib/containerd/io.containerd.content.v1.content /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs
  echo "### aplicando"
  kubectl apply -f vllm-qwen38-27b.yaml -f vllm-qwen38-27b-service.yaml
  echo "### linha do tempo (a cada 5 s): hora | G livres em / | fase | motivo"
  MOTIVO_PARADA="tempo esgotado (40 min)"
  for i in $(seq 1 480); do
    L=$(livre)
    FASE=$(kubectl get pod -n vllm-estudo -l app=vllm-qwen38-27b -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
    ESPERA=$(kubectl get pod -n vllm-estudo -l app=vllm-qwen38-27b -o jsonpath='{.items[0].status.containerStatuses[0].state.waiting.reason}' 2>/dev/null)
    PRONTO=$(kubectl get pod -n vllm-estudo -l app=vllm-qwen38-27b -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null)
    echo "$(date +%T) | ${L}G | ${FASE:-sem-pod} | ${ESPERA:--}"
    if [ "$L" -le 15 ]; then MOTIVO_PARADA="FREIO DE DISCO: ${L}G livres em /"; break; fi
    if [ "$ESPERA" = "ErrImagePull" ] || [ "$ESPERA" = "ImagePullBackOff" ]; then MOTIVO_PARADA="erro ao baixar a imagem: $ESPERA"; break; fi
    if [ "$PRONTO" = "true" ]; then MOTIVO_PARADA="pod Ready (a imagem coube)"; break; fi
    sleep 5
  done
  echo "### PARADA: $MOTIVO_PARADA   em $(date '+%F %T')"
  echo "### eventos do pod"
  kubectl describe pod -n vllm-estudo -l app=vllm-qwen38-27b | sed -n '/^Events:/,$p'
  echo "### condições do nó"
  kubectl describe node sabdiia02 | grep -E 'DiskPressure|MemoryPressure|^Taints'
  echo "### log do contêiner (só existe se chegou a iniciar)"
  kubectl logs -n vllm-estudo deploy/vllm-qwen38-27b --tail=200
  echo "### removendo o Deployment e o Service"
  kubectl delete -f vllm-qwen38-27b-service.yaml -f vllm-qwen38-27b.yaml --ignore-not-found --wait=false
  echo "### disco nos 3 min seguintes (deve parar de cair)"
  for i in $(seq 1 18); do echo "$(date +%T) | $(livre)G livres"; sleep 10; done
  echo "### depois";  df -h /;  du -sh /var/lib/containerd /var/lib/containerd/io.containerd.content.v1.content /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs
  echo "### imagens de vLLM registradas"
  ctr -n k8s.io images ls | awk 'NR==1 || /vllm/'
} 2>&1 | tee teste-queda-disco-v0.19.1-$(hostname -s)-$(date +%F-%H%M).log
```

O `kubectl delete` do fim também remove o *namespace* `vllm-estudo`, que está no mesmo arquivo. A pasta
`/home/utec/vllm-estudo/` do nó não é afetada.

O que olhar:

- **Linha do tempo:** quantos G a imagem consumiu até a parada, e em quanto tempo. É a medida que falta
  em AC-09.
- **`### PARADA`:** o motivo. "FREIO DE DISCO" confirma que a imagem não cabe na folga segura.
- **Disco nos 3 min seguintes:** se o número se mantém, o *download* parou.
- **Antes × depois:** quanto ficou ocupado por camadas parciais em `content` e `overlayfs`.

## Emergência — o espaço continua caindo depois da parada

Sinal: na seção "disco nos 3 min seguintes" os G livres seguem diminuindo. Significa que o containerd
continuou o *download* mesmo sem o *pod*.

1. **Avise o administrador.**
2. Último recurso, em `sabdiia02`, **altera o nó**: `systemctl restart containerd` interrompe os
   *downloads* em andamento. Os contêineres em execução normalmente sobrevivem ao reinício do containerd
   `[não verificado neste ambiente]`.

## Depois do teste

Traga o log (`scp` do topo do [runbook de inventário](inventario-do-ambiente.md)). Se sobrar espaço
ocupado por camadas parciais, ele entra na mesma limpeza das camadas órfãs da `v0.6.4` (PD-15).
