# Base de estudo operacional do Cashinho

Este documento registra as ideias externas que devem virar testes no Cashinho.
Nenhuma delas autoriza operacao real sozinha. Uma regra so pode virar criterio
operacional depois de passar por custo, amostra minima, holdout, walk-forward e
Monte Carlo.

## Principios que entram no Cashinho

1. Entrada sem saida nao e sistema.
   Toda oportunidade precisa nascer com entrada, stop, alvo, risco em R e tamanho
   da posicao. Sem isso, o Cashinho pode estudar, mas nao pode operar.

2. A conta de R$100 manda no tamanho.
   O objetivo nao e achar o trade "mais bonito", e sim o trade cujo risco cabe na
   conta sem destruir a chance de continuar operando depois de uma sequencia ruim.

3. Score alto precisa provar resultado liquido.
   Score so vale se faixas maiores melhorarem expectativa, drawdown e Monte Carlo
   depois de custos. Se score 90 perde dinheiro, ele deve ser rebaixado no estudo.

4. Mercado muda.
   Media movel, rompimento, VWAP, RSI, Fibonacci e volume podem funcionar em certos
   periodos e falhar em outros. O Cashinho deve separar treino e teste por tempo,
   nunca embaralhar candles.

5. Existem setups diferentes para regimes diferentes.
   Tendencia pede continuacao, pullback ou rompimento; lateralizacao pede retorno a
   media/VWAP; alta volatilidade pede trava extra, liquidez e confirmacao.

6. Day trade para pessoa fisica tem estatistica dura.
   Como a maioria perde depois de custos, o Cashinho deve ser conservador por padrao
   e so abrir excecao quando a vantagem historica for mensuravel.

## Fontes usadas como base

- CVM: materiais educativos e serie sobre riscos de day trade.
  https://www.gov.br/cvm/pt-br/assuntos/noticias/2023/cvm-lanca-serie-de-videos-educacionais-sobre-day-trade

- Chague, De-Losso e Giovannetti: estudo brasileiro sobre day trading para renda.
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101

- Brock, Lakonishok e LeBaron: regras tecnicas simples, medias moveis e rompimentos.
  https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1992.tb04681.x

- Evidencia posterior sobre adaptacao dos mercados e perda de poder das medias moveis.
  https://www.sciencedirect.com/science/article/abs/pii/S1042443115000724

- Van Tharp Institute: position sizing, R-multiple, expectancy e sistemas por tipo de mercado.
  https://vantharpinstitute.com/tharp-think-trading-concepts/

- B3: regras de mercado, call de abertura/fechamento, tuneis de negociacao e custos.
  https://b3.com.br/pt_br/produtos-e-servicos/negociacao/renda-variavel/mercado-de-acoes/caracteristicas-e-regras.htm

- B3: mecanismos de protecao e circuit breaker.
  https://www.b3.com.br/pt_br/noticias/mecanismos-de-protecao-ao-seu-investidor.htm

- Master Clear: biblioteca de e-books, analise tecnica, tape reading e materiais para traders.
  https://master.clear.com.br/ebooks/

- Master Clear: video sobre livros para traders.
  https://master.clear.com.br/videos/melhores-livros-para-traders-ao-vivo-educaclear/

- MetaTrader 5 Python: ticks e historico em UTC.
  https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksfrom_py

## Hipoteses de proximas rodadas

- Testar linhas separadas por regime: tendencia, range, expansao e volatilidade alta.
- Testar score minimo dinamico por setup, nao um unico score para todos.
- Exigir que custo seja pequeno perto do alvo provavel.
- Medir abertura, meio do dia e fechamento separadamente.
- Cruzar ativo principal com Ibovespa, Petrobras, Vale, dolar e juros quando houver dado.
- Fazer replay mais amplo com mais pontos por ano antes de liberar qualquer afrouxamento.
