# Runbook — Acesso ao vLLM pelo Kong (D-05) para os atores de desenvolvimento

**Rota no Kong** (usuário, 2026-11-07): prefixo `/vllm/`. A aplicação usa `https://<IP do Kong>/vllm/v1`
como `baseURL`; o Kong só publica `POST /vllm/v1/chat/completions`.

**Pergunta:** o desenho da D-05 funciona neste *cluster*? O desenho é: vLLM com `--api-key` atrás de um
`Service` `ClusterIP`, `NetworkPolicy` que só deixa o Kong chegar ao vLLM, e o Kong publicando só
`POST /vllm/v1/chat/completions`, em HTTPS, com **uma chave por ator**, limite de requisições por ator e
lista de IPs de origem.

**Decisões que destrava:**
- o tipo de exposição do manifesto de produção (PD-26);
- se a chave da `v0.19.1` precisa de reforço na rede (AC-32);
- se o SSE atravessa o Kong sem acumular;
- o que cada ator precisa mandar: URL, dois cabeçalhos e certificado.

**Atores** (usuário, 2026-11-06): dois desenvolvedores, cada um no seu PC, e a equipe que desenvolve a
aplicação em Next.js. O usuário entra com dois consumidores para os testes do Bloco E1: `estacao`, a máquina
virtual `DESKTOP-WELLINGT` (**172.16.30.6**), e `wsantos`, o notebook com o repositório, que não tem IP fixo e
recebe da VPN um endereço em `172.16.254.0/24`. Os IPs dos atores ainda serão pedidos: a lista
[configs/d05-consumidores.txt](../configs/d05-consumidores.txt) os marca como `pendente`. O Bloco C cria a
chave de cada um, mas o Kong só deixa passar quem tem IP na lista. Cada IP novo entra pela lista e por uma
nova rodada do Bloco C, sem reiniciar o vLLM e sem trocar as chaves já entregues.

**O IP é o da máquina que chama o modelo**, não o dos usuários finais. Na aplicação Next.js, a chamada sai
do servidor (rota de API ou *server action*), nunca do navegador: no navegador, as chaves iriam para o código
baixado pelo usuário.

Manifesto: [configs/vllm-nemo-gateway.yaml](../configs/vllm-nemo-gateway.yaml). Modelo: Mistral-Nemo 12B FP16
com as *flags* de AC-29, **3 réplicas, uma por nó, no *namespace* `vllms`**.

**As 3 GPUs são da aplicação, e o estudo adota o `vllm-server` do administrador** (acordo do usuário com
o administrador, 2026-11-07; D-06). O *Deployment* mantém o nome e o seletor `app=vllm-server`, que não muda
depois de criado. O manifesto versionado passa a ser a única fonte: o administrador não reaplica mais o
arquivo dele, e o `kubectl apply` do estudo substitui a configuração dele inteira. Isso troca o modelo
(DeepSeek-Coder-V2-Lite → Nemo), o contexto (4096 → 8192) e as ferramentas (*parser* `mistral`), põe a chave
(`--api-key`), tira o `--trust-remote-code` e passa os pesos do PVC NFS para o cache local de cada nó.
Na 1ª vez, o G1:
- guarda cópias do *Deployment* e do `Service` `vllm-llama-service` dele (`vllm-*-adocao-<data>.yaml`, em 01);
- apaga esse `LoadBalancer` (`192.168.50.160:8000`, sem chave; AC-06, AC-32);
- troca as réplicas uma a uma.

Tudo o que o estudo controla em `vllms` leva o rótulo `decisao=d-05`. O Bloco P de
[pausar-vllms.md](pausar-vllms.md) ignora esses recursos, e o Bloco L só apaga o que tem o rótulo. O
`Service` `vllm-llama31-8b` (sem *Deployment* desde 11-03) e o `ray-worker` continuam do administrador.

| Bloco | Onde | O que faz | Altera algo? |
|---|---|---|---|
| K0 | `sabdiia01`, bash | Inventário do Kong: *pods*, IP do *proxy*, `externalTrafficPolicy`, rotas e *plugins* já existentes | Não |
| K2 | `sabdiia01`, bash | `externalTrafficPolicy: Local` no *proxy* do Kong, pelo Helm (PD-35, autorizado pelo administrador) | Sim: o Kong passa a ver o IP do cliente |
| E0 | estação, PowerShell | A estação alcança o IP do Kong? Copia o manifesto e a lista de consumidores para 01 | Só copia arquivos |
| D1 | **cada ator**, PowerShell | A máquina do ator alcança o Kong, e com que IP? Não precisa de chave | Não |
| K1 | `sabdiia01`, bash | Bloco K1 de [remover-ray.md](remover-ray.md): apaga o `ray-worker` (D-07). Antes do G1; o H0/H1 dos *hosts* também | Sim: o Ray sai |
| W | `sabdiia01`, bash | Baixa os pesos do Nemo no cache de 02 e 03, na mesma revisão de 01. Uma vez só | Só arquivos em `/var/lib/vllm-estudo/hf-cache` de 02 e 03 |
| G1 | `sabdiia01`, bash | Na 1ª vez, adota o `vllm-server` (cópias, manifesto, fim do `LoadBalancer`); depois, só atualiza. Chave do vLLM, troca das 3 réplicas uma a uma, testes de cada réplica, de outro *pod* e de 01 pelo Kong | Substitui a configuração do `vllm-server`, **apaga o `vllm-llama-service`** e cria uma rota no Kong compartilhado |
| C | `sabdiia01`, bash | Consumidores a partir da lista: chave por ator, lista de IPs, arquivo de chave de cada um. **Repetível** | Cria, mantém ou revoga consumidores |
| E1 | estação, PowerShell | Testes de fora: chaves, SSE, caminhos fechados, HTTP sem TLS, certificado, limite de requisições | Não |
| D2 | **cada ator**, PowerShell | Com o arquivo de chave recebido: uma pergunta e o SSE | Não |
| L | `sabdiia01`, bash | Desmonta: guarda os logs dos *pods* e apaga tudo com `decisao=d-05`, inclusive as chaves | Apaga o que W, G1 e C criaram |
| R | `sabdiia01`, bash | **Só por decisão explícita do usuário**: devolver ao administrador é reaplicar as cópias `vllm-*-adocao-*.yaml` depois do L | Sim: a configuração dele de volta |

**Antes do G1, avise o administrador.** O Kong é compartilhado. O G1 e o C acrescentam uma rota
(`/vllm/...`), três `KongPlugin` e um `KongConsumer` por ator no *namespace* `vllms`. Nada no
*namespace* `kong` é alterado.

**Ordem da primeira vez:** K0, E0, D1 e W (a qualquer hora: o W baixa ~24,5 GB em 02 e 03 sem GPU, ~30-60 min
`[estimativa]`); K1, H0 e H1 de [remover-ray.md](remover-ray.md); G1; C; E1; D2. Depois, só o C a cada IP novo e o G1 a cada
mudança no manifesto. **Avise a quem usa `192.168.50.160:8000`**: o endereço deixa de responder no G1.

---

## Por que este desenho (conferido em 2026-11-06)

| Ponto | Fonte | Consequência |
|---|---|---|
| Na `v0.19.1`, o `AuthenticationMiddleware` só exige `Authorization: Bearer` em caminhos que começam com `/v1`; `OPTIONS` passa sempre | `vllm/entrypoints/openai/server_utils.py` [F-045] | `/health`, `/metrics` e `/invocations` respondem sem chave (AC-32) |
| A *tag* registra sempre o roteador da SageMaker: `POST /invocations` aceita `ChatCompletionRequest` e gera texto | `vllm/entrypoints/sagemaker/api_router.py`, `api_server.py` [F-045] | A chave do vLLM sozinha não fecha a geração: o Kong só encaminha um caminho, e a `NetworkPolicy` impede o acesso direto |
| `--api-key` tem precedência sobre `VLLM_API_KEY`; a variável vem de um `Secret` | `api_server.py`, `envs.py` [F-045] | A chave não aparece no manifesto nem no `ps` |
| `--disable-fastapi-docs` desliga `/docs`, `/redoc` e o *schema* OpenAPI | `cli_args.py` [F-045] | Menos superfície dentro do *cluster* |
| O Kong encaminha direto ao IP do *pod*, não ao `ClusterIP` | anotação `ingress.kubernetes.io/service-upstream` [F-046] | A `NetworkPolicy` tem de liberar o *namespace* do Kong, não um IP |
| `konghq.com/path` no `Service` prefixa o caminho enviado ao vLLM; `strip-path` retira a rota | [F-046] | A rota `/vllm/v1/chat/completions` vira `/v1/chat/completions`, e nenhum outro caminho do vLLM fica alcançável pelo Kong |
| `key-auth`: `key_names` (padrão `apikey`), `hide_credentials`, `key_in_query`; `rate-limiting`: `minute`, `limit_by` (padrão `consumer`), `policy`; `ip-restriction`: `allow`, "List of IPs or CIDR ranges" | esquema dos *plugins* na doc atual do Kong [F-046] | Um limite por ator; IP de origem por ator, ou faixa de DHCP. Valores postos explicitamente: o *cluster* roda Kong 3.9, e a doc é da versão atual |
| Tráfego do próprio nó para o *pod* é sempre permitido pela `NetworkPolicy` | doc do Kubernetes [F-047] | As *probes* do *kubelet* continuam passando |

