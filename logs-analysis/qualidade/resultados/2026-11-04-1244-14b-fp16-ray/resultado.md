# Teste de qualidade — Qwen/Qwen2.5-14B-Instruct

vLLM `0.19.1`, gabarito `2026-11-04`, início 2026-11-04T15:48:21.823116+00:00, 50 perguntas (49 na nota automática). Parâmetros: `{"temperature": 0, "top_p": 1, "repetition_penalty": 1.0, "chat_template_kwargs": {"enable_thinking": false}}`.

| Medida | Resultado |
|---|---|
| Etapa 1 — formato (`tool_calls` válido) | 0/49 = 0 % (IC 95 %: 0-7 %) |
| Etapa 1 — indicadores certos | 0/49 = 0 % (IC 95 %: 0-7 %) |
| Etapa 1 — datas certas | 0/49 = 0 % (IC 95 %: 0-7 %) |
| **Etapa 1 — consulta certa** (formato + indicadores + datas, aproximada) | **0/49 = 0 % (IC 95 %: 0-7 %)** |
| **Etapa 2 — resposta certa** (com os dados certos) | **46/49 = 94 % (IC 95 %: 83-98 %)** |
| As duas certas | 0/49 = 0 % (IC 95 %: 0-7 %) |
| Latência etapa 1 (1 usuário) | p50 24.27 s, p95 24.37 s, máx 29.54 s |
| Latência etapa 2 (1 usuário) | p50 9.30 s, p95 37.43 s, máx 37.80 s |
| Latência por pergunta (1 + 2, sem o SQL) | p50 33.60 s, p95 61.65 s, máx 62.14 s |
| *Tokens* gerados na etapa 2 | média 362, máx 768 |

## Por categoria

| Categoria | n | Etapa 1 | Etapa 2 |
|---|---|---|---|
| faixas_valor | 9 | 0 | 9 |
| inadimplencia | 9 | 0 | 9 |
| juros | 4 | 0 | 4 |
| prazos | 6 | 0 | 6 |
| regioes | 16 | 0 | 14 |
| saldo_recursos_livres | 5 | 0 | 4 |

## Falhas (revisar à mão: a etapa 1 é aproximada)

| ID | Etapa | Motivo | SQL ou resposta |
|---|---|---|---|
| 1 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 2 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 3 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 4 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 5 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 6 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 7 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 8 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 9 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 10 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 11 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 12 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 13 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 13 | etapa 2 | resposta cortada por max_tokens; faltam: 2018-07-01 Saldo de crédito pessoa jurídica por região - microempresa - Sudeste = 18844 | Em 1 de julho de 2018, o saldo de crédito pessoa jurídica por região - microempresa - Sudeste era de 18,844 milhões de euros. No entanto, esta região não existe e esta informação não é relevante para  |
| 14 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 15 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 16 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 17 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 18 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 19 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 20 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 21 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 22 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 23 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 24 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 25 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 26 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 27 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 28 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 29 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 30 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 31 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 32 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 33 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 34 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 35 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 36 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 37 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 38 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 39 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 40 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 41 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 41 | etapa 2 | faltam: 2021-01-01 Saldo de crédito pessoa jurídica por origem dos recursos - microempresa - recursos livres - Total = 43641.7; 2023-01-01 Saldo de crédito pess | Saldo de crédito pessoa jurídica por origem dos recursos - microempresa - recursos livres - Total variou de 43,642 milhões em 1/1/2021 para 58,167 milhões em 1/1/2023, um aumento de 38,165 milhões ou  |
| 42 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 42 | etapa 2 | resposta cortada por max_tokens; faltam: Sudeste = 128504; termo "sudeste" | Região Tês Mais Onde Oêêêê Parêê Monte Sê Sê Sê Sê Sê Sê Monte Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê Sê |
| 43 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 44 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 45 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 46 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 47 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 48 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 49 | etapa 1 | sem tool_calls (respondeu em texto) | `` |
| 50 | revisão manual | não existe indicador por região E faixa; a resposta certa é dizer que a base não | Qual era o saldo de crédito das EPP do Sudeste, na faixa acima de R$ 100 mil, em 01/10/2022?  No dia 1 de outubro de 2022, o saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - ac |

## Alerta: números sem lastro na resposta (podem ser contas legítimas)

