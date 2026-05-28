# Relatório Técnico-Gerencial: Inflação Cadastral no e-SUS PEC

Data de elaboração: 28/05/2026

## 1. Objetivo

Este relatório tem como objetivo apresentar uma análise preliminar sobre a divergência entre a quantidade de cidadãos existentes no sistema terceiro atualmente utilizado pelo município e a quantidade de cadastros individuais existentes na base do e-SUS PEC.

A análise foi realizada sobre uma cópia restaurada da base do e-SUS PEC, com foco na tabela de cadastros individuais e nos campos de origem, situação cadastral, data de cadastro e indicadores de duplicidade.

## 2. Resumo Executivo

Foi identificada uma diferença expressiva entre os números do sistema terceiro e os dados existentes no e-SUS PEC.

| Fonte | Quantidade |
|---|---:|
| Sistema terceiro em uso | 26.299 cidadãos |
| e-SUS PEC, cadastros atuais, ativos e sem recusa | 39.724 cadastros |
| Diferença PEC x sistema terceiro | 13.425 registros a mais no PEC |

A análise indica que a inflação cadastral no PEC está fortemente associada a uma carga externa de dados, identificada no banco pelo campo `tp_cds_origem = 3`, cujo significado na própria tabela de domínio do e-SUS é **Externo**.

No período de novembro de 2025 a janeiro de 2026, foram encontrados:

| Indicador | Quantidade |
|---|---:|
| Cadastros atuais/ativos/sem recusa criados no período crítico | 19.343 |
| Cadastros desse período com origem Externo | 19.343 |
| Cadastros desse período sem CPF | 19.342 |
| Cadastros desse período sem CNS | 1 |

Esse volume é suficiente para explicar a diferença de 13.425 registros entre o PEC e o sistema terceiro.

## 3. Contexto Operacional

O fluxo informado é o seguinte:

1. O município utiliza um sistema terceiro para operação cotidiana.
2. Esse sistema terceiro não realiza diretamente o envio das informações ao governo federal.
3. Para cumprir o envio, os dados são exportados em lotes.
4. Esses lotes são importados no e-SUS PEC.
5. O e-SUS PEC realiza o envio das informações ao Ministério da Saúde/SISAB.

Também foi informado que a base do PEC é antiga e vem de anos anteriores, e que houve migração/importação de dados mais de uma vez. Após essas importações, passou a ser percebida uma elevação relevante no número de pessoas/cadastros exibidos no PEC.

## 4. Evidências Encontradas

### 4.1. O PEC possui volume muito superior ao sistema terceiro

O sistema terceiro apresenta 26.299 cidadãos. Já o PEC possui 39.724 cadastros individuais atuais, ativos e sem recusa.

Isso gera uma diferença de 13.425 registros a mais no PEC.

### 4.2. A maior parte da diferença está concentrada em um período específico

Os meses com maior volume de cadastros atuais no PEC foram:

| Mês | Cadastros |
|---|---:|
| Janeiro/2026 | 11.418 |
| Novembro/2025 | 4.402 |
| Dezembro/2025 | 3.523 |
| Total do período | 19.343 |

Esse comportamento não é compatível com uma rotina normal de cadastramento gradual. Trata-se de um pico concentrado, com características de carga, migração ou importação em massa.

### 4.3. Todos os cadastros do período crítico vieram de origem externa

Na tabela de domínio do próprio banco do e-SUS PEC, os códigos de origem são:

| Código | Origem |
|---:|---|
| 0 | Offline |
| 1 | Online |
| 2 | PEC |
| 3 | Externo |
| 4 | Android - ACS |
| 5 | Android - AC |
| 6 | e-SUS Vacinação |

No período crítico, todos os 19.343 cadastros analisados estão com:

```text
tp_cds_origem = 3 = Externo
```

Isso indica que os registros não foram criados diretamente por uso normal do PEC, nem por aplicativo Android ACS. Eles entraram no PEC por integração/importação externa.