**Duas chaves no cliente.** O Kong lê a dele no cabeçalho `apikey` e a retira antes de encaminhar; essa é por
ator, e revogar um ator é apagar a linha dele da lista. O vLLM lê `Authorization: Bearer`; essa é uma só
para todos, porque o único caminho até ele é o Kong.

**Por que não um serviço intermediário compartilhado** (proposta discutida em 2026-11-06): ele repetiria o
que o Kong faz e juntaria os três atores numa chave e numa cota só. Um vazamento ou a saída de alguém do
projeto obrigaria todos a trocar de chave, e um *loop* de testes de um ator esgotaria a cota dos outros.

---

## Expectativa (escrita antes)

- **K0:** *pods* do Kong `Running`. Em 2026-10-27, o `kong-controller` estava em `ContainerStatusUnknown`
  em 01 ([log](../logs-analysis/ray-docker-inventario-sabdiia01-2026-10-27-1214.log)): se ainda estiver, pare
  aqui e fale com o administrador. Um `Service` `LoadBalancer` no *namespace* `kong`, com IP do
  `pool-publico` e portas 80 e 443. `externalTrafficPolicy: Cluster` (o padrão do Kubernetes)
  `[hipótese]`: nesse caso o Kong vê o IP de um nó, não o do ator, e o Bloco C não aplica a lista de IPs.
- **E0 e D1:** as máquinas alcançam a porta 443 do Kong `[hipótese]`: o `scp` da estação para
  192.168.50.151 já funciona. Para os atores, não se sabe.
- **W:** 02 e 03 baixam ~24,5 GB cada, na revisão que 01 já tem; `df` com centenas de GB livres (AC-09).
  Se os *pods* de 02 ou 03 não resolverem `huggingface.co` mesmo com `hostNetwork`, o problema é o DNS do
  nó (a PD-28 só foi vista em 01, sem `hostNetwork`).
- **G1, adoção:** cópias gravadas; o `apply` troca o modelo, e os volumes passam a `pesos-local` e `shm`, sem o
  PVC `hf-cache-pvc`; o `vllm-llama-service` sai. As réplicas do DeepSeek-Coder saem uma a uma, cada uma dando
  lugar a uma do Nemo em ~5-10 min a partir do cache local `[estimativa]`: ~15-30 min para as 3. Cada uma
  responde "Brasília".
- **G1, de dentro do *pod*:**
  - `/v1/models` sem chave: 401; com chave: 200;
  - *chat* em `/v1` com chave: 200, "Brasília";
  - **`/invocations` sem chave: 200, com resposta** (AC-32);
  - `/metrics` sem chave: 200;
  - `/docs`: 404.
- **G1, *pod* sonda:** o vLLM pelo `Service` e pelo IP do *pod* não responde (*timeout*); o *proxy* do Kong
  responde algum código HTTP (controle).
- **G1, de 01 pelo Kong:** sem chave, 401; `/vllm/metrics`, 404.
- **C:** 4 consumidores, 4 arquivos de chave; lista de IPs com só `172.16.30.6`. De 01, com a chave de cada
  ator: 403 se a lista de IPs valer (01 não está nela), ou 200 se não valer.
- **E1:**
  - sem chave, 401 do Kong; só a chave do Kong, 401 `{"error":"Unauthorized"}` do vLLM; só a do vLLM, 401
    do Kong; as duas, 200 e "Brasília"; a chave de um ator `pendente`, 403 (IP fora da lista);
  - SSE: primeiro *byte* em menos de 2 s e total acima de 5 s para 200 *tokens* (o Nemo faz ~28 *tok*/s
    com 1 usuário, AC-29). Primeiro *byte* ≈ total significa que o Kong acumula a resposta;
  - `GET` na rota, `/vllm/v1/models`, `/vllm/metrics` e `/invocations`: 404 do Kong;
  - HTTP sem TLS: 426 `[não verificado]`, qualquer código diferente de 200 fecha o ponto;
  - certificado autoassinado do Kong `[não verificado]`;
  - com 125 requisições em seguida, algumas recebem 429 se houver 1 *pod* de *proxy*. Com vários, o limite
    é contado em cada um (`policy: local`) e pode não aparecer.

---

## Bloco K0 — Inventário do Kong (servidor `sabdiia01`, bash; só leitura)

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  D-05 K0: o Kong está pronto?"
  case "$(hostname -s)" in sabdiia01|sabdiia02) ;; *) echo "ABORTA: kubectl só em 01 ou 02"; exit 1;; esac

  echo "### 1. pods do Kong"
  kubectl get pods -n kong -o wide
  kubectl get pods -n kong -o jsonpath='{range .items[*]}{.metadata.name}{"  hostNetwork="}{.spec.hostNetwork}{"  imagens="}{range .spec.containers[*]}{.image}{" "}{end}{"\n"}{end}'

  echo "### 2. Services do Kong: o proxy com IP do MetalLB"
  kubectl get svc -n kong -o wide
  kubectl get svc -n kong -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.name}{"  IP="}{.status.loadBalancer.ingress[0].ip}{"  externalTrafficPolicy="}{.spec.externalTrafficPolicy}{"  portas="}{.spec.ports[*].port}{"  pool="}{.metadata.annotations.metallb\.io/ip-allocated-from-pool}{"\n"}{end}'
  for s in $(kubectl get svc -n kong -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.name}{" "}{end}'); do
    echo "endpoints de $s: $(kubectl get endpoints "$s" -n kong -o jsonpath='{.subsets[*].addresses[*].ip}')"
  done

  echo "### 3. IngressClass e CRDs do Kong"
  kubectl get ingressclass
  kubectl get crd | grep konghq.com

  echo "### 4. o que já passa pelo Kong: rotas, plugins globais e de namespace, consumidores"
  kubectl get ingress -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"  classe="}{.spec.ingressClassName}{"  caminhos="}{.spec.rules[*].http.paths[*].path}{"\n"}{end}'
  kubectl get kongclusterplugins 2>&1
  kubectl get kongplugins -A 2>&1
  kubectl get kongconsumers -A 2>&1

  echo "### 5. NetworkPolicy existentes e rótulos do namespace kong"
  kubectl get networkpolicy -A
  kubectl get ns kong --show-labels

  echo "### 6. o proxy responde? (de 01, sem chave; 404 'no Route matched' é resposta)"
  for IP in $(kubectl get svc -n kong -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.status.loadBalancer.ingress[0].ip}{" "}{end}'); do
    curl -sk -m 5 -o /dev/null -w "https://$IP/  HTTP %{http_code}\n" "https://$IP/vllm/"
    curl -s  -m 5 -o /dev/null -w "http://$IP/   HTTP %{http_code}\n" "http://$IP/vllm/"
  done

  echo "### 7. últimas linhas de log dos pods do Kong"
  for p in $(kubectl get pods -n kong -o name); do echo "-- $p"; kubectl logs -n kong "$p" --all-containers --tail=5 2>&1 | cut -c1-250; done
  echo "== fim $(date -Is)"
} 2>&1 | tee d05-k0-kong-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:**
- a seção 2 mostra **um** `Service` `LoadBalancer` com IP e porta 443, e os *endpoints* dele não estão vazios;
- a seção 3 mostra uma `IngressClass` `kong` e as CRDs `kongplugins` e `kongconsumers`;
- a seção 6 responde algum código HTTP.

Anote o IP da seção 2: o E0 e o D1 pedem esse valor.

## Bloco K2 — O Kong passa a ver o IP do cliente (servidor `sabdiia01`, bash; PD-35)

**Autorizado pelo administrador (2026-11-07).** Muda o `Service` `kong/kong-gateway-proxy` de
`externalTrafficPolicy: Cluster` para `Local` **pelo Helm**, para não ser desfeito no próximo `helm upgrade`
(AC-33). O bloco:
- confere o *release* e o *chart*;
- guarda os *values* e o `Service` atuais;
- roda `helm upgrade` com a **mesma versão do chart** e `--reuse-values`, mudando só esse campo;
- confere o resultado.

Sem `helm` ou sem o *release*, cai para `kubectl patch`, com aviso de que um `helm upgrade` futuro desfaz a mudança.

Campo conferido no *chart* em 2026-11-07 [F-048]: `proxy.externalTrafficPolicy` no *chart* `kong`
(`_helpers.tpl`: `{{- if .externalTrafficPolicy }} externalTrafficPolicy: ...`, presente da 2.33.0 à 3.2.0); no
*chart* `ingress`, que embute o `kong` como `gateway`, o caminho é `gateway.proxy.externalTrafficPolicy`.

