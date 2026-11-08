# Teste de qualidade — mistralai/Mistral-Nemo-Instruct-2407

vLLM `0.19.1`, gabarito `2026-11-05`, início 2026-11-06T11:26:58.818478+00:00, 50 perguntas (49 na nota automática). Variante: `enum`. Parâmetros: `{"temperature": 0, "top_p": 1, "repetition_penalty": 1.0}`.

| Medida | Resultado |
|---|---|
| Etapa 1 — formato (`tool_calls` válido) | 42/49 = 86 % (IC 95 %: 73-93 %) |
| Etapa 1 — indicadores certos | 41/49 = 84 % (IC 95 %: 71-91 %) |
| Etapa 1 — datas certas | 42/49 = 86 % (IC 95 %: 73-93 %) |
| **Etapa 1 — consulta certa** (formato + indicadores + datas, aproximada) | **41/49 = 84 % (IC 95 %: 71-91 %)** |
| **Etapa 2 — resposta certa** (com os dados certos) | **45/49 = 92 % (IC 95 %: 81-97 %)** |
| As duas certas | 38/49 = 78 % (IC 95 %: 64-87 %) |
| Latência etapa 1 (1 usuário) | p50 2.47 s, p95 5.84 s, máx 7.42 s |
| Latência etapa 2 (1 usuário) | p50 1.97 s, p95 3.73 s, máx 3.94 s |
| Latência por pergunta (1 + 2, sem o SQL) | p50 4.43 s, p95 9.18 s, máx 9.78 s |
| *Tokens* gerados na etapa 2 | média 54, máx 98 |

## Por categoria

| Categoria | n | Etapa 1 | Etapa 2 |
|---|---|---|---|
| faixas_valor | 9 | 7 | 9 |
| inadimplencia | 9 | 8 | 9 |
| juros | 4 | 2 | 3 |
| prazos | 6 | 6 | 5 |
| regioes | 16 | 13 | 16 |
| saldo_recursos_livres | 5 | 5 | 3 |

## Falhas (revisar à mão: a etapa 1 é aproximada)

| ID | Etapa | Motivo | SQL ou resposta |
|---|---|---|---|
| 25 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 28 | etapa 1 | faltam indicadores: Saldo de crédito pessoa jurídica por região - pequeno porte - Centro-Oeste; Saldo de crédito pessoa jurídica por região - pequeno porte - No | `SELECT [DT_REGISTRO], [NM_INDICADOR], [VL_INDICADOR] FROM tabela WHERE [NM_INDICADOR] IN ('Saldo de crédito pessoa jurídica por região - microempresa - Nordeste', 'Saldo de crédito pessoa jurídica por` |
| 30 | etapa 2 | faltam: 2022-10-01 Saldo de crédito de pessoa jurídica por prazo - pequeno porte - maior que 2 a 5 anos = 202113 | Em 01/10/2022, o saldo de crédito das empresas de pequeno porte com prazo de 2 a 5 anos era de R$ 20.211,6 milhões, e acima de 5 anos era de R$ 81.602,5 milhões. |
| 33 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 34 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 37 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 38 | etapa 2 | faltam: 2020-04-01 Saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - recursos livres - Total = 140377; 2020-07-01 Saldo de crédito pess | O saldo de crédito com recursos livres das empresas de pequeno porte cresceu de R$ 136.985,2 milhões em janeiro de 2020 para R$ 203.050,4 milhões em outubro de 2020. |
| 41 | etapa 2 | faltam: variação % = 33.2822 | O saldo de crédito com recursos livres das microempresas passou de R$ 43.641,7 milhões em janeiro de 2021 para R$ 58.166,6 milhões em janeiro de 2023, um aumento de 33,1%. |
| 42 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 43 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 45 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 45 | etapa 2 | faltam: variação % = -50.2994 | A taxa de juros para antecipação de fatura de cartão de empresas de pequeno porte caiu de 33,4% em janeiro de 2018 para 16,6% em janeiro de 2020, uma redução de 16,8%. |
| 50 | revisão manual | não existe indicador por região E faixa; a resposta certa é dizer que a base não | O saldo de crédito das EPP do Sudeste, na faixa acima de R$ 100 mil, em 01/10/2022 era de R$ 207.578,5 milhões. |

## Alerta: números sem lastro na resposta (podem ser contas legítimas)

| ID | Números | Resposta |
|---|---|---|
| 30 | 20211.6 | Em 01/10/2022, o saldo de crédito das empresas de pequeno porte com prazo de 2 a 5 anos era de R$ 20.211,6 milhões, e acima de 5 anos era de R$ 81.602,5 milhões |
| 33 | 1, 2 | A taxa de inadimplência das empresas de pequeno porte (EPP) ficou em 3,5% no 1º trimestre de 2021, passou para 3,8% no 2º trimestre, ficou em 3,8% no 3º trimest |
| 41 | 33.1 | O saldo de crédito com recursos livres das microempresas passou de R$ 43.641,7 milhões em janeiro de 2021 para R$ 58.166,6 milhões em janeiro de 2023, um aument |
| 45 | 16.8 | A taxa de juros para antecipação de fatura de cartão de empresas de pequeno porte caiu de 33,4% em janeiro de 2018 para 16,6% em janeiro de 2020, uma redução de |