| ID | Números | Resposta |
|---|---|---|
| 1 | 1, 1, 1 | Based on the data available as of January 1, 2016:  - The **Taxa de Inadimplência de Pessoa Jurídica - Pequeno Porte** (Inadmissibility Rate for Small Businesse |
| 3 | 1 | Em 1 de abril de 2018, para empresas de pequeno porte na antecipação de fatura de cartão de crédito com recursos livres, a taxa de juros foi de 30,3%. |
| 4 | 1 | On October 1, 2020, the tax rate for a microenterprise in the anticipation of a credit card bill with free resources was 37%. |
| 5 | 1, 250 | Qual era o saldo de crédito com recursos livres para pessoas jurídicas de pequeno porte em 01/07/2021?  No dia 1 de julho de 2021, o saldo de crédito com recurs |
| 6 | 1, 33.5304 | Qual era o saldo de crédito das empresas de pequeno porte da região Sul em 01/01/2019?  No dia 1 de janeiro de 2019, o saldo de crédito das empresas de pequeno  |
| 7 | 1, 1, 1 | Em 1 de abril de 2020, o saldo de crédito pessoa jurídica por região - pequeno porte - Sudeste era de 76,403.9 euros. Convertendo para o real brasileiro, o sald |
| 8 | 1 | Em 1 de outubro de 2017, o saldo de crédito das pessoas jurídicas de pequeno porte na região Norte foi de 5768,9 euros. No entanto, a conversão em outra unidade |
| 9 | 1, 1, 1, 1, 1, 1 | Em 1 de julho de 2022, o saldo de crédito pessoa jurídica por região - pequeno porte - Nordeste foi de 43,893.8 euros. No entanto, a conversão do saldo de crédi |
| 10 | 1, 17 | Qual era o saldo de crédito das empresas de pequeno porte do Centro-Oeste em 01/04/2016?  No dia 1 de abril de 2016, o saldo de crédito das empresas de pequeno  |
| 11 | 1, 1 | Qual era o saldo de crédito com recursos livres das microempresas em 01/10/2019?  No dia 1 de outubro de 2019, o saldo de crédito com recursos livres das microe |
| 12 | 1, 1.1, 15776.3, 1.1, 15776.3, 1.1 | Qual era o saldo de crédito das microempresas da região Sul em 01/04/2021?  No dia 1 de abril de 2021, o saldo de crédito das microempresas da região Sul da emp |
| 13 | 1, 18.844, 1, 18.844, 18.844, 18.844 | Em 1 de julho de 2018, o saldo de crédito pessoa jurídica por região - microempresa - Sudeste era de 18,844 milhões de euros. No entanto, esta região não existe |
| 14 | 1 | Qual era o saldo de crédito das microempresas da região Norte em 01/04/2023?  No dia 1 de abril de 2023, o saldo de crédito das microempresas da região Norte fo |
| 15 | 1, 1, 1, 1 | Em 1 de outubro de 2020, o saldo de crédito das microempresas nordestinas era de 7320,9 euros. No entanto, a conversão do saldo de crédito da região do euro par |
| 16 | 1, 1, 1.1, 11612.2, 7755.5, 7755.5 | Qual era o saldo de crédito das microempresas do Centro-Oeste em 01/04/2022?  No dia 1 de abril de 2022, o saldo de crédito das microempresas do Centro-Oeste fo |
| 17 | 1, 50.3408, 50.3408, 50.3408, 50.3408 | Qual era o saldo de crédito de empresas de pequeno porte com prazo acima de 5 anos em 01/01/2014?  No dia 1 de janeiro de 2014, o saldo de crédito de pessoa jur |
| 19 | 1.30041e+07, 13.0041, 1.30041e+07, 13.0041, 1.30041e+07, 13.0041 | Qual era o saldo de crédito das empresas de pequeno porte com prazo maior que 1 e até 2 anos em 01/10/2019?  No dia 1 de outubro de 2019, o saldo de crédito de  |
| 23 | 1 | Qual era o saldo de crédito de pequeno porte na faixa de R$ 5 mil a R$ 10 mil em 01/01/2015?  No dia 1 de janeiro de 2015, o saldo de crédito de pessoa jurídica |
| 24 | 1 | Qual era o saldo de crédito das empresas de pequeno porte na faixa de R$ 10 mil a R$ 50 mil em 01/04/2022?  No dia 1 de abril de 2022, o saldo de crédito de pes |
| 25 | 1, 1, 5.2971, 5.2971, 279.971, 1 | Em 1 de outubro de 2021, o saldo de crédito de pessoa jurídica por faixa de valor - pequeno porte - De 50 mil a 100 mil foi 52,971.3 euros. Convertendo para o r |
| 27 | 1 | On January 1, 2020, the tax on inadmissibility for a microenterprise was 10%, and for a small enterprise (EPP) was 5%. |
| 28 | 1, 1, 1, 1, 1, 1 | Comparando o saldo de crédito das Empresas Pequenas e Pequenas Empresas (EPP) do Nordeste e do Centro-Oeste em 1 de outubro de 2022:  - Nordeste: Saldo de Crédi |
| 30 | 1, 1, 1, 1 | Based on the data available for October 1, 2022, there are two saldos de crédito de pessoa jurídica por prazo - pequeno porte (Saldo de crédito de pessoa jurídi |
| 31 | 1, 1, 253097, 1, 253097, 1 | Em 1 de abril de 2023, o saldo de crédito pessoa jurídica por origem dos recursos - pequeno porte - recursos livres - Total foi de 313,650.4 euros, enquanto o s |
| 33 | 1, 1, 1, 1, 1, 1 | A taxa de inadimplência de pessoa jurídica - pequeno porte ao longo de 2021 foi a seguinte:  - 1 de janeiro de 2021: 3.5% - 1 de abril de 2021: 3.8% - 1 de julh |
| 34 | 1, 1, 1, 1 | Based on the quarterly data for 2022, the trajectory of the interest rate for micro-enterprises with unrestricted resources in 2022 was as follows:  - January 1 |
| 35 | 1, 1, 1, 1, 1, 1 | Durante 2020, o saldo de crédito de microempresas por região - microempresa - Sudeste do Brasil variou ao longo do ano. Especificamente:  - Em 1 de janeiro de 2 |
| 36 | 1, 1, 1, 1, 1, 1 | A evolução trimestral do saldo de crédito das Empresas Pequenas e Pequenas Empresas (EPP) da região Sul em 2019 foi a seguinte:  - 1 de janeiro de 2019: 33,530. |
| 37 | 1, 1, 1, 1 | A evolução do saldo de crédito das Empresas de Pequeno Porte (EPP) na faixa acima de R$ 100 mil ao longo de 2022 é a seguinte:  - Em 1º de janeiro de 2022, o sa |
| 38 | 1, 1, 1, 1 | O saldo de crédito com recursos livres para pequeno porte (EPP) ao longo de 2020 aumentou de forma consistente. Especificamente:  - No **1º de janeiro de 2020** |
| 39 | 2 | A taxa de inadimplência de pessoa jurídica - pequeno porte (PEP) no primeiro trimestre dos anos entre 2019 e 2023 evoluiu de 5,9% em 2019 para 5,0% em 2020, 3,5 |
| 40 | 1, 1 | On July 1, 2019, the tax rate for a microenterprise was 10.2%, while for a small enterprise (EPP) it was 5.3%. The difference in the tax rate between a microent |
| 41 | 43.642, 58.167, 38.165, 38.165 | Saldo de crédito pessoa jurídica por origem dos recursos - microempresa - recursos livres - Total variou de 43,642 milhões em 1/1/2021 para 58,167 milhões em 1/ |
| 43 | 1 | Em 1 de outubro de 2021, a região que tinha o menor saldo de crédito para microempresas foi o Norte, com um saldo de crédito de 2139,2 milhões de reais. |
| 45 | 1, 1, 16.8, 16.8, 16.8 | Between January 1, 2018, and January 1, 2020, the tax-free interest rate for small businesses in China decreased from 33.4% to 16.6%. The reduction in the tax-f |
| 48 | 5.57, 1, 1, 1, 1 | A taxa média de inadimplência de pessoa jurídica - microempresa em 2022 foi de 5.57%, com valores específicos de 5.6%, 5.4%, 5.5% e 6.1% respectivamente em 1 de |
| 49 | 1, 1, 1, 1 | Based on the data provided, the evolution of the inadmissibility rate (inadmissibility rate) for micro-enterprises in 2022 is as follows:  - January 1, 2022: 5. |
| 50 | 1, 207.578, 207.578, 207.578, 207.578, 1 | Qual era o saldo de crédito das EPP do Sudeste, na faixa acima de R$ 100 mil, em 01/10/2022?  No dia 1 de outubro de 2022, o saldo de crédito de pessoa jurídica |
