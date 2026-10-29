# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# vLLM em Kubernetes com Tesla V100S — Estudo de Caso

Este repositório **não é código**: é o registro de um estudo de caso sobre como configurar o **vLLM**
num *cluster* Kubernetes com **GPUs Tesla V100S de 32 GB** até chegar à **configuração ótima** desse
ambiente. Não há *build*, *lint* nem testes. O trabalho é: descobrir o ambiente, executar, medir,
registrar e decidir.

Estudo iniciado em 2026-09-28. O estado do ambiente vive em §2 do estudo (Ficha do ambiente); o
resumo que muda o jeito de trabalhar é este:

- **3 nós** Dell R720 (`sabdiia01..03`, todos `control-plane`, 32 vCPU e ~755 GiB de RAM cada), **1
  Tesla V100S-PCIE-32GB por nó**. Um *pod* tem no máximo 1 GPU; *tensor parallel* dentro de um nó não
  existe (AC-01, AC-04).
- *Runtime* **containerd**, não Docker; GPU entregue pelo **NVIDIA GPU Operator**; *driver*
  `580.173.02` / CUDA 13.0 instalado no *host* (AC-02, AC-04). Escreva manifestos K8s, não `docker run`.
- Armazenamento só em **NFS**; o cache de modelos é o PVC `vllms/hf-cache` (AC-03). **Entre *pods*, rede
  de 1 GbE por destino** (`bond0`, LACP com *hash* `layer2`; é o IP que o Calico usa), então nada de
  *tensor parallel* multinó. Desde 2026-10-28 existe `bond1` (4 × 10 GbE, só IPv6 da VLAN 302, a do
  NFS), que os *pods* não usam (AC-08). A porta a 100 Mbps de `sabdiia01` segue fora do agregado. Desde
  2026-10-28, **`/` tem 631 G e `/home` 200 G nos 3 nós** (534-580 G livres em `/`, 77-156 G em `/home`);
  imagens e `etcd` ficam em `/` (AC-09; o `/` de 70 G encheu em 2026-10-27, AC-20). CPU sem AVX2. Docker e
  Podman foram instalados nos 3 nós, fora do Kubernetes, com `data-root` em `/home/utec/docker_data`.
  `kubectl` falha em `sabdiia03` (OIDC): blocos com `kubectl` rodam em 01 ou 02.
- **Há produção no *namespace* `vllms`**: `vllm-deepseek-33b` (`v0.6.4`, GPTQ) em `sabdiia03`, exposto
  em `192.168.50.160:8001` sem autenticação (AC-05, AC-06). **Desde 2026-10-28 o deepseek e o
  llama estão em `0/0`** (não apagados). O Ray do administrador rodou em 3 *pods* em `vllms` (`v0.5.4`, 1 GPU
  cada) de 2026-10-28 ~14:50 a 17:10 e foi removido (AC-19). **Em 2026-10-29 10:35, GPUs de 01 e 02 livres e
  `vllms` vazio** (§2); o estado muda de um dia para o outro: rode o Bloco 0 de
  [runbooks/teste-protocolo-modelos.md](runbooks/teste-protocolo-modelos.md) antes de usar GPU. **Nunca proponha parar, reiniciar, editar
  ou apagar recursos de `vllms` sem o usuário pedir explicitamente.** Experimentos vão para uma GPU livre,
  com `Service` `ClusterIP`. O Ray do administrador roda no *host* e, quando liga, ocupa as GPUs de
  `sabdiia01` e `sabdiia02` sem o Kubernetes saber, que continua mostrando as duas como livres (AC-19;
  ocupadas às 12:14 e vazias às 14:20 de 2026-10-27). Em 2026-10-28 14:21 a GPU de `sabdiia03` também
  estava vazia (o deepseek usava 27.882 MiB na véspera): confira o *pod* antes de supor produção no ar. Livre é `0 0`
  no Kubernetes **e** `nvidia-smi --query-compute-apps` vazio ("Qual GPU está livre?" do COMANDOS.md).
  O Ray do administrador segue a mesma regra de `vllms`: não proponha pará-lo sem o usuário pedir. O estudo
  sobe o **próprio** Ray em `vllm-estudo`, criado e apagado pelo
  [runbook](runbooks/teste-ray-pp2-qwen25-7b.md) (AC-23). Antes do 1º *pod* com uma imagem do vLLM num nó,
  baixe-a com `ctr -n k8s.io images pull`: pelo *kubelet*, o *pull* da `v0.19.1` cai por limite de 5 min (AC-24).