**Expectativa (escrita antes):** *release* `kong`, *chart* `ingress-0.x`, em `kong`; o `upgrade` mexe só no
`Service` (nenhum *pod* do Kong reinicia, `AGE` igual); `externalTrafficPolicy=Local` com um `healthCheckNodePort`
novo. Como o único *pod* do *gateway* está em `sabdiia03`, o MetalLB passa a anunciar `192.168.50.161` a partir de 03
`[hipótese: modo L2]`. Do notebook, o Kong deve registrar `172.16.254.x`, ou `192.168.30.251` se houver NAT no
roteador da VPN.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  D-05 K2: externalTrafficPolicy Local no proxy do Kong (PD-35)"
  case "$(hostname -s)" in sabdiia01|sabdiia02) ;; *) echo "ABORTA: kubectl só em 01 ou 02"; exit 1;; esac
  NS=kong; SVC=kong-gateway-proxy; TS=$(date +%F-%H%M)

  echo "### 1. como está"
  kubectl get svc $SVC -n $NS -o jsonpath='externalTrafficPolicy={.spec.externalTrafficPolicy} healthCheckNodePort={.spec.healthCheckNodePort} IP={.status.loadBalancer.ingress[0].ip}{"\n"}' || { echo "ABORTA: $SVC não existe em $NS"; exit 1; }
  kubectl get svc $SVC -n $NS -o yaml > kong-proxy-svc-antes-$TS.yaml
  kubectl get pods -n $NS -o wide
  kubectl get pods -A -o wide 2>/dev/null | grep -i metallb | awk '{print "metallb:", $1, $2, $4, $8}'

  echo "### 2. release do Helm"
  H=0
  if command -v helm >/dev/null; then
    helm version --short
    helm list -n $NS
    NR=$(helm list -n $NS -q | grep -c .)
    REL=$(helm list -n $NS -q | head -1)
    CH=$(helm list -n $NS -o json | sed -n 's/.*"chart":"\([^"]*\)".*/\1/p' | head -1)
    echo "releases em $NS: $NR; release=$REL chart=$CH"
    [ "$NR" = 1 ] || CH="(esperava 1 release, achei $NR)"
    case "$CH" in
      ingress-*) KEY=gateway.proxy.externalTrafficPolicy; NOME=ingress; VER=${CH#ingress-}; H=1 ;;
      kong-*)    KEY=proxy.externalTrafficPolicy;         NOME=kong;    VER=${CH#kong-};    H=1 ;;
      *) echo "AVISO: chart '$CH' não reconhecido: sem helm upgrade" ;;
    esac
    [ $H = 1 ] && { helm get values "$REL" -n $NS -o yaml > kong-helm-values-antes-$TS.yaml; echo "values atuais em kong-helm-values-antes-$TS.yaml ($(wc -l < kong-helm-values-antes-$TS.yaml) linhas)"; }
  else
    echo "AVISO: helm não instalado neste nó"
  fi

  echo "### 3. mudança   $(date +%T)"
  if [ $H = 1 ]; then
    echo "helm upgrade $REL $NOME --repo https://charts.konghq.com --version $VER -n $NS --reuse-values --set $KEY=Local"
    helm upgrade "$REL" "$NOME" --repo https://charts.konghq.com --version "$VER" -n $NS --reuse-values --set "$KEY=Local" --wait --timeout 5m || { echo "FALHOU o helm upgrade: nada mais foi feito; traga o log"; exit 1; }
    helm history "$REL" -n $NS | tail -3
  else
    echo "AVISO: sem Helm, kubectl patch; um helm upgrade futuro volta a Cluster (avise o administrador)"
    kubectl patch svc $SVC -n $NS -p '{"spec":{"externalTrafficPolicy":"Local"}}' || exit 1
  fi

  echo "### 4. conferência   $(date +%T)"
  sleep 15
  kubectl get svc $SVC -n $NS -o jsonpath='externalTrafficPolicy={.spec.externalTrafficPolicy} healthCheckNodePort={.spec.healthCheckNodePort} IP={.status.loadBalancer.ingress[0].ip}{"\n"}'
  kubectl get pods -n $NS -o wide
  kubectl get events -n $NS --sort-by=.lastTimestamp | tail -8 | cut -c1-200
  IP=$(kubectl get svc $SVC -n $NS -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
  for i in 1 2 3; do curl -sk -m 5 -o /dev/null -w "de $(hostname -s): https://$IP/vllm/  HTTP %{http_code}\n" "https://$IP/vllm/"; done
  echo "### 5. que IP o Kong registrou (as últimas requisições)"
  kubectl logs -n $NS deploy/kong-gateway --tail=200 2>/dev/null | grep -v 'GET /status' | tail -5 | cut -c1-200
  echo "== fim $(date -Is)"
} 2>&1 | tee d05-k2-kong-etp-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** a seção 4 mostra `externalTrafficPolicy=Local` e o IP `192.168.50.161`; os *pods* do Kong com a
mesma idade de antes; algum código HTTP nas três tentativas. Depois:
1. no notebook, rode o E0 de novo (seção 4: `HTTP 404`);
2. em 01, veja que IP o Kong registrou para o notebook:
   `kubectl logs -n kong deploy/kong-gateway --tail=50 | grep -v /status | tail -3`
3. se for `172.16.254.x`, a lista de consumidores já está certa; se for outro (NAT), ponha esse IP na linha do
   `wsantos` e reenvie a lista (E0-cópia);
4. o Bloco C passa a aplicar a lista de IPs (seção 3 sem `AVISO`).

**Para voltar:** `helm rollback kong -n kong` (a revisão anterior aparece no `helm history` da seção 3), ou, se foi
por `patch`, `kubectl patch svc kong-gateway-proxy -n kong -p '{"spec":{"externalTrafficPolicy":"Cluster"}}'`.

## Bloco E0 — A rede até o Kong (notebook ou máquina virtual, PowerShell)

Roda no **notebook** (consumidor `wsantos`, terminal do VS Code) ou na **máquina virtual** 172.16.30.6
(consumidor `estacao`): é da máquina onde roda que o Kong tem de aceitar conexão. Pede o IP da seção 2 do K0 e
o usuário do `scp`. O log vai para `C:\www\vllm-master\logs-analysis\` se o repositório estiver na máquina; se
não, para a Área de Trabalho. A cópia dos arquivos para 01 é o E0-cópia, abaixo: um `scp` dentro do script
escondia o pedido de senha.

Script: [runbooks/ps/d05-e0.ps1](ps/d05-e0.ps1). No terminal PowerShell do notebook (prompt `PS C:\...>`):

```powershell
pwsh -ExecutionPolicy Bypass -File C:\www\vllm-master\runbooks\ps\d05-e0.ps1
```

**Pronto se:** a seção 2 mostra `alcançou=True` na porta 443, com a origem da máquina (`172.16.254.x` no
notebook, `172.16.30.6` na máquina virtual). Se a 443 não alcançar mas o ssh sim, há um *firewall* ou falta rota da rede 172.16.30.0 para o IP
do MetalLB: leve o `tracert` à equipe de infraestrutura antes de seguir.

### E0-cópia — Só enviar o manifesto e a lista de consumidores (notebook, PowerShell)

Para mandar uma lista atualizada ou um manifesto novo sem repetir o teste de rede:

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
$c = "C:\www\vllm-master\configs"
scp "$c\vllm-nemo-gateway.yaml" "$c\d05-consumidores.txt" `
  "${u}@192.168.50.151:/home/utec/vllm-estudo/"
```

### E0-permissão — Só se o `scp` der `Permission denied` (servidor `sabdiia01`, bash, depois de `sudo -i`)

**Este bloco é bash: cole no SSH de 01 (Moba), não no PowerShell.** O diretório foi criado pelos blocos rodados
como `root`. O bloco dá escrita só ao seu usuário (ACL) e passa a ele os dois arquivos, se já existirem como
`root`. Executado em 2026-11-07; não precisa repetir.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s) $(date -Is) escrita em vllm-estudo"
  [ "$(id -u)" = 0 ] || { echo "ABORTA: rode depois de sudo -i"; exit 1; }
  U=${SUDO_USER:-}
  [ -n "$U" ] || { echo "ABORTA: use sudo -i a partir do seu usuário"; exit 1; }
  ls -ld . ; id "$U"
  if command -v setfacl >/dev/null; then
    setfacl -m "u:$U:rwx" . && echo "ACL: $U com rwx"
  else
    chgrp "$(id -gn "$U")" . && chmod g+rwx . && echo "grupo $(id -gn "$U") com rwx"
  fi
  for F in vllm-nemo-gateway.yaml d05-consumidores.txt; do
    [ -e "$F" ] && chown "$U" "$F" && echo "$F agora é de $U"
  done
  ls -ld . ; getfacl -p . 2>/dev/null | grep "user:$U"
} 2>&1 | tee permissao-vllm-estudo-$(hostname -s)-$(date +%F-%H%M).log
```

## Bloco D1 — Rede do ator (máquina de cada ator, PowerShell; sem chave)

Envie este bloco a cada ator com o IP do Kong. Ele roda o bloco e devolve o log que fica na Área de
Trabalho. O log mostra os IPv4 da máquina e o IP de origem com que ela sai para o Kong: esse é o candidato a
entrar na lista. **Se houver NAT no caminho, o Kong vê outro IP**; o 403 do D2 mostra isso.

