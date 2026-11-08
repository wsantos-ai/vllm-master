# Teste de qualidade — mistralai/Mistral-Nemo-Instruct-2407

vLLM `0.19.1`, gabarito `2026-11-04`, início 2026-11-05T15:08:13.667116+00:00, 50 perguntas (49 na nota automática). Parâmetros: `{"temperature": 0, "top_p": 1, "repetition_penalty": 1.0}`.

| Medida | Resultado |
|---|---|
| Etapa 1 — formato (`tool_calls` válido) | 49/49 = 100 % (IC 95 %: 93-100 %) |
| Etapa 1 — indicadores certos | 40/49 = 82 % (IC 95 %: 69-90 %) |
| Etapa 1 — datas certas | 48/49 = 98 % (IC 95 %: 89-100 %) |
| **Etapa 1 — consulta certa** (formato + indicadores + datas, aproximada) | **39/49 = 80 % (IC 95 %: 66-89 %)** |
| **Etapa 2 — resposta certa** (com os dados certos) | **44/49 = 90 % (IC 95 %: 78-96 %)** |
| As duas certas | 35/49 = 71 % (IC 95 %: 58-82 %) |
| Latência etapa 1 (1 usuário) | p50 3.92 s, p95 5.97 s, máx 7.20 s |
| Latência etapa 2 (1 usuário) | p50 1.93 s, p95 3.42 s, máx 4.07 s |
| Latência por pergunta (1 + 2, sem o SQL) | p50 5.77 s, p95 9.54 s, máx 10.62 s |
| *Tokens* gerados na etapa 2 | média 53, máx 106 |

## Por categoria

| Categoria | n | Etapa 1 | Etapa 2 |
|---|---|---|---|
| faixas_valor | 9 | 9 | 9 |
| inadimplencia | 9 | 8 | 8 |
| juros | 4 | 4 | 3 |
| prazos | 6 | 6 | 5 |
| regioes | 16 | 8 | 16 |
| saldo_recursos_livres | 5 | 4 | 3 |

## Falhas (revisar à mão: a etapa 1 é aproximada)