- **Testes de modelos da equipe** seguem um protocolo fixo (512 → 256 *tokens*, `temperature 0`, c=1/16/32)
  e são registrados em `C:\www\vllm-config\docs\registro-de-testes.md` (repositório compartilhado, `T-xxx`);
  o procedimento é o [runbook do protocolo](runbooks/teste-protocolo-modelos.md).

**Produto final:** [ESTUDO-DE-CASO.md](ESTUDO-DE-CASO.md). Quem chegar com hardware parecido lê em vinte
minutos e sai sabendo que versão instalar, que manifesto aplicar, quanto cabe na GPU e quais alavancas
de otimização existem, cada uma com ganho e custo **medidos**.

Idioma: **português do Brasil**. Termos técnicos em inglês (*inference*, *throughput*, *KV cache*,
*prefill*, *decode*, *quantization*, *tensor parallel*) ficam em inglês, em itálico na primeira
ocorrência de cada arquivo. Flags, comandos, campos de YAML e mensagens de erro nunca são traduzidos.

---

## Restrições que o hardware impõe (verificar antes de confiar)

V100S é Volta, *compute capability* 7.0 (`sm_70`, confirmado por GFD). Na literatura geral isso
implica as restrições abaixo, todas `[não verificado]` neste ambiente até existir log que as confirme:

- **Sem BF16 nativo**: modelos publicados em `bfloat16` devem rodar em `float16`.
- **Sem FP8** e sem vários *kernels* de *attention*/*quantization* que exigem Ampere (`sm_80`) ou mais.
- **Suporte do vLLM a `sm_70` acaba na `v0.19.1`** (AC-11): a `v0.20.0` passou a CUDA 13 e tirou o `7.0`
  da lista de arquiteturas. **Nunca sugira imagem `v0.20.0` ou posterior** (nem `-cu129`) sem conferir
  `torch_cuda_arch_list` no Dockerfile da *tag*. **Imagem de referência: `v0.19.1`** (D-01, confirmada
  em 2026-10-02): roda na V100S com motor V1, *attention* Triton e *CUDA graphs*, sem `--enforce-eager`,
  em CPU sem AVX2 (AC-13). Também roda: `v0.6.4` + GPTQ, com XFormers (AC-05).
- **CUDA 13 não compila para Volta** (AC-04, F-002). Não sugira atualizar o *driver* dos nós sem checar
  suporte a Volta.
- ***Quantization*:** GPTQ roda (CC ≥ 6.0), mas sem Marlin (exige CC ≥ 7.5): **GPTQ de 4 bits usa o
  `gptq_gemm`, que a própria `v0.19.1` chama de defeituoso** (AC-15). Prefira GPTQ Int8 ou FP16, e
  confira a resposta, não só a velocidade. **AWQ não** (CC ≥ 7.5); FP8 não. bitsandbytes roda, lento
  (~3 *tokens*/s num 27B, AC-14).

Toda decisão de modelo, precisão e versão passa por essas quatro linhas.

---

## O critério do ouro

Antes de escrever qualquer coisa no estudo de caso, pergunte:

1. **Muda uma decisão?** De versão, manifesto, flag, alocação de GPU ou operação.
2. **Evita uma falha que aconteceu de verdade?**
3. **É um número medido de que uma decisão depende?**

Se nenhuma das três, é terra: a saída bruta vai para `logs-analysis/` e o texto não entra no estudo.
Teste final: se o parágrafo sumir, quem vai repetir o caso decide pior? Se não, o parágrafo sai.

## Regras inegociáveis

- **Nenhum número inventado.** Todo valor de VRAM, latência, *throughput* ou versão vem de execução
  guardada em `logs-analysis/` ou de fonte `[F-xxx]` em [FONTES.md](FONTES.md). Ilustração leva
  `[número fictício para ilustração]`.