### 4.4. A carga externa praticamente não trouxe CPF

Dos 19.343 cadastros externos no período crítico:

| Situação | Quantidade |
|---|---:|
| Sem CPF | 19.342 |
| Sem CNS | 1 |
| Sem CPF e sem CNS | 0 |

Ou seja, a carga externa foi praticamente toda baseada em CNS, sem CPF.

Isso é relevante porque o CPF é um identificador forte para deduplicação. Sem CPF, a capacidade do PEC de reconhecer que um cidadão importado já existia anteriormente na base pode ficar reduzida, especialmente quando há variações de nome, data/hora de nascimento, nome da mãe, acentuação, grafia ou CNS inconsistentes/criptografados em registros antigos.

### 4.5. As duplicidades simples não explicam toda a inflação

Foi gerado um relatório de duplicidades estritas usando o critério:

```text
nome + data/hora de nascimento + nome da mãe
```

Esse relatório encontrou centenas de grupos duplicados, mas o volume envolvido não é suficiente, sozinho, para explicar a diferença total entre o PEC e o sistema terceiro.

Isso sugere que o problema não é apenas duplicidade exata. É provável que existam registros recriados com pequenas diferenças, por exemplo:

- nome com ou sem sobrenome adicional;
- diferenças de acentuação;
- abreviações ou pequenas variações de grafia;
- diferenças entre data de nascimento com hora `00:00:00`, `12:00:00` ou `13:00:00`;
- ausência de CPF;
- diferenças em CNS ou identificadores internos;
- registros históricos antigos não unificados com os registros importados.

O arquivo exportado pelo sistema com a lista de duplicados também parece usar critério mais flexível/fuzzy do que o critério estrito aplicado inicialmente no banco.

## 5. Hipótese Mais Provável

A hipótese mais provável é que a inflação cadastral tenha sido causada por importações externas realizadas sobre uma base antiga do PEC, sem que todos os cidadãos importados tenham sido corretamente reconhecidos como cidadãos já existentes.

Em outras palavras:

1. O PEC já possuía uma base histórica antiga.
2. O sistema terceiro exportou lotes de cidadãos/cadastros.
3. Esses lotes foram importados no PEC.
4. Durante a importação, parte dos cidadãos já existentes pode ter sido recriada em vez de atualizada/unificada.
5. Como a carga veio praticamente toda sem CPF, a identificação automática ficou mais frágil.
6. O resultado foi um aumento artificial dos cadastros atuais/ativos no PEC.

A evidência mais forte para essa hipótese é a concentração de 19.343 cadastros de origem **Externo** entre novembro/2025 e janeiro/2026.

## 6. Impactos Potenciais

A inflação cadastral pode gerar impactos como:

- distorção no número de cidadãos acompanhados no PEC;
- dificuldade na gestão territorial;
- dificuldade na análise de indicadores;
- aumento artificial de cadastros ativos;
- duplicidade ou fragmentação do histórico de cidadãos;
- inconsistências entre sistema terceiro, PEC e relatórios oficiais;
- dificuldade em saber qual registro deve permanecer ativo;
- retrabalho para equipes de ACS e coordenação de APS.

## 7. Recomendações

### 7.1. Não realizar novas importações sem validação prévia

Antes de novos lotes externos serem importados no PEC, recomenda-se realizar validação em ambiente de teste ou homologação, comparando:

- quantidade de cidadãos no lote;
- quantidade já existente no PEC;
- quantidade que será criada;
- quantidade que será atualizada;
- percentual sem CPF;
- percentual sem CNS;
- possíveis duplicidades por nome, nascimento e mãe.

### 7.2. Exigir identificadores fortes no sistema terceiro

Sempre que possível, o sistema terceiro deve exportar CPF e CNS de forma consistente.

A ausência de CPF em 19.342 dos 19.343 cadastros externos do período crítico é um sinal importante de fragilidade para deduplicação.

### 7.3. Mapear os cadastros externos do período crítico

