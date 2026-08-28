# Sistema profissional de apoio a decisao

Este documento traduz a especificacao do produto para regras de engenharia do
Cashinho. A premissa central e: preservar capital primeiro, controlar risco
depois, e apenas entao procurar retorno. O sistema nao promete lucro e nao
trata nenhuma estrategia como infalivel.

## Principios obrigatorios

1. `NAO OPERAR` e uma decisao valida.
2. Nenhum indicador isolado libera entrada.
3. Toda entrada precisa de dados validos, contexto, confluencia, risco e
   historico aceitavel.
4. Toda estrategia precisa de hipotese, backtest, validacao fora da amostra,
   estudo por regime e diario operacional.
5. LIVE permanece bloqueado ate existir validacao especifica em PAPER e
   ASSISTED.

## Fluxo alvo

1. Validar dados de mercado.
2. Ler regime do mercado.
3. Ler mercado amplo e correlacoes disponiveis.
4. Ranqueiar ativos.
5. Avaliar confluencias tecnicas.
6. Calcular qualidade da oportunidade.
7. Calcular risco para o capital atual.
8. Gerar `OBSERVACAO`, `PREPARACAO`, `POSSIVEL ENTRADA` ou `NAO OPERAR`.
9. Registrar a decisao no diario.
10. Comparar expectativa com resultado em PAPER.

## Estado atual

- Capital padrao: R$100.
- Modos disponiveis: RESEARCH, BACKTEST, REPLAY e PAPER.
- LIVE segue bloqueado.
- Scanner B3 analisa varios ativos do provider.
- Modo Estudo Profundo verifica mercado amplo antes da decisao.
- Politica operacional historica bloqueia contextos ruins.
- Score profissional classifica a oportunidade por dados, mercado, historico,
  gatilho, risco e confluencia.
- Estudo 2020-2026 versionado em `docs/DEEP_STUDY_2020_2026.md`.

## Score profissional

O score nao e probabilidade de acerto. Ele mede qualidade operacional:

| Fator | Peso | Pergunta |
|---|---:|---|
| Dados | 15 | Os candles sao confiaveis e fechados? |
| Mercado amplo | 15 | O mercado apoia a direcao do ativo? |
| Base historica | 15 | Esse contexto ja foi ruim no estudo? |
| Gatilho | 20 | A entrada foi confirmada por candle fechado? |
| Risco | 15 | Stop, alvo e tamanho cabem no capital? |
| Confluencia | 20 | Existem evidencias independentes suficientes? |

Niveis:

- `NAO OPERAR`: existe bloqueio ou qualidade insuficiente.
- `OBSERVACAO`: algo apareceu, mas ainda esta longe da entrada.
- `PREPARACAO`: a oportunidade esta proxima, mas falta confirmacao.
- `POSSIVEL ENTRADA`: criterios principais atendidos, ainda em PAPER.

## Proximos marcos

1. Estratégias independentes.

   Criar um registro de estrategias com hipotese, regimes aceitos, parametros,
   custos, periodo treinado, periodo validado e periodo fora da amostra.

2. Backtest profissional.

   Expandir metricas com drawdown medio, volatilidade dos resultados,
   retorno ajustado ao risco, Monte Carlo e walk-forward.

3. Alertas.

   Transformar os niveis `OBSERVACAO`, `PREPARACAO` e `POSSIVEL ENTRADA` em
   alertas visuais e sonoros no app.

4. Contexto externo.

   Adicionar Ibovespa, dolar, setores, commodities e correlacoes quando essas
   series estiverem disponiveis no provider.

5. Aprendizado com PAPER.

   Comparar continuamente o que o sistema esperava com o resultado real do
   PAPER: slippage, horario, regime, volume, spread e motivo do stop/alvo.