- **Flag, campo de manifesto ou valor padrão inventado é o pior erro possível.** Só escreva o que foi
  conferido na doc ou no código **da versão em uso**, com a data da conferência, ou no log de arranque.
- **O ambiente é parte da afirmação.** "vLLM entrega X tokens/s" está incompleto. O mínimo: modelo,
  precisão, nº de GPUs, versão do vLLM (tag da imagem), flags, carga e métrica, com referência à versão
  da ficha do ambiente (§2 do estudo).
- **Marque a incerteza:** `[confirmado]`, `[hipótese]`, `[não verificado]`, `[não executado]`,
  `[não medido]`. Texto sem marcador lê-se como confirmado e exige âncora.
- **Separe três camadas:** o que a doc promete, o que foi medido e a explicação da diferença (esta
  quase sempre `[hipótese]`).
- **Uma variável por vez.** Otimização sem linha de base não prova nada.

---

## Estrutura do repositório

```
ESTUDO-DE-CASO.md   — O DOCUMENTO (seções abaixo)
README.md           — porta de entrada
FONTES.md           — fontes externas [F-xxx], com versão e data de consulta
COMANDOS.md         — glossário de comandos por pergunta, com marca [executado]/[não executado];
                      ao usar um comando novo no chat ou num runbook, acrescente-o aqui
runbooks/           — procedimentos executáveis (inventário, primeiro arranque, diagnóstico)
configs/            — manifestos K8s, Dockerfiles e values usados de verdade, com cabeçalho de ambiente
logs-analysis/      — evidência bruta: logs e saídas que ancoram os achados
medicoes/           — (criar quando necessário) uma medição [B-xxx] por arquivo
```

Não crie arquivo ou pasta antes de precisar. Quando um item de §7 passar de uma tela, extraia para
arquivo próprio ligado a partir do estudo (ex.: `medicoes/B-001-baseline.md`).

### `ESTUDO-DE-CASO.md` — seções

| § | Seção | Guarda |
|---|---|---|
| — | Resumo | 4-6 frases que valem sozinhas, cada uma apontando para um achado |
| 1 | Contexto e pergunta | objetivo e restrições que decidem o caso |
| 2 | Ficha do ambiente | estado **atual** do *cluster*, nó e GPUs, com o comando que produziu cada valor |
| 3 | O caminho | cronologia: data, evento, achado gerado. Uma linha por marco |
| 4 | Achados `AC-xx` | o ouro, na forma fixa abaixo |
| 5 | Decisões | o escolhido, o descartado e por quê |
| 6 | Configuração de referência | manifesto/comando em uso e números do arranque |
| 7 | Otimização | alavancas com efeito medido; pendências `PD-xx` priorizadas |
| 8 | Lições | o que vale fora deste ambiente |
| 9 | Correções | uma linha por correção, com o mecanismo do erro |
| — | Evidências | mapa `logs-analysis/` → o que cada arquivo prova |

### Anatomia de um achado

```markdown
### AC-xx — <a afirmação, em uma linha que já é útil sozinha>

**O que é.** <2-6 frases. O mecanismo, só até onde ajuda a decidir.>

**Evidência.** <saída recortada, não editada, com link para logs-analysis/ ou [F-xxx]>

**Regra prática.** <o que fazer; comando ou trecho de manifesto executado>

**Validade.** <versão do vLLM, ambiente, data; o que NÃO foi testado>
```

Um achado cabe numa tela. Se não couber, são dois achados ou tem terra dentro.

### Pendências `PD-xx`

Cada uma tem: pergunta, **que decisão destrava** e **como fechar** (experimento ou leitura).
Pendência que não destrava decisão não entra. Ao fechar, vira achado, decisão ou medição, ou sai com a
razão numa linha de §9.

### Medições `[B-xxx]`

Só valem com: versão da ficha, tag da imagem, flags exatas, recursos do *pod* (`nvidia.com/gpu`, CPU,
memória, `/dev/shm`), carga (concorrência, tokens de entrada e saída, nº de requisições), *warmup*,
p50/p95/p99 de TTFT, ITL e *throughput*, o comando do gerador de carga e a saída guardada. Confira:

