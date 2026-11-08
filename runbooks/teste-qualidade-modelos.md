# Runbook — Teste de qualidade dos candidatos (tool calling + resposta), sem o banco

**Pergunta:** qual candidato pede a consulta certa e responde certo às perguntas da aplicação ([F-023]),
com as 50 perguntas de `dataset/dataset-test.csv`? **Decisão que destrava:** o modelo do MVP (PD-25) e o
arranjo: se o 14B FP16 (Ray, 2 GPUs) não acertar claramente mais que o 14B GPTQ-Int8 (1 GPU), ficam 3
réplicas de 1 GPU (D-04), porque por GPU os dois empataram em velocidade (P-05, AC-26).

**Como mede** (os arquivos estão em [`qualidade/`](../qualidade/)). Cada pergunta faz duas chamadas, uma de
cada vez:

| Etapa | O modelo recebe | Nota (dada por `pontuar-respostas.py`, não pelo modelo) |
|---|---|---|
| 1 — consulta | *prompt* de sistema (tabela, colunas, 37 indicadores) + pergunta + ferramenta `consultar_sql` | `tool_calls` válido; o SQL cita os indicadores e as datas do gabarito. **Aproximada**: sem banco, não executa o SQL |
| 2 — resposta | o mesmo + uma chamada simulada + as linhas que o banco devolveria | os números esperados aparecem no texto (aceitando o arredondamento que o texto mostra), mais o termo exigido nas perguntas "qual região/faixa" |

A etapa 2 independe da etapa 1: todo candidato recebe os mesmos dados certos. Nas perguntas com conta
(IDs 40, 41, 44, 45, 48), o modelo recebe só os valores brutos e tem de fazer a conta.
O gabarito sai de `qualidade/montar-gabarito.py`; IDs 43, 46 e 47 recebem a saída do SQL de referência
(o CSV não traz os outros valores) e a ID 50 (pergunta sem resposta na base) é revisada à mão.

**Validado na estação em 2026-11-04** com respostas simuladas: a coleta "perfeita" (SQL de referência +
coluna `Resposta` do CSV) tira 49/49 nas duas etapas. Uma coleta com 10 erros plantados reprova os 5
que estão errados e aprova os 5 corretos escritos de outro jeito ("R$ 33,5 bilhões", "4.9 p.p.").
O coletor também rodou contra um servidor falso local.

**Ressalvas que valem para todo resultado:**

- O *prompt* e a ferramenta são uma proposta do estudo, não os da aplicação `[hipótese]`. O resultado
  compara os candidatos entre si, nas mesmas condições. Com o *prompt* real em mãos, troque-o em
  `montar-gabarito.py` e repita.
- 50 perguntas: com 80 % de acerto, o intervalo de 95 % vai de ~67 % a ~89 % (o relatório imprime o
  intervalo de cada nota). Diferença menor que isso entre dois candidatos não decide nada.
- A ID 34 exige o nome do indicador com **dois espaços** (`jurídica  micro empresa`), como está no CSV.
  Um modelo que "corrija" o espaço erra a consulta, como erraria no banco `[hipótese: o nome no banco é
  o mesmo do CSV]`.
- Unidades do *prompt* (taxas em %, saldos em R$ milhões, série trimestral) vêm do CSV (`FORMAT(VL/100,'p')`,
  rótulos de `Valor_Identificado`) `[não verificado no banco]`.

---

## Ordem e GPUs

| # | Candidato | Comando | GPUs | Cache dos pesos |
|---|---|---|---|---|
| 1 | Qwen2.5-7B FP16 | `qualidade.sh 7b` | 01 | `/home/utec/vllm-estudo/hf-cache` (01) |
| 2 | **controle:** o mesmo 7B pelo Ray | `qualidade.sh 7b-ray` | 01 + 02 | `/var/lib/vllm-estudo/hf-cache`: baixa ~15 GB em 01 e em 02 |
| 3 | Qwen2.5-14B GPTQ-Int8 | `qualidade.sh 14b-int8` | 01 | `/home/utec/vllm-estudo/hf-cache` (01) |
| 4 | Qwen3-30B-A3B GPTQ-Int4 | `qualidade.sh 30b-a3b` | 01 | `/home/utec/vllm-estudo/hf-cache` (01) |
| 5 | Qwen2.5-14B FP16 pelo Ray | `qualidade.sh 14b-fp16-ray` | 01 + 02 | `/var/lib/vllm-estudo/hf-cache` (01 e 02, do P-05) |
| 6 | Mistral-Nemo 12B FP16 (2026-11-05) | `qualidade.sh nemo` | 01 | `/var/lib/vllm-estudo/hf-cache` (01), baixado antes pelo Bloco N1 de [teste-mistral-nemo.md](teste-mistral-nemo.md). Formato Mistral e `--tool-call-parser mistral` ([F-044]); o coletor manda `id` `chamada01` e omite `chat_template_kwargs` para modelos `mistralai/` |

