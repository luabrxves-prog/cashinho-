# Base de estudo das estrategias

Este documento registra a base conceitual usada pelo Cashinho antes de qualquer
evolucao para dinheiro real. A regra principal e simples: uma estrategia so entra
no app quando puder virar regra objetiva, teste automatizado, backtest, paper
trading e explicacao clara na interface.

## Principios adotados

1. Mercado antes do ativo.

   Inspiracao: Wyckoff coloca a leitura do mercado como primeiro passo: entender
   se o mercado esta em tendencia ou consolidacao antes de escolher uma acao.
   No Cashinho, isso virou o Modo Estudo Profundo: o scanner le todos os ativos
   disponiveis no provider antes de liberar uma leitura isolada.

2. Ativo em harmonia com o mercado.

   Inspiracao: Wyckoff tambem recomenda selecionar ativos mais fortes que o
   mercado em alta e mais fracos em baixa. No Cashinho, o ativo precisa concordar
   com o vies amplo; se o mercado estiver contra, a entrada fica bloqueada.

3. Regras mecanicas, nao impulso.

   Inspiracao: Turtle Trading usava regras completas para mercado, tamanho,
   entrada, stop e saida. No Cashinho, cada decisao precisa responder: o que foi
   analisado, qual timeframe manda, qual gatilho confirmou, onde esta o stop e
   quanto dinheiro fica em risco.

4. Volatilidade define tamanho.

   Inspiracao: os Turtles dimensionavam posicoes pela volatilidade; Van Tharp
   popularizou o calculo de tamanho pelo risco da conta e distancia ate o stop.
   No Cashinho, a quantidade e calculada por capital, risco por operacao,
   exposicao maxima e diferenca entre entrada e stop.

5. Perda pequena e aceita imediatamente.

   Inspiracao: William O'Neil/IBD enfatiza cortar perdas cedo; a propria base
   publica do IBD cita a regra de 7% a 8% para swing/growth investing. Para o
   Cashinho intradiario, isso nao deve ser copiado literalmente: o stop precisa
   ser tecnico e menor, calculado pelo grafico e pelo capital disponivel.

6. Sem dados validos, nao opera.

   Inspiracao: todos os metodos serios dependem de dado confiavel. No Cashinho,
   candle aberto, dado velho, CSV sintetico ou qualidade bloqueada precisam
   aparecer na interface como motivo de estudo, nunca como entrada real.

7. Mente, metodo e dinheiro precisam virar trava de sistema.

   A lista de livros da Clear destaca Alexander Elder, Mark Douglas, John Murphy,
   Martin Pring, estudos de candlestick e livros sobre gestao de risco. No
   Cashinho, isso vira desenho de produto: plano claro, controle emocional
   automatizado, leitura tecnica explicavel e bloqueios historicos quando a
   maquina encontra contexto ruim.

## Como isso vira regra no app

O fluxo de liberacao deve continuar nesta ordem:

1. Qualidade dos dados.
2. Mercado amplo.
3. Ativo em relacao ao mercado.
4. Multi-timeframe.
5. Candle fechado.
6. Gatilho de entrada.
7. Risco/retorno minimo.
8. Tamanho de posicao compativel com o capital atual.
9. Base historica operacional.
10. PAPER antes de qualquer modo real.

## Perfil inicial de R$100

Com R$100, a meta nao e operar mais por ansiedade. A meta e impedir que uma unica
entrada estrague a conta. O perfil padrao foi ajustado para:

- capital: R$100;
- risco por operacao: 2%;
- perda diaria maxima: 4%;
- uma posicao aberta por vez;
- duas operacoes por dia;
- duas perdas consecutivas como limite;
- risco/retorno minimo: 2:1.

Esses limites sao mais permissivos que um perfil iniciante conservador, mas ainda
mantem a perda maxima em reais visivel. Se o stop de 1 acao passar do limite, o
Cashinho deve bloquear a boleta.

## O que ainda precisa ser estudado

- Custos reais: corretagem, emolumentos, spread, slippage e imposto.
- Liquidez no fracionario para entradas pequenas.
- Backtests com dados reais de B3, nao fixtures sinteticas.
- Resultados separados por ativo, horario, volatilidade e regime de mercado.
- Politica operacional gerada automaticamente a partir dos backtests de 2020 a
  2026, com bloqueios por horario, ativo, regime, volatilidade e timeframe.
- Diario de erros: entrada antecipada, stop mal colocado, ativo sem liquidez,
  noticia, horario ruim e ansiedade operacional.

## Fontes publicas consultadas

- CVM, materiais educativos sobre Day Trade e riscos:
  https://www.gov.br/cvm/pt-br/assuntos/noticias/2023/cvm-lanca-serie-de-videos-educacionais-sobre-day-trade
- CVM, caderno sobre Day Trade e funcionamento da bolsa:
  https://www.gov.br/cvm/pt-br/assuntos/noticias/2020/educacao-financeira-em-pauta--cvm-lanca-materiais-educativos-sobre-day-trade-e-funcionamento-da-bolsa-de-valores-5221f3b6650040a084fd7e3554ad9807
- B3, caracteristicas de acoes e mercado fracionario:
  https://www.b3.com.br/pt_br/produtos-e-servicos/negociacao/renda-variavel/acoes.htm
- StockCharts, tutorial publico sobre o metodo Wyckoff:
  https://chartschool.stockcharts.com/table-of-contents/market-analysis/wyckoff-analysis-articles/the-wyckoff-method-a-tutorial
- TurtleTrader, resumo publico das regras de Turtle Trading:
  https://www.turtletrader.com/rules/
- Van Tharp Institute, calculadora publica de position sizing:
  https://vantharpinstitute.com/tools/position-sizing-calculator/
- IBD/Yahoo Finance, regra publica de corte de perdas de William O'Neil:
  https://finance.yahoo.com/news/why-cutting-stock-losses-short-211000887.html
- Clear, lista de livros para traders e temas de estudo:
  https://master.clear.com.br/livros-para-traders/
