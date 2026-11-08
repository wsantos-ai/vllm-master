# Teste de qualidade — Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8

vLLM `0.19.1`, gabarito `2026-11-05`, início 2026-11-06T12:01:14.667134+00:00, 50 perguntas (49 na nota automática). Variante: `enum`. Parâmetros: `{"temperature": 0, "top_p": 1, "repetition_penalty": 1.0, "chat_template_kwargs": {"enable_thinking": false}}`.

| Medida | Resultado |
|---|---|
| Etapa 1 — formato (`tool_calls` válido) | 46/49 = 94 % (IC 95 %: 83-98 %) |
| Etapa 1 — indicadores certos | 46/49 = 94 % (IC 95 %: 83-98 %) |
| Etapa 1 — datas certas | 46/49 = 94 % (IC 95 %: 83-98 %) |
| **Etapa 1 — consulta certa** (formato + indicadores + datas, aproximada) | **46/49 = 94 % (IC 95 %: 83-98 %)** |
| **Etapa 2 — resposta certa** (com os dados certos) | **45/49 = 92 % (IC 95 %: 81-97 %)** |
| As duas certas | 42/49 = 86 % (IC 95 %: 73-93 %) |
| Latência etapa 1 (1 usuário) | p50 1.71 s, p95 4.91 s, máx 5.69 s |
| Latência etapa 2 (1 usuário) | p50 1.44 s, p95 3.89 s, máx 4.51 s |
| Latência por pergunta (1 + 2, sem o SQL) | p50 3.18 s, p95 7.91 s, máx 10.21 s |
| *Tokens* gerados na etapa 2 | média 71, máx 186 |

## Por categoria

| Categoria | n | Etapa 1 | Etapa 2 |
|---|---|---|---|
| faixas_valor | 9 | 9 | 8 |
| inadimplencia | 9 | 8 | 9 |
| juros | 4 | 2 | 3 |
| prazos | 6 | 6 | 6 |
| regioes | 16 | 16 | 15 |
| saldo_recursos_livres | 5 | 5 | 4 |

## Falhas (revisar à mão: a etapa 1 é aproximada)

| ID | Etapa | Motivo | SQL ou resposta |
|---|---|---|---|
| 3 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 4 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 41 | etapa 2 | faltam: variação % = 33.2822 | O saldo de crédito com recursos livres das microempresas variou de R$ 43.641,70 milhões em 01/01/2021 para R$ 58.166,60 milhões em 01/01/2023. Isso representa um aumento de 33,30% no período. |
| 43 | etapa 2 | pediu nova consulta em vez de responder |  |
| 45 | etapa 2 | faltam: variação % = -50.2994 | A taxa de juros para antecipação de fatura de cartão de crédito para empresas de pequeno porte (EPP) foi de 33,4% ao ano em 01/01/2018 e reduziu para 16,6% ao ano em 01/01/2020. A redução percentual f |
| 47 | etapa 2 | pediu nova consulta em vez de responder |  |
| 49 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 50 | revisão manual | não existe indicador por região E faixa; a resposta certa é dizer que a base não | O saldo de crédito das EPP (Empresas de Pequeno Porte) do Sudeste, na faixa acima de R$ 100 mil, em 01/10/2022, era de R$ 207.578,50 milhões. |

## Alerta: números sem lastro na resposta (podem ser contas legítimas)

| ID | Números | Resposta |
|---|---|---|
| 36 | 1342.6, 1700.6, 1010.6 | O saldo de crédito das EPP na região Sul foi de R$ 33.530,40 milhões em janeiro de 2019, aumentando para R$ 34.873,00 milhões em abril, R$ 36.572,60 milhões em  |
| 41 | 33.3 | O saldo de crédito com recursos livres das microempresas variou de R$ 43.641,70 milhões em 01/01/2021 para R$ 58.166,60 milhões em 01/01/2023. Isso representa u |
| 45 | 50 | A taxa de juros para antecipação de fatura de cartão de crédito para empresas de pequeno porte (EPP) foi de 33,4% ao ano em 01/01/2018 e reduziu para 16,6% ao a |