Deve ser gerada uma lista operacional dos cadastros:

```text
tp_cds_origem = 3
dt_cad_individual entre 2025-11-01 e 2026-01-31
st_versao_atual = 1
st_ficha_inativa = 0
st_recusa_cad = 0
```

Essa lista representa o principal conjunto suspeito de ter causado a inflação.

### 7.4. Comparar cadastros externos com registros antigos do PEC

Para cada cadastro externo do período crítico, recomenda-se buscar registros anteriores no PEC com critérios progressivos:

1. CNS igual;
2. CPF igual, quando existir;
3. nome + nascimento;
4. nome + nascimento + mãe;
5. nome parecido + nascimento;
6. nome parecido + mãe parecida;
7. telefone, microárea e família, quando disponíveis.

Isso ajudará a identificar quais registros foram provavelmente recriados pela importação.

### 7.5. Separar casos com alta confiança e baixa confiança

Nem toda suspeita deve ser unificada automaticamente.

Sugere-se classificar os casos em:

- **Alta confiança:** mesmo CNS ou CPF, mesmo nome/nascimento, mesma mãe.
- **Média confiança:** nome muito parecido, mesma data de nascimento, mãe parecida.
- **Baixa confiança:** apenas nome parecido ou apenas data coincidente.

Somente casos de alta confiança devem ser considerados para unificação automática. Casos de média e baixa confiança devem passar por validação humana.

### 7.6. Criar rotina de saneamento antes de qualquer unificação

Antes de realizar unificações no PEC, recomenda-se:

- fazer backup completo da base;
- trabalhar primeiro em ambiente de teste;
- gerar relatório de impacto;
- validar amostra com a equipe de APS;
- definir regra oficial de qual cadastro permanece ativo;
- preservar histórico e rastreabilidade;
- documentar todos os critérios usados.

### 7.7. Validar com a gestão e com o fornecedor do sistema terceiro

Como o campo `tp_cds_origem = 3` indica origem externa, é recomendável envolver o fornecedor/responsável técnico do sistema terceiro para esclarecer:

- quais lotes foram exportados;
- quais datas de exportação/importação correspondem a novembro/2025, dezembro/2025 e janeiro/2026;
- se os lotes foram reenviados mais de uma vez;
- se os arquivos continham CPF;
- se houve alteração na regra de geração de CNS, UUID ou identificadores;
- se o sistema terceiro reaproveita os mesmos identificadores entre exportações;
- se houve migração ou recarga completa em vez de carga incremental.

## 8. Próximos Passos Técnicos Sugeridos

1. Gerar relatório completo dos 19.343 cadastros externos do período crítico.
2. Identificar quais deles têm correspondência provável com registros anteriores a novembro/2025.
3. Separar correspondências por grau de confiança.
4. Produzir uma lista de candidatos à unificação.
5. Validar amostras com a equipe responsável.
6. Definir regra de saneamento.
7. Testar a unificação em cópia da base.
8. Somente depois avaliar execução em produção.

## 9. Conclusão

Os dados analisados indicam que a diferença entre o sistema terceiro e o e-SUS PEC não parece ter sido causada por uso normal do PEC.

A inflação cadastral está fortemente concentrada em registros de origem externa (`tp_cds_origem = 3`), principalmente entre novembro de 2025 e janeiro de 2026. Nesse intervalo foram criados/importados 19.343 cadastros atuais, ativos e sem recusa, volume suficiente para explicar a diferença de 13.425 registros entre o PEC e o sistema terceiro.

A hipótese mais provável é que a importação externa tenha recriado cidadãos que já existiam na base antiga do PEC, especialmente porque a carga veio praticamente toda sem CPF, dificultando a deduplicação automática.

Recomenda-se tratar os registros externos do período crítico como o principal universo de investigação e iniciar um processo controlado de saneamento, com backup, validação em ambiente de teste, classificação de confiança e aprovação da gestão antes de qualquer unificação ou alteração definitiva.