Script: [runbooks/ps/d05-d1.ps1](ps/d05-d1.ps1). Envie o arquivo ao ator; ele o salva na Área de Trabalho e roda
no PowerShell, a partir da Área de Trabalho:

```powershell
powershell -ExecutionPolicy Bypass -File .\d05-d1.ps1
```

**Leitura:** `alcançou=True` e `PrefixOrigin` `Manual` dão um IP fixo para a lista. Com `Dhcp`, peça à
infraestrutura uma reserva ou use a faixa da rede (`PrefixLength`) em CIDR. Uma faixa libera todas as
máquinas dela, mas ainda exige a chave. `alcançou=False`: a rede do ator não chega ao Kong, um caso para a
infraestrutura.

## Antes do G1 — Ray fora (D-07)

Rode os Blocos K1, H0 e H1 de [remover-ray.md](remover-ray.md). O `ray-worker` reservava GPU nos 3 nós, e o
Ray do *host* ocupa GPU sem o Kubernetes saber (AC-19): com ele no ar, a réplica nova daquele nó cai por falta
de memória. O Bloco 0 de [teste-protocolo-modelos.md](teste-protocolo-modelos.md) não serve aqui, porque as
GPUs estão ocupadas pelas réplicas que o G1 vai trocar.

## Bloco W — Pesos do Nemo em 02 e 03 (servidor `sabdiia01`, bash; uma vez só)

Lê a revisão do Nemo no cache de 01 e sobe um *pod* sem GPU em 02 e outro em 03, com `hostNetwork` para
resolver nomes. Eles baixam a mesma revisão para `/var/lib/vllm-estudo/hf-cache` de cada nó, só
`consolidated.safetensors`, `*.json` e `*.txt`, como no Bloco N1 de [teste-mistral-nemo.md](teste-mistral-nemo.md).
As 3 réplicas ficam com pesos idênticos.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  D-05 W: pesos do Nemo em 02 e 03, na revisão de 01"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01 (lê a revisão no cache local)"; exit 1; }
  NS=vllms; C=/var/lib/vllm-estudo/hf-cache/hub/models--mistralai--Mistral-Nemo-Instruct-2407
  REV=$(ls "$C/snapshots" 2>/dev/null); echo "revisão em 01: $REV"
  [ "$(echo "$REV" | grep -c .)" = 1 ] || { echo "ABORTA: esperava 1 revisão em $C/snapshots"; exit 1; }
  ls -laL "$C/snapshots/$REV"

  echo "### 1. imagem v0.19.1 nos 3 nós (lista de imagens do nó)"
  for NO in sabdiia01 sabdiia02 sabdiia03; do
    kubectl get node $NO -o jsonpath='{range .status.images[*]}{.names}{"\n"}{end}' | grep -q 'vllm/vllm-openai:v0.19.1' && echo "$NO: v0.19.1 presente" || echo "AVISO: $NO sem a v0.19.1: no próprio nó, ctr -n k8s.io images pull docker.io/vllm/vllm-openai:v0.19.1 (AC-24)"
  done

  echo "### 2. pods de download   $(date +%T)"
  for NO in sabdiia02 sabdiia03; do
    sed -e "s/__NO__/$NO/g" -e "s/__REV__/$REV/g" <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata: {name: d05-pesos-__NO__, namespace: vllms, labels: {app: d05-pesos, decisao: d-05}}
spec:
  nodeSelector: {kubernetes.io/hostname: __NO__}
  hostNetwork: true
  restartPolicy: Never
  automountServiceAccountToken: false
  containers:
  - name: pesos
    image: vllm/vllm-openai:v0.19.1
    command: ["/bin/bash", "-c"]
    args:
    - |
      set -e
      df -h /hf-cache
      python3 -c "from huggingface_hub import snapshot_download as s; print('pesos em', s('mistralai/Mistral-Nemo-Instruct-2407', revision='__REV__', allow_patterns=['consolidated.safetensors','*.json','*.txt']))"
      # baixar com revision=<sha> não cria refs/main, e o vllm-server procura a revisão main (local_files_only)
      mkdir -p /hf-cache/hub/models--mistralai--Mistral-Nemo-Instruct-2407/refs
      printf '%s' '__REV__' > /hf-cache/hub/models--mistralai--Mistral-Nemo-Instruct-2407/refs/main
      ls -laL /hf-cache/hub/models--mistralai--Mistral-Nemo-Instruct-2407/snapshots/__REV__
      du -shL /hf-cache/hub/models--mistralai--Mistral-Nemo-Instruct-2407
    env:
    - {name: HF_HOME, value: /hf-cache}
    - {name: HF_HUB_OFFLINE, value: "0"}
    resources:
      requests: {cpu: "2", memory: 4Gi}
      limits: {cpu: "4", memory: 16Gi}
    volumeMounts:
    - {name: hf-cache, mountPath: /hf-cache}
  volumes:
  - name: hf-cache
    hostPath: {path: /var/lib/vllm-estudo/hf-cache, type: DirectoryOrCreate}
EOF
  done

  echo "### 3. aguardando (até 60 min)"
  T0=$(date +%s)
  while [ $(( $(date +%s) - T0 )) -lt 3600 ]; do
    F=$(kubectl get pods -n $NS -l app=d05-pesos -o jsonpath='{range .items[*]}{.metadata.name}={.status.phase}/{.status.containerStatuses[0].state.waiting.reason} {end}')
    echo "$(date +%T) $F"
    echo "$F" | grep -qE 'Pending|Running' || break
    sleep 60
  done

  echo "### 4. resultado"
  for NO in sabdiia02 sabdiia03; do echo "-- $NO"; kubectl logs -n $NS d05-pesos-$NO 2>&1 | grep -vE '%\|' | cut -c1-200 | tail -15; done
  kubectl get pods -n $NS -l app=d05-pesos -o wide
  kubectl delete pods -n $NS -l app=d05-pesos --wait=true
  echo "== fim $(date -Is)"
} 2>&1 | tee d05-w-pesos-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** a seção 1 mostra a `v0.19.1` nos 3 nós; a seção 3 termina com os dois `Succeeded`; a seção 4
mostra `consolidated.safetensors` com 24.495.604.224 *bytes* em 02 e 03 (o tamanho de [F-044]).

### W-refs — Reparo de 2026-11-07: `refs/main` em 02 e 03 (cada nó, bash como `root`; sem `kubectl`)