Todos com `v0.19.1`, `--dtype float16 --max-model-len 8192 --gpu-memory-utilization 0.90
--generation-config vllm --enable-auto-tool-choice --tool-call-parser hermes` ([F-042]). O 2 vem logo
depois do 1 para o `qualidade.sh` comparar os dois sozinho (seção `6b`).

**Duração por candidato** `[estimativa]`: 3-15 min de arranque (o 2 baixa os pesos antes) + 100
chamadas de alguns segundos. Os 1, 3 e 4 precisam só da GPU de 01; os 2 e 5, de 01 e 02.

**Antes de rodar:** combine a janela com o administrador. Hoje as 3 GPUs estão com o `vllm-server`
dele (desde 2026-11-03 ~16:33, §2); o script aborta se a GPU estiver reservada ou com processo. Rode o
Bloco 0 de [teste-protocolo-modelos.md](teste-protocolo-modelos.md) em 01 (e em 02, para os 2 e 5).
Se precisar pausar `vllms`, é só com o acordo dele: [pausar-vllms.md](pausar-vllms.md).

---

## Copiar os arquivos para `sabdiia01` (estação, PowerShell)

O login é com o seu usuário (o mesmo do MobaXterm), não com `root`: o `root` recusa a senha por
`ssh` (`Permission denied`, 2026-11-04). Por isso a cópia vai para `/tmp/qualidade-copia`, que qualquer
usuário grava, e o Bloco 1 (como `root`) a move para o lugar. O bloco pergunta o usuário.

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
ssh "${u}@192.168.50.151" "mkdir -p /tmp/qualidade-copia"
scp C:\www\vllm-master\qualidade\qualidade.sh C:\www\vllm-master\qualidade\coletar-respostas.py C:\www\vllm-master\qualidade\pontuar-respostas.py C:\www\vllm-master\qualidade\carga-respostas.py C:\www\vllm-master\qualidade\gabarito-qualidade.json "${u}@192.168.50.151:/tmp/qualidade-copia/"
```

Sem `scp`, o painel SFTP do MobaXterm serve: arraste os 5 arquivos para `/tmp/qualidade-copia`.

## Bloco 1 — Confere os arquivos (servidor `sabdiia01`, bash como `root`; aborta em outro nó)

Entre como de costume e vire `root` (`sudo -i`) antes de colar.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
{
  echo "== $(hostname -s)  $(date -Is)  preparo do teste de qualidade"
  [ "$(hostname -s)" = sabdiia01 ] || { echo "ABORTA: este bloco é para sabdiia01"; exit 1; }
  [ "$(id -u)" = 0 ] || { echo "ABORTA: rode como root (sudo -i)"; exit 1; }
  if [ -d /tmp/qualidade-copia ]; then
    mkdir -p qualidade && cp -v /tmp/qualidade-copia/* qualidade/ && rm -rf /tmp/qualidade-copia
  fi
  cd qualidade || { echo "ABORTA: falta /home/utec/vllm-estudo/qualidade (passo de cópia acima)"; exit 1; }
  sed -i 's/\r$//' qualidade.sh coletar-respostas.py pontuar-respostas.py gabarito-qualidade.json carga-respostas.py
  ls -l qualidade.sh coletar-respostas.py pontuar-respostas.py gabarito-qualidade.json carga-respostas.py
  sha256sum qualidade.sh coletar-respostas.py pontuar-respostas.py gabarito-qualidade.json carga-respostas.py
  bash -n qualidade.sh && echo "qualidade.sh sem erro de sintaxe"
  grep -c '"id":' gabarito-qualidade.json | xargs echo "entradas com id no gabarito (esperado >= 50):"
  grep -q -- '--tool-call-parser hermes' qualidade.sh && echo "flags de tool call presentes"
} 2>&1 | tee qualidade-preparo-$(hostname -s)-$(date +%F-%H%M).log
```

