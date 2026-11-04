# Teste de qualidade — Qwen/Qwen2.5-7B-Instruct

vLLM `0.19.1`, gabarito `2026-11-04`, início 2026-11-04T15:01:58.183878+00:00, 50 perguntas (49 na nota automática). Parâmetros: `{"temperature": 0, "top_p": 1, "repetition_penalty": 1.0, "chat_template_kwargs": {"enable_thinking": false}}`.

| Medida | Resultado |
|---|---|
| Etapa 1 — formato (`tool_calls` válido) | 48/49 = 98 % (IC 95 %: 89-100 %) |
| Etapa 1 — indicadores certos | 38/49 = 78 % (IC 95 %: 64-87 %) |
| Etapa 1 — datas certas | 47/49 = 96 % (IC 95 %: 86-99 %) |
| **Etapa 1 — consulta certa** (formato + indicadores + datas, aproximada) | **37/49 = 76 % (IC 95 %: 62-85 %)** |
| **Etapa 2 — resposta certa** (com os dados certos) | **40/49 = 82 % (IC 95 %: 69-90 %)** |
| As duas certas | 32/49 = 65 % (IC 95 %: 51-77 %) |
| Latência etapa 1 (1 usuário) | p50 2.25 s, p95 3.73 s, máx 4.30 s |
| Latência etapa 2 (1 usuário) | p50 1.19 s, p95 3.08 s, máx 3.53 s |
| Latência por pergunta (1 + 2, sem o SQL) | p50 3.46 s, p95 6.37 s, máx 6.70 s |
| *Tokens* gerados na etapa 2 | média 65, máx 159 |

## Por categoria

| Categoria | n | Etapa 1 | Etapa 2 |
|---|---|---|---|
| faixas_valor | 9 | 8 | 6 |
| inadimplencia | 9 | 7 | 9 |
| juros | 4 | 2 | 3 |
| prazos | 6 | 5 | 6 |
| regioes | 16 | 12 | 14 |
| saldo_recursos_livres | 5 | 3 | 2 |

## Falhas (revisar à mão: a etapa 1 é aproximada)