- [ ] Houve *warmup*?
- [ ] A GPU estava exclusiva para o *pod* medido (nenhum outro *pod*/processo em `nvidia-smi`)?
- [ ] Uma variável por vez em relação à linha de base?
- [ ] *Prompts* repetidos? Confira no log de arranque se *prefix caching* está ativo; ele infla a
      segunda rodada.
- [ ] Sem `--enforce-eager`? Com ele, o número é piso, não medida.
- [ ] Amostragem fixada? Confira se o `generation_config.json` do modelo sobrescreve os padrões.
- [ ] O gerador de carga roda onde? (dentro do *cluster* ou fora: a rede entra na latência)
- [ ] **A GPU sustentou o *clock* durante a carga?** Grave `nvidia-smi` (temperatura, *clock*, potência) a
      cada 2 s e `nvidia-smi -q -d PERFORMANCE`. Com `SW Thermal Slowdown` ativo, o número é da
      refrigeração, não do motor: a V100S de `sabdiia01` caía a ~400 MHz em 2 min, até o ajuste de
      refrigeração de 2026-10-22 (AC-17). O critério é o contador `SW Thermal Slowdown` parado, não um
      piso de *clock*.

---

## Como trabalhar aqui

### Onde os comandos rodam

Esta estação é **Windows/PowerShell** e não tem acesso direto ao servidor: os comandos são colados pelo
usuário no servidor. Todo bloco colável diz **no título** a máquina e o *shell* (servidor/bash com
`kubectl`, ou estação/PowerShell). **Nenhum *placeholder*:** o bloco traz valores reais já conferidos
(imagem, *tag*, nó) ou os descobre sozinho. Um *placeholder* colado sem edição virou nome de imagem
inválido três vezes seguidas no Bloco 3 (§9). O `tee` grava **todas** as etapas do bloco, não só a
última, para que a falha apareça no log. O nome do log usa `$(hostname -s)`, nunca o nó escrito à mão, e
o bloco feito para um nó aborta em outro: um bloco de 01 rodou em 03 e gravou o log com o nome de 01 (§9).

### Ao executar algo no servidor

1. **Inventário e preflight primeiro:** [runbooks/inventario-do-ambiente.md](runbooks/inventario-do-ambiente.md).
2. **Guarde a saída** em `/home/utec/vllm-estudo/` no nó onde o bloco rodou: todo bloco começa com
   `mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo` e termina em
   `2>&1 | tee <descricao>-$(date +%F-%H%M).log`. O usuário traz o `.log` por `scp` (comando no topo
   do runbook), não por cópia de tela. Sem log guardado, a execução não existiu.
3. **Escreva antes o que espera ver.** A diferença entre expectativa e resultado costuma virar achado.
4. Copie o log para `logs-analysis/` e registre em "Evidências".
5. **Aplique o critério do ouro** e atualize achado, §2, §5, §6, §7 conforme o caso.

### Ao responder perguntas

- **Resposta direta primeiro**, depois o porquê, depois a evidência.
- Procure antes um `AC-xx` sobre o assunto; existindo, responda a partir dele. Divergindo, diga.
- Se a resposta depende do hardware, responda para este ambiente e diga o que mudaria em outro.
- Se a conversa produziu achado novo, **proponha a inclusão** no formato fixo.

### Ao pesquisar