| ID | Etapa | Motivo | SQL ou resposta |
|---|---|---|---|
| 6 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - pequeno porte - Sul | `SELECT VL_INDICADOR FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE DT_REGISTRO = '2019-01-01' AND NM_INDICADOR = 'Saldo de crédito de pessoa jurídica por região - pequeno porte - Sul'` |
| 7 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - pequeno porte - Sudeste | `SELECT VL_INDICADOR FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE DT_REGISTRO = '2020-04-01' AND NM_INDICADOR = 'Saldo de crédito de pessoa jurídica por região - pequeno porte - Sudeste` |
| 9 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - pequeno porte - Nordeste | `SELECT VL_INDICADOR FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE DT_REGISTRO = '2022-07-01' AND NM_INDICADOR = 'Saldo de crédito de pessoa jurídica por região - pequeno porte - Nordest` |
| 10 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - pequeno porte - Centro-Oeste | `SELECT VL_INDICADOR FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE DT_REGISTRO = '2016-04-01' AND NM_INDICADOR = 'Saldo de crédito de pessoa jurídica por região - pequeno porte - Centro-` |
| 13 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - microempresa - Sudeste | `SELECT VL_INDICADOR FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE DT_REGISTRO = '2018-07-01' AND NM_INDICADOR = 'Saldo de crédito de pessoa jurídica por região - microempresa - Sudeste'` |
| 15 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - microempresa - Nordeste | `SELECT VL_INDICADOR FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE DT_REGISTRO = '2020-10-01' AND NM_INDICADOR = 'Saldo de crédito de pessoa jurídica por região - microempresa - Nordeste` |
| 30 | etapa 2 | faltam: 2022-10-01 Saldo de crédito de pessoa jurídica por prazo - pequeno porte - acima de 5 anos = 81602.5 | Em 01/10/2022, o saldo de crédito de pessoa jurídica por prazo - pequeno porte - maior que 2 a 5 anos era de R$ 202.112,6 milhões, e o saldo de crédito de pessoa jurídica por prazo - pequeno porte - a |
| 31 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - recursos livres - Total | `SELECT VL_INDICADOR FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE DT_REGISTRO = '2023-04-01' AND NM_INDICADOR = 'Saldo de crédito pessoa jurídica por origem dos recursos - microempresa ` |
| 31 | etapa 2 | faltam: 2023-04-01 Saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - recursos livres - Total = 313650; 2023-04-01 Saldo de crédito pess | Em 01/04/2023, o saldo de crédito com recursos livres para microempresas era de R$ 60,553 milhões, enquanto para empresas de pequeno porte era de R$ 313,650 milhões. |
| 33 | etapa 2 | faltam: 2021-04-01 Taxa de inadimplência de pessoa jurídica - pequeno porte = 3.8; 2021-07-01 Taxa de inadimplência de pessoa jurídica - pequeno porte = 3.8 | A taxa de inadimplência das empresas de pequeno porte ficou em 3,5% em janeiro de 2021 e chegou a 4,1% em outubro de 2021. |
| 39 | etapa 1 | não filtra 1º de janeiro de 2019 a 2023 | `SELECT DT_REGISTRO, NM_INDICADOR, VL_INDICADOR FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE DT_REGISTRO BETWEEN '2019-01-01' AND '2023-03-31' AND NM_INDICADOR IN ('Taxa de inadimplênci` |
| 41 | etapa 2 | faltam: variação % = 33.2822 | O saldo de crédito com recursos livres das microempresas passou de R$ 43.641,7 milhões em janeiro de 2021 para R$ 58.166,6 milhões em janeiro de 2023. No período, o valor aumentou 33,1%. |
| 42 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - pequeno porte - Norte; Saldo de crédito pessoa jurídica por região - pequeno porte - Nordeste; | `SELECT TOP 1 NM_REGIAO, VL_INDICADOR FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE DT_REGISTRO = '2022-04-01' AND NM_INDICADOR = 'Saldo de crédito pessoa jurídica por região - pequeno p` |
| 43 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - microempresa - Nordeste; Saldo de crédito pessoa jurídica por região - microempresa - Centro-O | `SELECT TOP 1 NM_REGIAO, VL_INDICADOR FROM [dataabdichico].[dbo].[ACESSO_AO_CREDITO_BACEN_F] WHERE DT_REGISTRO = '2021-10-01' AND NM_INDICADOR = 'Saldo de crédito pessoa jurídica por região - microempr` |
| 45 | etapa 2 | faltam: variação % = -50.2994 | A taxa de juros para antecipação de fatura de cartão de crédito para empresas de pequeno porte caiu de 33,4% em janeiro de 2018 para 16,6% em janeiro de 2020, uma redução de 16,8%. |
| 50 | revisão manual | não existe indicador por região E faixa; a resposta certa é dizer que a base não | O saldo de crédito das EPP do Sudeste, na faixa acima de R$ 100 mil, em 01/10/2022, era de R$ 207.578,5 milhões. |

## Alerta: números sem lastro na resposta (podem ser contas legítimas)

| ID | Números | Resposta |
|---|---|---|
| 30 | 816025 | Em 01/10/2022, o saldo de crédito de pessoa jurídica por prazo - pequeno porte - maior que 2 a 5 anos era de R$ 202.112,6 milhões, e o saldo de crédito de pesso |
| 31 | 60.553, 313.65 | Em 01/04/2023, o saldo de crédito com recursos livres para microempresas era de R$ 60,553 milhões, enquanto para empresas de pequeno porte era de R$ 313,650 mil |
| 36 | 12.07 | O saldo de crédito das EPP da região Sul foi de R$ 33,53 bilhões em janeiro de 2019, passou para R$ 34,87 bilhões em abril, para R$ 36,57 bilhões em julho e par |
| 41 | 33.1 | O saldo de crédito com recursos livres das microempresas passou de R$ 43.641,7 milhões em janeiro de 2021 para R$ 58.166,6 milhões em janeiro de 2023. No períod |
| 45 | 16.8 | A taxa de juros para antecipação de fatura de cartão de crédito para empresas de pequeno porte caiu de 33,4% em janeiro de 2018 para 16,6% em janeiro de 2020, u |