| ID | Etapa | Motivo | SQL ou resposta |
|---|---|---|---|
| 3 | etapa 1 | faltam indicadores: Taxa de juros de pessoa jurídica - pequeno porte - recursos livres | `SELECT [DT_REGISTRO], [VL_INDICADOR] FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE [NM_INDICADOR] = 'Taxa de juros de pessoa jurídica  micro empresa - recursos livres' AND [DT_REGISTRO]` |
| 5 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - recursos livres - Total | `SELECT [DT_REGISTRO], [VL_INDICADOR] FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE [NM_INDICADOR] = 'Saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - Total' AN` |
| 5 | etapa 2 | faltam: 2021-07-01 Saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - recursos livres - Total = 250000 | O saldo de crédito com recursos livres para pessoas jurídicas de pequeno porte em 01/07/2021 era de R$ 249,999,500,00 milhões. |
| 7 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - pequeno porte - Sudeste | `SELECT [VL_INDICADOR] FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE [DT_REGISTRO] = '2020-04-01' AND [NM_INDICADOR] = 'Saldo de crédito de pessoa jurídica por região - pequeno porte - S` |
| 21 | etapa 1 | faltam indicadores: Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - Menor que 1 mil | `SELECT [VL_INDICADOR] FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE [DT_REGISTRO] = '2018-04-01' AND [NM_INDICADOR] = 'Saldo de crédito de pessoa jurídica por faixa de valor- pequeno po` |
| 28 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - pequeno porte - Centro-Oeste; Saldo de crédito pessoa jurídica por região - pequeno porte - No | `SELECT [VL_INDICADOR] AS Saldo_Nordeste FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE [NM_INDICADOR] = 'Saldo de crédito de pessoa jurídica por faixa de valor- pequeno porte - Menor que` |
| 31 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - recursos livres - Total | `SELECT [DT_REGISTRO], [NM_INDICADOR], [VL_INDICADOR] FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE [DT_REGISTRO] = '2023-04-01' AND ([NM_INDICADOR] LIKE '%EPP - recursos livres%' OR [NM` |
| 31 | etapa 2 | faltam: 2023-04-01 Saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - recursos livres - Total = 313650; 2023-04-01 Saldo de crédito pess | Em 01/04/2023, o saldo de crédito com recursos livres para pequeno porte foi de R$ 313,65 milhões, enquanto para microempresas foi de R$ 60,55 milhões. |
| 32 | etapa 2 | faltam: 2020-07-01 Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - De 50 mil a 100 mil = 38355.4 | Em 01/07/2020, a faixa que tinha maior saldo de crédito para EPP era de R$ 10 mil a R$ 50 mil, com um saldo de R$ 40.272,70 milhões. |
| 36 | etapa 2 | faltam: 2019-04-01 Saldo de crédito pessoa jurídica por região - pequeno porte - Sul = 34873; 2019-07-01 Saldo de crédito pessoa jurídica por região - pequeno p | O saldo de crédito das EPP da região Sul evoluiu de R$ 33.530,40 milhões em janeiro de 2019 para R$ 37.583,20 milhões em outubro de 2019. Isso representa um aumento de R$ 4.052,80 milhões no período. |
| 37 | etapa 2 | faltam: 2022-04-01 Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - Acima de 100 mil = 170012; 2022-07-01 Saldo de crédito de pessoa jur | O saldo de crédito das EPP na faixa acima de R$ 100 mil evoluiu de R$ 168.550,20 milhões em janeiro de 2022 para R$ 207.578,50 milhões em outubro de 2022. |
| 39 | etapa 1 | não filtra 1º de janeiro de 2019 a 2023 | `SELECT [DT_REGISTRO], [VL_INDICADOR] FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE [NM_INDICADOR] = 'Taxa de inadimplência de pessoa jurídica - Pequeno porte' AND [DT_REGISTRO] BETWEEN ` |
| 41 | etapa 2 | faltam: variação % = 33.2822 | O saldo de crédito com recursos livres das microempresas variou de R$ 43.641,70 milhões em 01/01/2021 para R$ 58.166,60 milhões em 01/01/2023. A variação percentual foi de:  \[ \frac{58166.6 - 43641.7 |
| 42 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - pequeno porte - Norte; Saldo de crédito pessoa jurídica por região - pequeno porte - Nordeste; | `SELECT TOP 1 [NM_REGIAO], [VL_INDICADOR] FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE [DT_REGISTRO] = '2022-04-01' AND [NM_INDICADOR] = 'Saldo de crédito pessoa jurídica por região - p` |
| 42 | etapa 2 | faltam: Sudeste = 128504; termo "sudeste" | O Sul era a região com o maior saldo de crédito para EPP em 01/04/2022, com R$ 74.023,60 milhões. |
| 43 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - microempresa - Norte; Saldo de crédito pessoa jurídica por região - microempresa - Nordeste; S | `SELECT TOP 1 [NM_REGIAO], [VL_INDICADOR] FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE [DT_REGISTRO] = '2021-10-01' AND [NM_INDICADOR] = 'Saldo de crédito pessoa jurídica por região - m` |
| 44 | etapa 1 | faltam indicadores: Saldo de crédito de pessoa jurídica por prazo - pequeno porte - maior que 2 a 5 anos | `SELECT FORMAT(DT_REGISTRO, 'yyyy-MM-dd') AS Data, [VL_INDICADOR] FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE [NM_INDICADOR] IN ('Saldo de crédito de pessoa jurídica por prazo - pequen` |
| 45 | etapa 1 | faltam indicadores: Taxa de juros de pessoa jurídica - pequeno porte - recursos livres | `SELECT [DT_REGISTRO], [VL_INDICADOR] FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE [NM_INDICADOR] = 'Taxa de juros de pessoa jurídica  micro empresa - recursos livres' AND [DT_REGISTRO]` |
| 45 | etapa 2 | faltam: variação % = -50.2994 | A taxa de juros para antecipação de fatura de cartão das EPP reduziu de 33,4% em 01/01/2018 para 16,6% em 01/01/2020, representando uma redução de 16,8 percentage points. |
| 47 | etapa 2 | faltam: 2022-10-01 Saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - Acima de 100 mil = 207578 | O saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - Acima de 100 mil apresentava o maior saldo de crédito das EPP em 01/10/2022, no valor de R$ 207,58 milhões. |
| 49 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 50 | revisão manual | não existe indicador por região E faixa; a resposta certa é dizer que a base não | O saldo de crédito das EPP do Sudeste, na faixa acima de R$ 100 mil, em 01/10/2022 era de R$ 207.578,50 milhões. |

## Alerta: números sem lastro na resposta (podem ser contas legítimas)

| ID | Números | Resposta |
|---|---|---|
| 5 | 250 | O saldo de crédito com recursos livres para pessoas jurídicas de pequeno porte em 01/07/2021 era de R$ 249,999,500,00 milhões. |
| 31 | 313.65, 60.55 | Em 01/04/2023, o saldo de crédito com recursos livres para pequeno porte foi de R$ 313,65 milhões, enquanto para microempresas foi de R$ 60,55 milhões. |
| 34 | 1, 1, 2, 1, 3, 1 | A trajetória trimestral da taxa de juros das microempresas com recursos livres em 2022 foi a seguinte:  - 1º trimestre (1º de janeiro): 39,9% - 2º trimestre (1º |
| 35 | 1, 1 | O saldo de crédito das microempresas do Sudeste apresentou variações ao longo de 2020. No início do ano, em 01 de janeiro, o saldo era de R$ 25.881,50 milhões.  |
| 36 | 4052.8 | O saldo de crédito das EPP da região Sul evoluiu de R$ 33.530,40 milhões em janeiro de 2019 para R$ 37.583,20 milhões em outubro de 2019. Isso representa um aum |
| 41 | 100, 33.55, 33.55 | O saldo de crédito com recursos livres das microempresas variou de R$ 43.641,70 milhões em 01/01/2021 para R$ 58.166,60 milhões em 01/01/2023. A variação percen |
| 45 | 16.8 | A taxa de juros para antecipação de fatura de cartão das EPP reduziu de 33,4% em 01/01/2018 para 16,6% em 01/01/2020, representando uma redução de 16,8 percenta |
| 47 | 207.58 | O saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - Acima de 100 mil apresentava o maior saldo de crédito das EPP em 01/10/2022, no valor |
| 48 | 5.75 | A taxa média de inadimplência das microempresas em 2022 foi de 5,75%. Isso foi calculado com base nos valores de 5,6%, 5,4%, 5,5% e 6,1% observados nos trimestr |