O W de 2026-11-07 baixou os pesos com `revision=<sha>`, e isso não cria o arquivo `refs/main` no cache. O
`vllm-server` chama `snapshot_download(..., local_files_only=True)` sem revisão, ou seja, procura `main`, e cai com
`LocalEntryNotFoundError` ([G1](../logs-analysis/d05-g1-sabdiia01-2026-11-07-2130.log)). O W já foi corrigido;
este bloco repara os dois nós que ele baixou. Rode em `sabdiia02` e em `sabdiia03`:

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s) $(date -Is) refs/main do Nemo"
  [ "$(id -u)" = 0 ] || { echo "ABORTA: rode como root"; exit 1; }
  case "$(hostname -s)" in sabdiia02|sabdiia03) ;; *) echo "ABORTA: só 02 e 03"; exit 1;; esac
  R=04d8a90549d23fc6bd7f642064003592df51e9b3
  M=/var/lib/vllm-estudo/hf-cache/hub/models--mistralai--Mistral-Nemo-Instruct-2407
  ls -d "$M/snapshots/$R" || { echo "ABORTA: revisão ausente no cache"; exit 1; }
  mkdir -p "$M/refs" && printf '%s' "$R" > "$M/refs/main"
  ls -l "$M/refs"; echo "refs/main = $(cat "$M/refs/main")"
} 2>&1 | tee nemo-refs-main-$(hostname -s)-$(date +%F-%H%M).log
```

Depois, rode o G1 de novo: sem mudança no manifesto, o `apply` não dispara outra troca. O *pod* de 02 sai do
*loop* sozinho, em até ~5 min (espera entre reinícios), e a troca segue para 03.

## Bloco G1 — Sobe as 3 réplicas e testa por dentro (servidor `sabdiia01`, bash; aborta em outro nó)

**Não interrompa com Ctrl+C:** os *pods* seguem subindo. Para desfazer, use o Bloco L.

A chave do vLLM é gerada aqui e só entra no `Secret`. Nenhuma chave vai para o log. Ao fim do G1 nenhum ator
passa pelo Kong ainda: não há consumidor até o Bloco C.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  D-05 G1: vLLM atrás do Kong, com chave, NetworkPolicy e rota única"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  NS=vllms; M=vllm-nemo-gateway.yaml

  echo "### 1. pré-condições"
  [ -f $M ] || { echo "ABORTA: $M ausente; rode a seção 5 do E0"; exit 1; }
  sha256sum $M
  kubectl get ns $NS >/dev/null || { echo "ABORTA: namespace $NS não existe"; exit 1; }
  ADOCAO=0
  if ! kubectl get deploy vllm-server -n $NS >/dev/null 2>&1; then
    echo "vllm-server não existe: criação do zero"
  elif [ "$(kubectl get deploy vllm-server -n $NS -o jsonpath='{.metadata.labels.decisao}')" = d-05 ]; then
    echo "vllm-server já é do estudo: o apply troca uma réplica por vez (RollingUpdate), 2 seguem atendendo"
  else
    ADOCAO=1
    echo "vllm-server do administrador: ADOÇÃO (acordo de 2026-11-07, D-06). Como está:"
    kubectl get deploy vllm-server -n $NS -o jsonpath='réplicas {.spec.replicas}; seletor {.spec.selector.matchLabels}{"\n"}{.spec.template.spec.containers[0].args}{"\n"}' | sed -E 's/(--api-key[= "]+)[^ ",]+/\1***/g'
    [ "$(kubectl get deploy vllm-server -n $NS -o jsonpath='{.spec.selector.matchLabels}')" = '{"app":"vllm-server"}' ] || { echo "ABORTA: seletor do vllm-server diferente de app=vllm-server (o seletor não muda depois de criado)"; exit 1; }
  fi
  for O in svc/vllm-server ingress/vllm-server networkpolicy/vllm-server-so-kong secret/vllm-nemo-api-key kongplugin/d05-key-auth kongplugin/d05-rate-limit; do
    ROT=$(kubectl get $O -n $NS -o jsonpath='{.metadata.labels.decisao}' 2>/dev/null) && [ "$ROT" != d-05 ] && { echo "ABORTA: $O já existe em $NS e não é do estudo (sem decisao=d-05)"; exit 1; }
  done
  RW=$(kubectl get pods -n $NS -l app=ray-worker --no-headers 2>/dev/null | grep -c .)
  [ "$RW" = 0 ] || { echo "ABORTA: ray-worker com $RW pods: Bloco K1 de remover-ray.md (D-07)"; exit 1; }
  kubectl describe nodes sabdiia01 sabdiia02 sabdiia03 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  OUT=$(kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}|{.metadata.labels.app}|{.status.phase}|{.spec.containers[*].resources.limits.nvidia\.com/gpu}{"\n"}{end}' | awk -F'|' '$4!="" && $2!="vllm-server" && $3!="Succeeded" && $3!="Failed"')
  [ -z "$OUT" ] || { echo "ABORTA: outro pod segura GPU: $OUT"; exit 1; }
  echo "processos na GPU de 01 (os do vllm-server atual saem no rollout): $(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader | tr '\n' ' ')"
  for NO in sabdiia01 sabdiia02 sabdiia03; do
    kubectl get node $NO -o jsonpath='{range .status.images[*]}{.names}{"\n"}{end}' | grep -q 'vllm/vllm-openai:v0.19.1' || { echo "ABORTA: $NO sem a imagem v0.19.1 (AC-24; seção 1 do Bloco W)"; exit 1; }
  done
  ls /var/lib/vllm-estudo/hf-cache/hub/models--mistralai--Mistral-Nemo-Instruct-2407/snapshots/*/consolidated.safetensors || { echo "ABORTA: pesos do Nemo fora do cache de 01 (Bloco N1 de teste-mistral-nemo.md)"; exit 1; }
  W=$(ls -t d05-w-pesos-*.log 2>/dev/null | head -1)
  [ -n "$W" ] || { echo "ABORTA: rode antes o Bloco W (pesos em 02 e 03)"; exit 1; }
  echo "pesos em 02 e 03, segundo $W:"; grep -E 'consolidated\.safetensors|Succeeded|Failed' "$W" | tail -6
  kubectl get ingressclass kong >/dev/null || { echo "ABORTA: sem IngressClass kong"; exit 1; }
  kubectl get crd kongplugins.configuration.konghq.com kongconsumers.configuration.konghq.com >/dev/null || { echo "ABORTA: CRDs do Kong ausentes"; exit 1; }
  kubectl get pods -n kong -o jsonpath='{range .items[*]}{.spec.hostNetwork}{"\n"}{end}' | grep -q true && { echo "ABORTA: pod do Kong com hostNetwork: a NetworkPolicy por namespace não o reconhece"; exit 1; }
  LBS=$(kubectl get svc -n kong -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.name}{" "}{.status.loadBalancer.ingress[0].ip}{" "}{.spec.externalTrafficPolicy}{" "}{.spec.ports[*].port}{"\n"}{end}' | grep -w 443)
  [ "$(echo "$LBS" | grep -c .)" = 1 ] || { echo "ABORTA: esperava 1 Service LoadBalancer com 443 em kong; achei: $LBS"; exit 1; }
  read -r KSVC KIP ETP _ <<< "$LBS"; echo "proxy do Kong: $KSVC  IP $KIP  externalTrafficPolicy $ETP"
  [ -n "$(kubectl get endpoints "$KSVC" -n kong -o jsonpath='{.subsets[*].addresses[*].ip}')" ] || { echo "ABORTA: proxy do Kong sem endpoints"; exit 1; }
  ROTAS=$(kubectl get ingress -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{" "}{.spec.rules[*].http.paths[*].path}{"\n"}{end}' | grep -v "^$NS/vllm-server ")
  # outra rota sob /vllm/v1 disputaria a nossa; outra sob /vllm convive: o Kong escolhe o prefixo mais longo
  echo "$ROTAS" | grep -E ' /vllm/v1(/|$| )' && { echo "ABORTA: outra rota já usa /vllm/v1"; exit 1; }
  echo "$ROTAS" | grep -E ' /vllm(/|$| )' && echo "AVISO: há outra rota sob /vllm (acima); a nossa, mais longa, tem prioridade no caminho do chat"

  echo "### 2. chave do vLLM (fora do log)   $(date +%T)"
  if kubectl get secret vllm-nemo-api-key -n $NS >/dev/null 2>&1; then
    echo "Secret vllm-nemo-api-key já existe: mantido"
  else
    ( umask 077; printf 'VLLM_API_KEY=%s\n' "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')" > d05-s1.env
      kubectl create secret generic vllm-nemo-api-key -n $NS --from-env-file=d05-s1.env )
    rm -f d05-s1.env
    kubectl label secret vllm-nemo-api-key -n $NS decisao=d-05
  fi

  echo "### 3. manifesto   $(date +%T)"
  if [ $ADOCAO = 1 ]; then
    TS=$(date +%F-%H%M)
    kubectl get deploy vllm-server -n $NS -o yaml > vllm-server-adocao-$TS.yaml
    kubectl get svc vllm-llama-service -n $NS -o yaml > vllm-llama-service-adocao-$TS.yaml 2>/dev/null
    grep -q '^kind: Deployment' vllm-server-adocao-$TS.yaml || { echo "ABORTA: cópia do vllm-server não gravada"; exit 1; }
    chmod 600 vllm-*-adocao-$TS.yaml; ls -l vllm-*-adocao-$TS.yaml
  fi
  kubectl apply -f $M || exit 1
  if [ $ADOCAO = 1 ] && kubectl get svc vllm-llama-service -n $NS >/dev/null 2>&1; then
    if [ "$(kubectl get svc vllm-llama-service -n $NS -o jsonpath='{.spec.selector.app}')" = vllm-server ]; then
      echo "fecha o LoadBalancer sem chave (AC-06, AC-32): $(kubectl get svc vllm-llama-service -n $NS -o jsonpath='{.status.loadBalancer.ingress[0].ip}:{.spec.ports[0].port}')"
      kubectl delete svc vllm-llama-service -n $NS
    else
      echo "AVISO: vllm-llama-service não aponta para app=vllm-server: mantido"
    fi
  fi
  kubectl get deploy vllm-server -n $NS -o jsonpath='rótulos {.metadata.labels}{"\n"}volumes {.spec.template.spec.volumes[*].name}{"\n"}'
  kubectl get deploy vllm-server -n $NS -o jsonpath='{.spec.template.spec.volumes}' | grep -q hf-cache-pvc && echo "AVISO: o PVC do administrador ficou no Deployment (o apply mesclou em vez de substituir): traga o log"
  kubectl get deploy vllm-server -n $NS -o jsonpath='{.spec.template.spec.containers[0].args}' | grep -q trust-remote-code && echo "AVISO: --trust-remote-code continua nos argumentos: traga o log"
  kubectl get svc -n $NS -o wide
  kubectl get ingress vllm-server -n $NS -o jsonpath='plugins na rota: {.metadata.annotations.konghq\.com/plugins}{"\n"}'

  echo "### 4. aguardando as 3 réplicas, trocadas uma a uma (até 45 min)   $(date +%T)"
  T0=$(date +%s); PRONTO=0
  while [ $(( $(date +%s) - T0 )) -lt 2700 ]; do
    ST=$(kubectl get deploy vllm-server -n $NS -o jsonpath='{.status.readyReplicas}/{.status.updatedReplicas}/{.status.unavailableReplicas}')
    [ "$ST" = "3/3/" ] && { PRONTO=1; break; }
    echo "$(date +%T) prontas/atualizadas/indisponíveis = $ST"
    kubectl get pods -n $NS -l app=vllm-server -o wide --no-headers 2>/dev/null | awk '{print "    ", $1, $2, $3, $4, $7}'
    sleep 30
  done
  echo "pronto=$PRONTO depois de $(( ($(date +%s) - T0) / 60 )) min"
  kubectl get pods -n $NS -l app=vllm-server -o wide
  if [ $PRONTO != 1 ]; then
    kubectl describe pods -n $NS -l app=vllm-server | grep -A15 '^Events:'
    kubectl logs -n $NS -l app=vllm-server --prefix --tail=30 2>&1 | cut -c1-250
    echo "FALHOU A SUBIDA: traga o log; para desmontar, Bloco L"; exit 1
  fi
  kubectl logs -n $NS -l app=vllm-server --prefix --tail=-1 | grep -iE 'pesos em|Available KV cache memory|GPU KV cache size|Maximum concurrency|WARNING|ERROR' | grep -vE 'GET /health' | cut -c1-250 | head -30

  echo "### 4b. cada réplica responde?   $(date +%T)"
  for P in $(kubectl get pods -n $NS -l app=vllm-server -o jsonpath='{.items[*].metadata.name}'); do
    NO=$(kubectl get pod $P -n $NS -o jsonpath='{.spec.nodeName}')
    RESP=$(kubectl exec -n $NS $P -- python3 -c 'import json,os,urllib.request as u; r=u.Request("http://127.0.0.1:8000/v1/chat/completions", data=json.dumps({"model":"mistralai/Mistral-Nemo-Instruct-2407","max_tokens":10,"temperature":0,"messages":[{"role":"user","content":"Qual é a capital do Brasil? Responda com uma palavra."}]}).encode(), headers={"Content-Type":"application/json","Authorization":"Bearer "+os.environ["VLLM_API_KEY"]}); print(json.load(u.urlopen(r,timeout=60))["choices"][0]["message"]["content"])' 2>&1 | tail -1)
    echo "$NO $P -> $RESP"
  done

  echo "### 5. de dentro do pod: o que a chave do vLLM protege (AC-32)   $(date +%T)"
  kubectl exec -i -n $NS deploy/vllm-server -- python3 - <<'EOF'
import json, os, urllib.request, urllib.error
B = "http://127.0.0.1:8000"
K = os.environ["VLLM_API_KEY"]
def t(nome, metodo, caminho, corpo=None, chave=False, esperado=None):
    h = {"Content-Type": "application/json"}
    if chave:
        h["Authorization"] = "Bearer " + K
    d = json.dumps(corpo).encode() if corpo is not None else None
    r = urllib.request.Request(B + caminho, data=d, headers=h, method=metodo)
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            c, txt = x.status, x.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        c, txt = e.code, e.read(400).decode("utf-8", "replace")
    except Exception as e:
        c, txt = "ERRO", repr(e)
    ok = "" if esperado is None else ("  [como esperado]" if c == esperado else f"  [ESPERADO {esperado}]")
    print(f"{nome:<34} {metodo:<4} {caminho:<21} chave={'sim' if chave else 'não'} -> {c}{ok} | {' '.join(txt.split())[:170]}")
chat = {"model": "mistralai/Mistral-Nemo-Instruct-2407", "max_tokens": 10, "temperature": 0,
        "messages": [{"role": "user", "content": "Qual é a capital do Brasil? Responda com uma palavra."}]}
t("saúde", "GET", "/health", esperado=200)
t("/v1 sem chave", "GET", "/v1/models", esperado=401)
t("/v1 com chave", "GET", "/v1/models", chave=True, esperado=200)
t("chat /v1 sem chave", "POST", "/v1/chat/completions", chat, esperado=401)
t("chat /v1 com chave", "POST", "/v1/chat/completions", chat, chave=True, esperado=200)
t("SageMaker sem chave (AC-32)", "POST", "/invocations", chat, esperado=200)
t("métricas sem chave", "GET", "/metrics", esperado=200)
t("docs (--disable-fastapi-docs)", "GET", "/docs", esperado=404)
EOF

  echo "### 6. NetworkPolicy: outro pod chega ao vLLM?   $(date +%T)"
  CIP=$(kubectl get svc vllm-server -n $NS -o jsonpath='{.spec.clusterIP}')
  PIP=$(kubectl get pods -n $NS -l app=vllm-server -o jsonpath='{.items[0].status.podIP}')
  KCIP=$(kubectl get svc "$KSVC" -n kong -o jsonpath='{.spec.clusterIP}')
  echo "Service do vLLM $CIP, pod $PIP, proxy do Kong (ClusterIP) $KCIP"
  cat > d05-sonda.yaml <<EOF
apiVersion: v1
kind: Pod
metadata: {name: d05-sonda, namespace: $NS, labels: {app: d05-sonda, decisao: d-05}}
spec:
  nodeSelector: {kubernetes.io/hostname: sabdiia01}
  restartPolicy: Never
  automountServiceAccountToken: false
  containers:
  - name: sonda
    image: vllm/vllm-openai:v0.19.1
    command: ["python3", "-c"]
    args:
    - |
      import os, ssl, urllib.request, urllib.error
      ctx = ssl._create_unverified_context()
      for nome, url in [("vLLM pelo Service (bloqueio esperado)", "http://" + os.environ["CIP"] + ":8000/health"),
                        ("vLLM pelo IP do pod (bloqueio esperado)", "http://" + os.environ["PIP"] + ":8000/health"),
                        ("controle: proxy do Kong (deve responder)", "https://" + os.environ["KCIP"] + "/vllm/")]:
          try:
              c = urllib.request.urlopen(url, timeout=5, context=ctx).status
          except urllib.error.HTTPError as e:
              c = e.code
          except Exception as e:
              c = "sem resposta: " + type(e).__name__ + " " + str(e)[:80]
          print(nome, "->", c, flush=True)
    env:
    - {name: CIP, value: "$CIP"}
    - {name: PIP, value: "$PIP"}
    - {name: KCIP, value: "$KCIP"}
    resources:
      requests: {cpu: "100m", memory: 256Mi}
      limits: {cpu: "1", memory: 1Gi}
EOF
  kubectl apply -f d05-sonda.yaml
  kubectl wait pod/d05-sonda -n $NS --for=jsonpath='{.status.phase}'=Succeeded --timeout=180s
  kubectl logs -n $NS d05-sonda
  kubectl delete pod d05-sonda -n $NS --wait=true

  echo "### 7. a rota no Kong (o controlador leva alguns segundos)   $(date +%T)"
  sleep 20
  kubectl get ingress,kongplugin -n $NS
  kubectl get events -n $NS --sort-by=.lastTimestamp | grep -viE 'pulled|scheduled|created|started|probe' | tail -15 | cut -c1-250

  echo "### 8. de 01 pelo Kong, sem chave   $(date +%T)"
  URL="https://$KIP/vllm/v1/chat/completions"
  printf '%s' '{"model":"mistralai/Mistral-Nemo-Instruct-2407","messages":[{"role":"user","content":"Qual é a capital do Brasil? Responda com uma palavra."}],"max_tokens":10,"temperature":0}' > d05-corpo.json
  k() { rm -f d05-resp.txt; local c; c=$(curl -sk -m 60 -o d05-resp.txt -w 'HTTP %{http_code}' "${@:2}"); echo "$1 -> $c | $(tr -s ' \n' ' ' < d05-resp.txt 2>/dev/null | cut -c1-170)"; }
  k "sem chave (401 do Kong)" -X POST -H 'Content-Type: application/json' --data-binary @d05-corpo.json "$URL"
  k "/vllm/metrics (404: sem rota)" "https://$KIP/vllm/metrics"
  rm -f d05-resp.txt
  echo "Kong em $KIP. Próximo: Bloco C."
  echo "== fim $(date -Is)"
} 2>&1 | tee d05-g1-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** `pronto=1`; a seção 5 sem `[ESPERADO`; a seção 6 com "sem resposta" nas duas primeiras
linhas e um código HTTP na terceira; a seção 8 com 401 e 404.

## Bloco C — Consumidores a partir da lista (servidor `sabdiia01`, bash; repetível)

Lê `d05-consumidores.txt`, copiado pelo E0, e:
- cria a chave do Kong de cada ator novo e **mantém as que já existem**;
- revoga quem saiu da lista;
- grava a lista de IPs **de cada ator** num `KongPlugin` `d05-ip-<nome>` ligado ao `KongConsumer` dele: a chave
  de um ator só vale dos IPs dele (ator `pendente`: só `127.0.0.1`, ninguém de fora);
- grava um arquivo de chave por ator, `d05-chave-<nome>.env` (permissão 600, dono = quem entra por `scp`).

Rode depois do G1 e de novo a cada mudança na lista: edite a lista no notebook, envie com o E0-cópia e rode
este bloco.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  D-05 C: consumidores do Kong a partir de d05-consumidores.txt"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  NS=vllms; F=d05-consumidores.txt
  [ -f $F ] || { echo "ABORTA: $F ausente; rode a seção 5 do E0"; exit 1; }
  sha256sum $F
  kubectl get ingress vllm-server -n $NS >/dev/null && kubectl get secret vllm-nemo-api-key -n $NS >/dev/null || { echo "ABORTA: rode antes o G1"; exit 1; }
  LBS=$(kubectl get svc -n kong -o jsonpath='{range .items[?(@.spec.type=="LoadBalancer")]}{.metadata.name}{" "}{.status.loadBalancer.ingress[0].ip}{" "}{.spec.externalTrafficPolicy}{" "}{.spec.ports[*].port}{"\n"}{end}' | grep -w 443)
  [ "$(echo "$LBS" | grep -c .)" = 1 ] || { echo "ABORTA: esperava 1 Service LoadBalancer com 443 em kong; achei: $LBS"; exit 1; }
  read -r KSVC KIP ETP _ <<< "$LBS"; echo "proxy do Kong: $KSVC  IP $KIP  externalTrafficPolicy $ETP"

  echo "### 1. a lista"
  ERRO=0; NOMES=""; declare -A IPS_DE
  while read -r NOME RESTO; do
    echo "$NOME" | grep -qE '^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$' || { echo "ERRO: nome inválido: $NOME"; ERRO=1; continue; }
    NOMES="$NOMES $NOME"; IPS=""
    for X in $RESTO; do
      [ "$X" = pendente ] && continue
      echo "$X" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}(/(3[0-2]|[12][0-9]|[89]))?$' || { echo "ERRO: IP ou CIDR inválido em $NOME: $X (CIDR de /8 a /32)"; ERRO=1; continue; }
      IPS="$IPS $X"
    done
    IPS_DE[$NOME]="$IPS"
    echo "$NOME:${IPS:- (sem IP: o Kong recusa até o IP entrar na lista)}"
  done < <(tr -d '\r' < $F | grep -vE '^[[:space:]]*(#|$)')
  [ $ERRO = 0 ] || { echo "ABORTA: corrija a lista"; exit 1; }
  [ -n "$NOMES" ] || { echo "ABORTA: lista sem consumidores"; exit 1; }
  D=$(echo $NOMES | tr ' ' '\n' | sort | uniq -d); [ -z "$D" ] || { echo "ABORTA: nome repetido: $D"; exit 1; }
  if [ "$ETP" = Local ]; then
    echo "lista de IPs: uma por consumidor (a chave de um ator só vale dos IPs dele)"
  else
    echo "AVISO: externalTrafficPolicy=$ETP: o Kong vê o IP de um nó, não o do ator. Sem lista de IPs; só as chaves protegem (AC-33)."
  fi

  echo "### 2. chaves, listas de IPs e consumidores (chaves fora do log)   $(date +%T)"
  DONO=${SUDO_USER:-$(stat -c %U /home/utec/vllm-estudo)}
  for N in $NOMES; do
    S=kong-cred-$N
    if kubectl get secret $S -n $NS >/dev/null 2>&1; then
      echo "$N: chave já existe, mantida"
    else
      ( umask 077; printf 'key=%s\n' "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')" > d05-s.env
        kubectl create secret generic $S -n $NS --from-env-file=d05-s.env )
      rm -f d05-s.env
      echo "$N: chave nova"
    fi
    kubectl label secret $S -n $NS konghq.com/credential=key-auth decisao=d-05 d05-consumidor=$N --overwrite >/dev/null
    if [ "$ETP" = Local ]; then
      A=${IPS_DE[$N]:-}; [ -n "$A" ] || A=127.0.0.1
      LISTA=$(for X in $A; do printf '"%s", ' "$X"; done | sed 's/, $//')
      kubectl apply -f - <<EOF
apiVersion: configuration.konghq.com/v1
kind: KongPlugin
metadata:
  name: d05-ip-$N
  namespace: $NS
  labels: {decisao: d-05, d05-consumidor: "$N"}
plugin: ip-restriction
config:
  allow: [$LISTA]
EOF
      PLUG="d05-ip-$N"
    else
      kubectl delete kongplugin d05-ip-$N -n $NS --ignore-not-found >/dev/null
      PLUG=""
    fi
    kubectl apply -f - <<EOF
apiVersion: configuration.konghq.com/v1
kind: KongConsumer
metadata:
  name: $N
  namespace: $NS
  labels: {decisao: d-05, d05-consumidor: "$N"}
  annotations:
    kubernetes.io/ingress.class: kong
    konghq.com/plugins: "$PLUG"
username: $N
credentials: [$S]
EOF
    if [ -n "$PLUG" ]; then echo "$N: IPs liberados: $A"; else echo "$N: sem lista de IPs"; fi
    ( umask 077
      KK=$(kubectl get secret $S -n $NS -o jsonpath='{.data.key}' | base64 -d)
      KV=$(kubectl get secret vllm-nemo-api-key -n $NS -o jsonpath='{.data.VLLM_API_KEY}' | base64 -d)
      printf 'CONSUMIDOR=%s\nMODELO=mistralai/Mistral-Nemo-Instruct-2407\nKONG_IP=%s\nBASE_URL=https://%s/vllm/v1\nCHAVE_KONG=%s\nCHAVE_VLLM=%s\n' "$N" "$KIP" "$KIP" "$KK" "$KV" > d05-chave-$N.env )
    chown "$DONO" d05-chave-$N.env
  done
  for N in $(kubectl get kongconsumer -n $NS -l decisao=d-05 -o jsonpath='{.items[*].metadata.name}'); do
    echo " $NOMES " | grep -q " $N " && continue
    echo "$N saiu da lista: consumidor, chave, lista de IPs e arquivo apagados (revogado)"
    kubectl delete kongconsumer $N -n $NS
    kubectl delete secret kong-cred-$N -n $NS --ignore-not-found
    kubectl delete kongplugin d05-ip-$N -n $NS --ignore-not-found
    rm -f d05-chave-$N.env
  done

  echo "### 3. a rota: chave e limite (a lista de IPs fica em cada consumidor)   $(date +%T)"
  kubectl annotate ingress vllm-server -n $NS konghq.com/plugins=d05-key-auth,d05-rate-limit --overwrite
  # lista única na rota (versão de 2026-11-07 22:48): valia para qualquer chave; sai
  kubectl delete kongplugin d05-ip-restriction -n $NS --ignore-not-found

  echo "### 4. o Kong aceitou?   $(date +%T)"
  sleep 20
  kubectl get kongconsumer,kongplugin,ingress -n $NS
  kubectl get ingress vllm-server -n $NS -o jsonpath='plugins na rota: {.metadata.annotations.konghq\.com/plugins}{"\n"}'
  kubectl get events -n $NS --sort-by=.lastTimestamp | grep -viE 'pulled|scheduled|created|started|probe' | tail -10 | cut -c1-250

  echo "### 5. de 01 com a chave de cada ator (01 fora da lista: 403 se a lista vale, 200 se não)   $(date +%T)"
  URL="https://$KIP/vllm/v1/chat/completions"
  printf '%s' '{"model":"mistralai/Mistral-Nemo-Instruct-2407","messages":[{"role":"user","content":"Qual é a capital do Brasil? Responda com uma palavra."}],"max_tokens":10,"temperature":0}' > d05-corpo.json
  for N in $NOMES; do
    ( umask 077; . ./d05-chave-$N.env; printf 'apikey: %s\nAuthorization: Bearer %s\n' "$CHAVE_KONG" "$CHAVE_VLLM" > d05-h.txt )
    rm -f d05-resp.txt
    C=$(curl -sk -m 60 -o d05-resp.txt -w 'HTTP %{http_code}' -X POST -H @d05-h.txt -H 'Content-Type: application/json' --data-binary @d05-corpo.json "$URL")
    echo "$N -> $C | $(tr -s ' \n' ' ' < d05-resp.txt 2>/dev/null | cut -c1-150)"
  done
  rm -f d05-h.txt d05-resp.txt

  echo "### 6. arquivos de chave (entregar cada um só ao seu ator)"
  ls -l d05-chave-*.env
  echo "== fim $(date -Is)"
} 2>&1 | tee d05-c-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** a seção 1 sem `ERRO`, a seção 4 sem eventos de falha, a seção 5 com o mesmo código para
todos os atores (403 ou 200), e a seção 6 com um arquivo por ator.

**Entregar as chaves.** Copie os arquivos para a estação:
`scp "${u}@192.168.50.151:/home/utec/vllm-estudo/d05-chave-*.env" "$env:USERPROFILE\.vllm-estudo\"`.
Mande cada arquivo **só ao seu ator**, por um canal privado (não em grupo, não no repositório), e apague a
cópia depois de entregar. Quem receber o arquivo de outro ator passa a valer por ele no limite e nos logs.
Para trocar a chave de um ator, apague o `Secret` dele (comando em COMANDOS.md) e rode o Bloco C.

## Bloco E1 — Testes de fora (notebook ou máquina virtual, PowerShell)

Usa a chave do consumidor da máquina onde roda (`wsantos` ou `estacao`) e, para o teste de IP fora da lista, a de um ator `pendente`. Copia as
duas para `%USERPROFILE%\.vllm-estudo\`, fora do repositório, e apaga tudo no fim. O log grava códigos e
respostas, nunca as chaves. O teste de limite fica por último porque esgota a cota do minuto.

Script: [runbooks/ps/d05-e1.ps1](ps/d05-e1.ps1). No terminal PowerShell do notebook (prompt `PS C:\...>`):

```powershell
pwsh -ExecutionPolicy Bypass -File C:\www\vllm-master\runbooks\ps\d05-e1.ps1
```

**Pronto se:** a seção 1 mostra 401, 401, 401, 200 com "Brasília" e 403; a seção 2, o primeiro *byte* bem
antes do total; as seções 3 e 4, nenhum 200.

## Bloco D2 — Teste do ator com a chave recebida (máquina de cada ator, PowerShell)

Envie ao ator junto com o arquivo de chave dele, depois que o IP dele entrou na lista e o Bloco C rodou. Ele
devolve o log da Área de Trabalho, que não contém as chaves.

Script: [runbooks/ps/d05-d2.ps1](ps/d05-d2.ps1). Envie o arquivo ao ator; ele o salva na Área de Trabalho e roda
no PowerShell, a partir da Área de Trabalho:

```powershell
powershell -ExecutionPolicy Bypass -File .\d05-d2.ps1
```

**Para a aplicação** `[não verificado]`: `BASE_URL` do arquivo como `baseURL` do cliente OpenAI do Vercel AI
SDK; `CHAVE_VLLM` como `apiKey`; cabeçalho extra `apikey` com `CHAVE_KONG`. As chaves ficam em variáveis de
ambiente do **servidor** Next.js, nunca em variável exposta ao navegador. O Node.js recusa certificado
autoassinado (PD-34). Não mande `chat_template_kwargs` ao Nemo (AC-29). Se a equipe usar Linux ou macOS, os
blocos D1 e D2 precisam de uma versão em bash.

## Bloco L — Desmonta: guarda os logs e apaga tudo do estudo (servidor `sabdiia01`, bash)

Só quando o ambiente for desmontado, ou se o G1 falhar e for preciso recomeçar. Apaga as réplicas, a rota,
os consumidores e todas as chaves. Não toca no que é do administrador.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  D-05 L: log do pod e limpeza"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  NS=vllms
  echo "### 1. logs das réplicas e requisições recebidas por réplica (origem = IP do pod do Kong)"
  L=d05-vllm-server-pods-$(date +%F-%H%M).log
  kubectl logs -n $NS -l app=vllm-server --prefix --tail=-1 > "$L" 2>&1; echo "$L: $(wc -l < "$L") linhas"
  grep -E '"(GET|POST) ' "$L" | grep -v '/health' | sed -E 's#^\[pod/([^/]+)/[^]]*\] .* ([0-9.]+):[0-9]+ - "(GET|POST) ([^ ]+) HTTP/1\.1" ([0-9]+).*#\1 \2 \3 \4 \5#' | sort | uniq -c
  kubectl get pods -n kong -o wide --no-headers | awk '{print "pod do Kong:", $1, $6}'
  echo "### 2. apaga o que W, G1 e C criaram (só decisao=d-05)"
  kubectl delete pod d05-sonda -n $NS --ignore-not-found
  kubectl delete pods -n $NS -l app=d05-pesos --ignore-not-found
  [ -f vllm-nemo-gateway.yaml ] && kubectl delete -f vllm-nemo-gateway.yaml --ignore-not-found --wait=true --timeout=180s
  kubectl delete kongconsumer,kongplugin,secret -n $NS -l decisao=d-05 --ignore-not-found
  rm -f d05-chave-*.env d05-h*.txt d05-corpo.json d05-resp.txt d05-s.env d05-s1.env
  echo "### 3. o que sobrou"
  kubectl get all,ingress,networkpolicy,secret,kongplugin,kongconsumer -n $NS -l decisao=d-05
  kubectl get deploy,ds -n $NS -l 'decisao!=d-05'
  ls -l d05-* 2>/dev/null
  kubectl describe nodes sabdiia01 sabdiia02 sabdiia03 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
  echo "== fim $(date -Is)"
} 2>&1 | tee d05-l-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** a seção 3 não lista nada com `d-05` (o `vllm-server` adotado também sai); só sobram os
`.log`, o `.yaml`, a lista e as cópias `vllm-*-adocao-*.yaml`; as 3 GPUs mostram `0 0`. Para devolver ao
administrador, reaplique essas cópias, só por decisão do usuário. Os pesos em `/var/lib/vllm-estudo/hf-cache`
ficam nos nós. Peça aos atores que apaguem os arquivos de chave:
depois do L, eles não valem mais.

## Trazer os logs (notebook, PowerShell)

Os logs do E0 e do E1 já estão em `logs-analysis/`. Os dos atores (D1, D2) chegam por eles; salve-os também
em `logs-analysis/`.

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
scp "${u}@192.168.50.151:/home/utec/vllm-estudo/d05-*.log" "C:\www\vllm-master\logs-analysis\"
```

## O que olhar

| Onde | O que | Leitura |
|---|---|---|
| W seção 3 | `ErrImagePull`, `ImagePullBackOff` | Imagem ausente no nó: `ctr -n k8s.io images pull` no próprio nó (AC-24) |
| W seção 4 | erro de resolução de nome ou `LocalEntryNotFoundError` | O nó não chega ao Hugging Face: DNS ou *proxy* do nó |
| G1 seção 3 | `AVISO: o PVC do administrador ficou` ou `--trust-remote-code continua` | O `apply` mesclou com a configuração antiga: compare com `vllm-server-adocao-*.yaml` antes de seguir |
| G1 seção 4 | réplica `Pending` | GPU ocupada no nó por algo fora do Kubernetes (Ray no *host*, AC-19) ou a anti-afinidade barrando uma 2ª réplica num nó, o esperado |
| G1 seção 4 | troca parada com 2 réplicas antigas no ar | A 1ª réplica nova não sobe (pesos ausentes naquele nó? Bloco W): as antigas seguem atendendo; traga o log |
| G1 seção 4b | réplica sem "Brasília" | Pesos diferentes ou corrompidos naquele nó: compare a seção 4 do W |
| K0 seção 1 | `ContainerStatusUnknown`, `CrashLoopBackOff` | Kong doente: pare e fale com o administrador. Plano B da D-05: `LoadBalancer` direto com `--api-key` e `NetworkPolicy` só dos IPs dos atores, sem rota única (`/invocations` fica aberto, AC-32) |
| K0 seção 4 | `KongClusterPlugin` com `global: true` | Vale para a nossa rota também: anote qual |
| E0 seção 2 / D1 seção 2 | 443 `False` | *Firewall* ou rota entre a rede do ator e o IP do MetalLB: infraestrutura |
| D1 seção 1 | `PrefixOrigin` `Dhcp` | IP muda: reserva no DHCP ou faixa CIDR na lista |
| G1 seção 5 | `/invocations` 200 sem chave | Confirma AC-32 na execução |
| G1 seção 6 | as duas primeiras linhas com código HTTP | A `NetworkPolicy` não está valendo (o Calico aplica `NetworkPolicy` `[não verificado]` neste *cluster*): o desenho perde uma camada |
| G1 seção 7 / C seção 4 | eventos `KongConfigurationTranslationFailed` ou `KongConfigurationApplyFailed` | Campo de *plugin* ou anotação recusado pelo KIC 3.5 / Kong 3.9: traga o log |
| C seção 3 | `AVISO: externalTrafficPolicy` | Sem lista de IPs: só as chaves protegem. Mudar o `Service` do Kong para `Local` é decisão do administrador (afeta todas as rotas dele) |
| C seção 5 / E1 seção 1 | 503 ou 502 com chave | O Kong não alcança o *pod*: `NetworkPolicy` ou rótulo do *namespace* `kong` |
| E1 seção 1, linha 4 / D2 seção 1 | 403 `IP address not allowed` | O Kong vê outro IP (NAT no caminho): o IP certo é o que o Kong vê, não o da máquina. Peça à infraestrutura o IP de saída da rede do ator |
| E1 seção 1 | 404 no caminho certo | `strip-path` + `konghq.com/path` não montaram `/v1/chat/completions`: veja o caminho no log do *pod* (Bloco L, seção 1) |
| E1 seção 2 / D2 seção 2 | primeiro *byte* ≈ total | O Kong acumula a resposta: `response-buffering` não pegou |
| E1 seção 6 | nenhum 429 | Vários *pods* de *proxy* (`policy: local`) ou *plugin* fora da rota |
| L seção 1 | IPs de origem | Só IPs de *pods* do Kong e `127.0.0.1` (testes internos) |

## Depois

- Resultado no AC-32 (execução) e na D-05 (de provisória para confirmada ou revista); PD-26 fecha ou muda.
- Em produção: só o IP do servidor da aplicação na lista, um consumidor por aplicação, e um limite por minuto
  acima da capacidade total, ~214 requisições/min por GPU com 32 usuários (AC-31, 2 chamadas por pergunta)
  `[hipótese para 3 réplicas]`. O limite por usuário final fica na aplicação.