**Pronto se:** os 5 arquivos aparecem, `sem erro de sintaxe` e `flags de tool call presentes`.

## Bloco Q — Roda um candidato (servidor `sabdiia01`, bash)

Um candidato por vez, na ordem da tabela. Cada linha sobe o servidor, coleta, pontua e **apaga os
*pods*** no fim, devolvendo as GPUs.

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
bash qualidade/qualidade.sh 7b 2>&1 | tee qualidade-7b-$(hostname -s)-$(date +%F-%H%M).log
```

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
bash qualidade/qualidade.sh 7b-ray 2>&1 | tee qualidade-7b-ray-$(hostname -s)-$(date +%F-%H%M).log
```

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
bash qualidade/qualidade.sh 14b-int8 2>&1 | tee qualidade-14b-int8-$(hostname -s)-$(date +%F-%H%M).log
```

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
bash qualidade/qualidade.sh 30b-a3b 2>&1 | tee qualidade-30b-a3b-$(hostname -s)-$(date +%F-%H%M).log
```

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
bash qualidade/qualidade.sh 14b-fp16-ray 2>&1 | tee qualidade-14b-fp16-ray-$(hostname -s)-$(date +%F-%H%M).log
```

**Não interrompa com Ctrl+C.** Os *pods* continuam e seguram as GPUs. Se precisar parar:

```bash
# servidor sabdiia01 ou sabdiia02, bash
kubectl delete pod -n vllm-estudo vllm-qual qual-ray-head qual-ray-worker --ignore-not-found
kubectl describe nodes sabdiia01 sabdiia02 | grep -E '^Name:|^  nvidia\.com/gpu +[0-9]'
```

## Expectativa (escrita antes)

- **Formato:** ≥ 95 % nos três Qwen2.5 (o *template* deles é o do *parser* `hermes`, [F-042]). No
  Qwen3-30B-A3B, `hermes` é `[hipótese]`: formato perto de 0 % significa *parser* errado, não modelo
  ruim. Nesse caso, pare e traga o log; o `qwen3_xml` não serve, porque é do Qwen3-**Coder**.
- **Consulta (etapa 1):** a mais baixa das três notas. As falhas prováveis são:
  - a ID 34 (dois espaços no nome);
  - as perguntas "qual região/faixa" (42, 43, 47), que pedem todos os nomes do grupo ou um `LIKE`;
  - as séries por ano (33-39), escritas de muitos jeitos.
  Revise essas à mão antes de concluir.
- **Resposta (etapa 2):** ≥ 90 % no 14B e no 30B-A3B `[hipótese]`. O 7B deve errar mais nas contas
  (IDs 40, 41, 44, 45, 48).
- **Controle (`7b-ray` × `7b`):** respostas idênticas ou quase. A ordem das somas em FP16 muda com a
  divisão entre GPUs e pode trocar um *token* de vez em quando `[hipótese]`. **A nota da etapa 2 não
  pode mudar** em mais de 1-2 perguntas. Se mudar, o Ray altera a qualidade, e isso contraria a
  premissa de comparar arranjos só pela velocidade.

## Resultado da 1ª rodada (2026-11-04)

Contra a expectativa acima: o controle falhou. **Pelo Ray, 0 de 49 *tool calls*** no 7B e no 14B
(AC-27, PD-33). Em 1 GPU, a expectativa se confirmou: formato de 92-98 %, e as duas etapas certas em
92 % no 30B-A3B, 90 % no 14B Int8 e 67 % no 7B (AC-28). Repita só depois de mudar o gabarito, o
*prompt* ou o modelo; para repontuar sem GPU, veja abaixo.

## Rodada 2 — Ferramenta com lista fechada de indicadores (`enum`), preparada em 2026-11-05

**Pergunta:** se a ferramenta só aceitar nomes do catálogo, o Mistral-Nemo para de errar os indicadores por
região e chega perto do 14B Int8? **Decisão que destrava:** o Nemo entra ou não no MVP (AC-29), e se a
aplicação deve trocar o SQL livre por uma ferramenta com parâmetros.

**O que muda (uma coisa por variante, contra a coleta `sql` de AC-28 e AC-29):**

| Variante | Ferramenta | `tool_choice` na etapa 1 | O vLLM obriga o *schema*? ([F-044], `docs/features/tool_calling.md` da `v0.19.1`) |
|---|---|---|---|
| `sql` (feita) | `consultar_sql(sql)` | `auto` | não |
| `enum` | `consultar_indicadores(indicadores, datas)`; `indicadores` é lista com `enum` dos 37 nomes, `datas` é opcional (sem ela, a série inteira) | `auto` | **não**: o modelo vê o `enum`, mas escreve livre |
| `enum-required` | a mesma | `required` | **sim**, por *structured outputs* (`xgrammar`, que trata o *tokenizer* Mistral na `v0.19.1`) |

O *prompt* de sistema muda só na regra 1 (chamar `consultar_indicadores` em vez de escrever SQL). A etapa 2
continua em `auto`, com a chamada simulada na ferramenta nova e os mesmos dados. O pontuador transforma os
argumentos no SQL equivalente (`IN` nos nomes e nas datas) e aplica a mesma régua; as notas antigas não mudam
(repontuadas em 2026-11-05: iguais nas 5 coletas). Testado contra um servidor falso: erros plantados (nome com
"de" a mais, sem datas, resposta em texto) reprovados nas duas variantes, `required` enviado só na etapa 1.

**Ressalva da `enum-required`:** ela também impede responder sem consultar. Parte do ganho do 14B (que
respondeu sem consultar em 4 perguntas, AC-28) vem disso, não do `enum`.

**Expectativa (escrita antes):**

- `enum`: formato ≥ 95 % nos dois. O ganho no Nemo é pequeno `[hipótese]`, porque o catálogo já estava no
  *prompt* e ele errou mesmo assim.
- `enum-required`: nenhum nome fora do catálogo. Consulta certa do Nemo de 80 % para ≥ 90 % `[hipótese]`; o
  que sobrar é região, porte ou data errados, não nome inventado. A 1ª pergunta demora mais (compilação da
  gramática).
- Etapa 2 igual à da `sql`, com diferença de até 2 perguntas, nos dois modelos.
- Se a `enum-required` der erro HTTP em todas as perguntas, é o *structured outputs* com aquele *tokenizer*:
  pare e traga o log.

**Execução** (precisa só da GPU de 01; **pausa de `vllms` só com o acordo do administrador**):

1. Bloco P de [pausar-vllms.md](pausar-vllms.md) e Bloco 0 de [teste-protocolo-modelos.md](teste-protocolo-modelos.md) em 01.
2. Copiar os 4 arquivos de `qualidade/` (o gabarito também mudou) e rodar o Bloco 1 acima. Confira que o
   `sha256sum` do `gabarito-qualidade.json` mudou em relação a 2026-11-04.
3. Os dois candidatos, um por vez (~15 min cada `[estimativa]`: arranque + 2 coletas de 50 perguntas):

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
bash qualidade/qualidade.sh nemo "enum enum-required" 2>&1 | tee qualidade-nemo-enum-$(hostname -s)-$(date +%F-%H%M).log
```

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
bash qualidade/qualidade.sh 14b-int8 "enum enum-required" 2>&1 | tee qualidade-14b-int8-enum-$(hostname -s)-$(date +%F-%H%M).log
```

4. Bloco R de [pausar-vllms.md](pausar-vllms.md) e trazer os resultados (abaixo). Cada pasta
   `resultados/<data>-<candidato>-enum+enum-required/` tem `respostas-enum.jsonl`, `resultado-enum.md`,
   `respostas-enum-required.jsonl` e `resultado-enum-required.md`.

**Resultado (2026-11-06): [AC-30](../ESTUDO-DE-CASO.md#ac-30).** Com `enum-required`, Nemo 90 % e 14B Int8
96 % nas duas etapas; em `auto`, respostas sem consultar. O gabarito passou a `2026-11-06` (IDs 43 e 47, §9 do
estudo): numa nova rodada, copie de novo os 4 arquivos.

**O que olhar:** seções `6-enum` e `6-enum-required` de cada log, contra a linha `sql` de AC-28 e AC-29 (Nemo:
formato 100 %, consulta 80 %, resposta 90 %, as duas 71 %; 14B Int8: 92 %, 92 %, 98 %, 90 %). Nas falhas da
etapa 1, separe nome fora do catálogo (só possível na `enum`) de escolha errada (região, porte, datas).

## Rodada 3 — Carga com as perguntas da aplicação (`carga`), preparada em 2026-11-06

**Pergunta:** com as perguntas reais da aplicação e a ferramenta de AC-30 (`enum-required`), quantas perguntas
por minuto uma GPU atende com 1, 8, 16 e 32 usuários simultâneos, com que espera, e a nota se mantém?
**Decisão que destrava:** Nemo ou 14B Int8 no MVP (AC-29, AC-30), e quantos usuários cada réplica aguenta,
base para dimensionar as 3 réplicas (D-04).

**Por que não basta o protocolo (AC-29):** ele usa 512 *tokens* de entrada; as perguntas da aplicação têm
2.049-2.072 (etapa 1) e até 2.500 (etapa 2) *tokens* no Nemo, e 2.299-2.735 no 14B (`usage` das coletas de
2026-11-06). O *KV cache* do Nemo tem 28.288 *tokens*; sem reaproveitar o *prompt* comum, caberiam ~12
perguntas ao mesmo tempo `[cálculo]`. O *prefix caching* reaproveitou 97 % da entrada com 1 usuário (log do
*pod*); com 32 `[não medido]`. O custo da gramática do `required` sob concorrência também `[não medido]`.

**Como mede** (`carga-respostas.py`, chamado pelo `qualidade.sh` com a variante `carga`): cada usuário faz a
etapa 1 e a etapa 2 de uma pergunta, em sequência e sem *streaming*, e pega a próxima da fila. Por nível, a
fila tem as 50 perguntas 1× (1 e 8 usuários), 2× (16) ou 4× (32). Antes, 4 perguntas de aquecimento.
Vazão contada só enquanto todos os usuários estão ocupados. Mede: perguntas/min, *tokens* gerados/s,
latência por pergunta p50/p95, a nota de cada repetição com a régua do teste de qualidade, quantas respostas
saem idênticas às de 1 usuário, e do `/metrics` do vLLM as séries de preempção, *prefix cache*, uso do
*KV cache* e fila (lidas sem fixar nomes). `nvidia-smi` a cada 2 s em `gpu-carga.csv`. TTFT `[não medido]`:
sem *streaming*, a espera medida é até a resposta completa. Testado em 2026-11-06 contra um servidor falso.

**Expectativa (escrita antes):**

- 1 usuário: latência por pergunta como na Rodada 2 (`enum-required`: Nemo p50 4,34 s, 14B 3,22 s).
- 16 e 32 usuários: o Nemo atende mais perguntas/min que o 14B, mas a razão fica abaixo de 1,9× (protocolo,
  AC-29) `[hipótese]`: a entrada é 4× maior e a gramática pesa mais sob carga.
- Nemo com 32: sem preempção e uso do *KV cache* < 100 %, graças ao *prefix caching* `[hipótese]`. Se houver
  preempção, o limite é o *KV cache* de AC-29.
- Nota igual em todos os níveis (diferença de até 2 perguntas) e 0 erros HTTP. Parte das respostas muda de
  texto sob carga (o lote muda a conta em FP16) sem mudar a nota `[hipótese]`.

**Execução** (só a GPU de 01, ~15 min por modelo `[estimativa]`; `vllms` já pausado em 2026-11-06 08:17):

1. Bloco 0 de [teste-protocolo-modelos.md](teste-protocolo-modelos.md) em 01, se passou mais de 1 h do último.
2. Copiar os **5** arquivos de `qualidade/` (o gabarito e o coletor mudaram; `carga-respostas.py` é novo) e
   rodar o Bloco 1 acima:

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
ssh "${u}@192.168.50.151" "mkdir -p /tmp/qualidade-copia"
scp C:\www\vllm-master\qualidade\qualidade.sh C:\www\vllm-master\qualidade\coletar-respostas.py C:\www\vllm-master\qualidade\pontuar-respostas.py C:\www\vllm-master\qualidade\carga-respostas.py C:\www\vllm-master\qualidade\gabarito-qualidade.json "${u}@192.168.50.151:/tmp/qualidade-copia/"
```