Fonte primária antes de fórum ou blog: doc do vLLM **com versão e data**, código da tag em uso,
*issue*/PR, doc do NVIDIA GPU Operator/*device plugin*, doc do Kubernetes. Registre em
[FONTES.md](FONTES.md). Sem confirmação, `[não verificado]`; se bloquear decisão, abra `PD-xx`.
Antes de escrever "a partir da versão X", confira mais de um ponto: generalizar de uma única amostra é
o erro mais comum neste tipo de estudo.

### Ao corrigir

Corrija no lugar e acrescente uma linha em §9 com o **mecanismo do erro**.

---

## Segurança, disco e segredos

- **Exposição:** o servidor OpenAI-compatível do vLLM não exige autenticação por padrão
  `[não verificado na versão em uso]`. Todo manifesto declara como o `Service` é exposto
  (`ClusterIP`/`NodePort`/`Ingress`) e se usa `--api-key`, ou registra o risco assumido.
- **Disco:** *weights* têm dezenas de GB. O cache de modelos (`HF_HOME`) fica em volume persistente,
  nunca na camada do contêiner, ou cada reinício do *pod* baixa tudo de novo. Registre onde cada modelo
  mora e quanto ocupa.
- **Segredos:** *token* do Hugging Face e chaves de API vão em `Secret` do K8s criado fora do
  repositório. Nunca versione valor real; só modelos (`*.example`).
- ***Kubeconfig*:** o usuário acompanha o *cluster* pelo Freelens com um *kubeconfig* fornecido pelo
  administrador (não tem acesso ao `admin.conf`). O lugar dele é `%USERPROFILE%\.kube\`, fora do repositório.
  Não leia o conteúdo nem o copie para arquivos do estudo. O que se vê no Freelens não conta como
  evidência: a evidência é o log gravado com `tee`.

## Commits

O diretório ainda não é repositório git (2026-09-28). Quando for: um assunto por *commit*, no
imperativo, descrevendo **o que mudou no conhecimento**, sem emoji.

- ✅ `Registra que a imagem X não traz kernels sm_70`
- ❌ `Atualiza ESTUDO-DE-CASO.md`

---

## As perguntas do caso, em ordem

A lista viva e priorizada está em §7 do estudo; esta é só a ordem de ataque:

1. **Inventário.** Concluído em 2026-09-29 (AC-01 a AC-10). Uma imagem recente do vLLM ocupa ~3,3× o
   tamanho comprimido (medido: `v0.12.0` = 27 G; `v0.19.1` ≈ 29 G; AC-09); com `/` de 631 G (desde
   2026-10-28) cabem várias por nó. Remoção de imagem só **por *digest***, as três
   referências, medindo `df` antes e depois (Passo 3 do runbook de primeiro arranque); remover pelo nome
   não libera espaço.
2. **Versão viável.** Fechado: `v0.19.1` (AC-11, AC-13).
3. **Primeiro arranque.** Feito em 2026-10-02 em `sabdiia01` (AC-13, §6), pelo
   [runbook](runbooks/primeiro-arranque-v0.19.1.md). `sabdiia01` era o nó de testes (D-02, **suspensa em
   2026-10-27**: GPU disputada com o Ray do administrador e `v0.19.1` apagada de 01; AC-19, AC-20, PD-29. O
   disco deixou de bloquear em 2026-10-28, PD-15 fechada; falta o acordo das GPUs). Nunca interrompa
   um bloco de arranque com Ctrl+C: o *pod* continua sozinho; use `kubectl delete pod`.
   O modelo pedido pelo usuário, `Qwen/Qwen3.8-27B`, sobe com `--quantization bitsandbytes
   --enforce-eager` a ~3 *tokens*/s, com *KV cache* de 20.384 *tokens* e 12 min de arranque (AC-14).
   Sem `--enforce-eager` cai por OOM. **Descartado pelo usuário em 2026-10-13 por velocidade (D-03).**
   Próximo: escolher o substituto entre os candidatos da PD-19.
4. **Linha de base.** **Objetivo do estudo (usuário, 2026-10-14): vLLM servindo várias requisições
   simultâneas.** Medição B-001 em [runbooks/teste-concorrencia-vllm.md](runbooks/teste-concorrencia-vllm.md):
   `Qwen/Qwen2.5-7B-Instruct` FP16, `vllm bench serve` dentro do *pod*, concorrência 1 a 64.
5. **As GPUs.** 3 réplicas independentes (1 por nó) atrás de um `Service` (D-04). Dividir entre nós pelo
   Ray foi medido em 2026-10-29: o 7B em 2 GPUs (*pipeline parallel* 2) rende 22-25 % **menos** que em 1
   (AC-23). Multinó só para um modelo necessário que não caiba em 1 GPU, aceitando essa perda.
6. **Maior modelo útil.** Quais *quantizations* têm *kernel* em `sm_70`.
7. **Contexto × concorrência.** `--max-model-len`, `--max-num-seqs`, `--gpu-memory-utilization` medidos.
8. **Operação.** *Probes*, reinício, arranque a frio, atualização sem queda.

**A moeda deste repositório:** menos texto, mais decisão por página.
