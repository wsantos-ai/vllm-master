# Certificado válido para as rotas do vLLM no Kong (PD-34)

Modelo do administrador (`docs-analysis/certificado-exemplo-1.txt` e `-2.txt`, outro *cluster*): cert-manager,
`ClusterIssuer` `letsencrypt-cloudflare` (Let's Encrypt, desafio DNS-01 pela Cloudflare), `Certificate` para um nome em
`abdi.com.br` e `spec.tls` no `Ingress` do Kong. Neste *cluster* o cert-manager foi instalado em 2026-11-12 e o emissor
está `READY False` porque falta o *Secret* com o *token* da Cloudflare
([T0](../logs-analysis/pd34-t0-sabdiia01-2026-11-12-1700.log)). **O administrador pediu ao usuário que crie o que falta
a partir dos exemplos (2026-11-12).**

| Bloco | O que faz |
|---|---|
| T0 | só leitura: cert-manager, emissores, certificados e `Ingress` (rodado em 2026-11-12 17:00) |
| T1 | grava o *token* da Cloudflare no *Secret* que o emissor espera e espera o emissor ficar `Ready` |
| T1-desfazer | apaga o *Secret* |

## Gerar o *token* na Cloudflare (navegador, quem tem acesso à conta da ABDI)

Conferido na doc do cert-manager em 2026-11-12 [F-058]:

1. Cloudflare → ícone do usuário → **My Profile** → **API Tokens** → **Create Token** → modelo **Edit zone DNS**
   (ou **Custom token**).
2. **Permissions:** `Zone` · `DNS` · `Edit` e `Zone` · `Zone` · `Read`.
3. **Zone Resources:** a doc recomenda `Include` · `All zones`. O mínimo necessário é `Include` · `Specific zone` ·
   `abdi.com.br`, que limita o estrago se o *token* vazar.
4. Opcional: **Client IP Address Filtering** com o IP de saída do *cluster* para a internet, e **TTL** (data de
   expiração). Com expiração, o certificado deixa de renovar quando o *token* vencer: anote a data.
5. **Continue to summary** → **Create Token** → copie o *token*. Ele aparece uma vez só.

O *token* é segredo: não vai para o chat, e-mail, repositório nem log. Ele só passa pelo terminal, no T1.

## T1 — *Token* no *Secret* do emissor (servidor `sabdiia01`, bash com `kubectl`)

O bloco lê do próprio emissor o nome do *Secret* e a chave que ele espera, e lê do cert-manager o *namespace* em que
um `ClusterIssuer` procura segredos (o padrão é `cert-manager`). O *token* é pedido sem eco (`read -s`), não fica no
histórico do bash e não vai para o log. Autorização: o administrador, em 2026-11-12. Cópia antes: não há (o *Secret*
não existe; o bloco aborta se existir).

**Expectativa (escrita antes):**
- seção 1: servidor ACME do Let's Encrypt, um e-mail, `apiTokenSecretRef` com `name: cloudflare-api-token-secret`;
- seção 2: `secret/cloudflare-api-token-secret created`;
- seção 3: emissor `Ready True` em até 2 min (o cert-manager registra a conta ACME). O `Ready` **não prova** que o
  *token* funciona: a Cloudflare só é chamada quando um certificado é pedido (próximo bloco).

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  T1: token da Cloudflare no secret do emissor (PD-34)"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: rode em sabdiia01 (kubectl)"; exit 1; }
  CI=letsencrypt-cloudflare
  R='{.spec.acme.solvers[0].dns01.cloudflare.apiTokenSecretRef'
  SN=$(kubectl get clusterissuer $CI -o jsonpath="$R.name}")
  SK=$(kubectl get clusterissuer $CI -o jsonpath="$R.key}")
  A=$(kubectl get deploy cert-manager -n cert-manager \
    -o jsonpath='{.spec.template.spec.containers[0].args}')
  CRN=$(echo "$A" | grep -o 'cluster-resource-namespace=[a-z0-9-]*' | cut -d= -f2)
  CRN=${CRN:-cert-manager}

  echo "### 1. o que o emissor espera"
  kubectl get clusterissuer $CI \
    -o jsonpath='servidor: {.spec.acme.server}{"\n"}e-mail: {.spec.acme.email}{"\n"}'
  echo "secret: $SN  chave: $SK  namespace: $CRN"
  [ -n "$SN" ] && [ -n "$SK" ] || { echo "ABORTA: o emissor não usa apiTokenSecretRef"; exit 1; }
  kubectl get secret "$SN" -n "$CRN" >/dev/null 2>&1 && { echo "ABORTA: $SN já existe"; exit 1; }

  echo "### 2. o token (colar; não aparece na tela)"
  read -rsp "Token da Cloudflare: " TK < /dev/tty; echo
  [ ${#TK} -ge 30 ] || { echo "ABORTA: token curto demais (${#TK} caracteres)"; exit 1; }
  kubectl create secret generic "$SN" -n "$CRN" --from-file="$SK"=<(printf '%s' "$TK")
  unset TK
  kubectl get secret "$SN" -n "$CRN" -o jsonpath='chaves no secret: {.data}{"\n"}' \
    | sed 's/:"[^"]*"/:"<oculto>"/g'

  echo "### 3. emissor   $(date +%T)"
  kubectl wait --for=condition=Ready clusterissuer/$CI --timeout=120s
  kubectl get clusterissuer $CI -o wide
  echo "== fim $(date -Is)"
} 2>&1 | tee pd34-t1-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** seção 3 com `READY True`. Se continuar `False`, a mensagem diz o motivo (o T0 mostrou o formato).

### T1-desfazer (servidor `sabdiia01`, bash)

Apaga o *Secret*; o emissor volta a `READY False`. Revogue também o *token* na Cloudflare (My Profile → API Tokens →
Roll ou Delete) se ele não for mais usado ou se vazou.

```bash
kubectl delete secret cloudflare-api-token-secret -n cert-manager
```