3. Os dois modelos, um por vez, em `sabdiia01` como `root`:

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
bash qualidade/qualidade.sh nemo carga 2>&1 | tee qualidade-nemo-carga-$(hostname -s)-$(date +%F-%H%M).log
```

```bash
mkdir -p /home/utec/vllm-estudo && cd /home/utec/vllm-estudo
bash qualidade/qualidade.sh 14b-int8 carga 2>&1 | tee qualidade-14b-int8-carga-$(hostname -s)-$(date +%F-%H%M).log
```

4. Trazer os resultados (abaixo). Bloco R de [pausar-vllms.md](pausar-vllms.md) quando acabarem os testes do dia.

**Resultado (2026-11-06): [AC-31](../ESTUDO-DE-CASO.md#ac-31).** Com 32 usuários, Nemo 106,9 e 14B Int8 51,0
perguntas/min; nota igual em todos os níveis; Nemo sem preempção (*KV cache* máx 34 %). A expectativa da
razão abaixo de 1,9× errou: deu 1,9× com 16 e 2,1× com 32.

**O que olhar:** seção `6-carga` de cada log: a tabela de vazão, a de qualidade por nível e a do servidor; e
a linha "GPU durante a carga" (o contador `SW Thermal Slowdown` tem de ficar em 0). Compare as duas tabelas
de vazão no mesmo nível de usuários.

## Trazer os resultados (estação, PowerShell)

```powershell
$u = Read-Host "Usuário com que você entra no sabdiia01"
scp "${u}@192.168.50.151:/home/utec/vllm-estudo/qualidade-*.log" "C:\www\vllm-master\logs-analysis\"
New-Item -ItemType Directory -Force "C:\www\vllm-master\logs-analysis\qualidade" | Out-Null
scp -r "${u}@192.168.50.151:/home/utec/vllm-estudo/qualidade/resultados" "C:\www\vllm-master\logs-analysis\qualidade\"
```

Ler basta para trazer: os arquivos que o `root` grava saem legíveis para todos (`umask` 022
`[hipótese]`). Se der `Permission denied` aqui, rode no 01, como `root`:
`chmod -R a+rX /home/utec/vllm-estudo/qualidade /home/utec/vllm-estudo/qualidade-*.log`.

Cada pasta `resultados/<data>-<candidato>/` traz `manifesto.yaml`, `respostas.jsonl` (bruto),
`resultado.md` (nota), os logs dos *pods* e, no `7b-ray`, `controle.md`. Para repontuar todas na
estação, sem GPU (por exemplo, depois de corrigir o gabarito):

```powershell
Get-ChildItem "C:\www\vllm-master\logs-analysis\qualidade\resultados" -Directory | ForEach-Object {
  $n = $_.Name; $r = "$($_.FullName)\resultado-estacao.md"
  python C:\www\vllm-master\qualidade\pontuar-respostas.py C:\www\vllm-master\qualidade\gabarito-qualidade.json "$($_.FullName)\respostas.jsonl" | Out-File -Encoding utf8 $r
  Select-String -Path $r -Pattern '\*\*Etapa' | ForEach-Object { "$n $($_.Line)" }
}
```

## O que olhar

| Onde | O que | Leitura |
|---|---|---|
| Seção 1 | `ABORTA` | GPU ocupada ou *pod* sobrando em `vllm-estudo`: nada foi criado |
| Seção 3 | `pronto=1` | Subiu. Com `pronto=0`, a seção 4 mostra os eventos e a seção 8 o fim dos logs |
| Seção 4 | comando com `--enable-auto-tool-choice --tool-call-parser hermes` | Sem isso, a etapa 1 não vale |
| Seção 5 | `linhas gravadas: 51` | 1 de meta + 50 perguntas. Linhas `SEM tool_call` no progresso = formato falhando |
| Seção 6 | tabela de notas + **Falhas** | Revise cada falha da etapa 1: SQL certo escrito de outro jeito vira acerto manual (anote o ID) |
| Seção 6b | `controle.md` | Só no `7b-ray` (ver Expectativa) |

## Depois

1. Para cada candidato: nota automática, acertos manuais da revisão (com os IDs) e latência por
   pergunta. Com os 5, o resultado vira achado e fecha (ou reabre) a PD-25.
2. Critério de aprovação proposto, **a validar com quem vai usar a aplicação** `[hipótese]`: formato
   ≥ 95 %, consulta certa ≥ 80 %, resposta certa ≥ 90 %.
3. Quando chegarem as credenciais do banco, acrescentar a etapa de ponta a ponta: executar o SQL do
   modelo e mandar o resultado real para a etapa 2.
