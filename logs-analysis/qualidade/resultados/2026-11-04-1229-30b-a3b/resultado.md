# Teste de qualidade — Qwen/Qwen3-30B-A3B-GPTQ-Int4

vLLM `0.19.1`, gabarito `2026-11-04`, início 2026-11-04T15:32:40.054008+00:00, 50 perguntas (49 na nota automática). Parâmetros: `{"temperature": 0, "top_p": 1, "repetition_penalty": 1.0, "chat_template_kwargs": {"enable_thinking": false}}`.

| Medida | Resultado |
|---|---|
| Etapa 1 — formato (`tool_calls` válido) | 48/49 = 98 % (IC 95 %: 89-100 %) |
| Etapa 1 — indicadores certos | 48/49 = 98 % (IC 95 %: 89-100 %) |
| Etapa 1 — datas certas | 47/49 = 96 % (IC 95 %: 86-99 %) |
| **Etapa 1 — consulta certa** (formato + indicadores + datas, aproximada) | **47/49 = 96 % (IC 95 %: 86-99 %)** |
| **Etapa 2 — resposta certa** (com os dados certos) | **48/49 = 98 % (IC 95 %: 89-100 %)** |
| As duas certas | 46/49 = 94 % (IC 95 %: 83-98 %) |
| Latência etapa 1 (1 usuário) | p50 1.17 s, p95 1.53 s, máx 6.67 s |
| Latência etapa 2 (1 usuário) | p50 1.79 s, p95 3.52 s, máx 3.56 s |
| Latência por pergunta (1 + 2, sem o SQL) | p50 2.96 s, p95 4.82 s, máx 8.18 s |
| *Tokens* gerados na etapa 2 | média 70, máx 183 |

## Por categoria

| Categoria | n | Etapa 1 | Etapa 2 |
|---|---|---|---|
| faixas_valor | 9 | 9 | 8 |
| inadimplencia | 9 | 7 | 9 |
| juros | 4 | 4 | 4 |
| prazos | 6 | 6 | 6 |
| regioes | 16 | 16 | 16 |
| saldo_recursos_livres | 5 | 5 | 5 |

## Falhas (revisar à mão: a etapa 1 é aproximada)

| ID | Etapa | Motivo | SQL ou resposta |
|---|---|---|---|
| 37 | etapa 2 | faltam: 2022-01-01 Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - Acima de 100 mil = 168550; 2022-04-01 Saldo de crédito de pessoa jur | A evolução do saldo de crédito das empresas de pequeno porte (EPP) na faixa acima de R$ 100 mil em 2022 foi a seguinte:  - Janeiro de 2022: R$ 196.216,90 milhões - Abril de 2022: R$ 198.011,80 milhões |
| 39 | etapa 1 | não filtra 1º de janeiro de 2019 a 2023 | `SELECT DT_REGISTRO, VL_INDICADOR FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE NM_INDICADOR = 'Taxa de inadimplência de pessoa jurídica - pequeno porte' AND DT_REGISTRO BETWEEN '2019-01` |
| 49 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 50 | revisão manual | não existe indicador por região E faixa; a resposta certa é dizer que a base não | Em 01/10/2022, o saldo de crédito das EPP do Sudeste, na faixa acima de R$ 100 mil, era de R$ 207.578,50 milhões. |

## Alerta: números sem lastro na resposta (podem ser contas legítimas)

| ID | Números | Resposta |
|---|---|---|
| 33 | 0.6 | A taxa de inadimplência das Empresas de Pequeno Porte (EPP) no Brasil evoluiu da seguinte forma ao longo de 2021:  - Janeiro: 3,5% - Abril: 3,8% - Julho: 3,8% - |
| 37 | 198012, 226217, 237578 | A evolução do saldo de crédito das empresas de pequeno porte (EPP) na faixa acima de R$ 100 mil em 2022 foi a seguinte:  - Janeiro de 2022: R$ 196.216,90 milhõe |
| 48 | 5.8 | A taxa média de inadimplência das microempresas em 2022 foi de 5,8% (calculada com os valores dos trimestres: 5,6%; 5,4%; 5,5% e 6,1%). |
