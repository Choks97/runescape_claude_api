# GE RuneScape MCP

Servidor MCP (connector para o Claude) que consulta os preços do Grand Exchange do Old School RuneScape e do RuneScape 3. Serve para pesquisar itens, ver preços e histórico e procurar flips e alchs com lucro, diretamente numa conversa com o Claude, no PC ou no telemóvel.

Este projeto não é afiliado à Jagex.

## O que faz

| Ferramenta | Descrição | Jogos |
|---|---|---|
| `search_item` | Procura itens pelo nome | OSRS, RS3 |
| `get_price` | Preço atual do item. No OSRS inclui a margem de flip já com o imposto descontado | OSRS, RS3 |
| `price_history` | Histórico de preços com resumo da tendência | OSRS, RS3 |
| `flip_finder` | Procura os melhores flips para um dado capital, com filtros de preço, volume, margem, ROI e members | OSRS |
| `alch_profit` | Itens em que o high alch dá lucro depois de contar a nature rune | OSRS |
| `calcular_flip` | Calculadora manual de lucro com o imposto do GE | OSRS, RS3 |

## De onde vêm os dados

- **OSRS**: API de preços em tempo real da Wiki do OSRS (`prices.runescape.wiki`), que dá o preço de compra e de venda separados.
- **RS3**: API da Weird Gloop (`api.weirdgloop.org`) e os dados em massa da Wiki do RuneScape.

Isto tem uma consequência importante. No RS3 só existe um preço médio por item, atualizado cerca de uma vez por dia, sem preço de compra e de venda separados. Por isso o `flip_finder` e o `alch_profit` só funcionam no OSRS. No RS3 as ferramentas de pesquisa, preço e histórico funcionam normalmente.

O imposto do GE é calculado como 2% do preço de venda, arredondado para baixo, com máximo de 5M por item e isenção abaixo de 50 gp. Só os bonds estão marcados como isentos, por isso noutros itens isentos a margem pode aparecer ligeiramente abaixo da real. O limite de 5M foi confirmado para o OSRS e assumido igual no RS3.

## Correr no teu computador

Precisas de Python 3.10 ou superior.

```
pip install -r requirements.txt
python server.py
```

O servidor fica em `http://localhost:8000/mcp`.

Antes de o correr, abre o `server.py` e troca o User-Agent na variável `HEADERS` pelo teu contacto. A Wiki pede que quem usa as APIs se identifique, e assim sabem a quem falar se houver algum problema.

Podes testar as ferramentas com o MCP Inspector (`npx @modelcontextprotocol/inspector`), escolhendo o transporte Streamable HTTP. Se reiniciares o servidor, tens de voltar a ligar o Inspector, porque a sessão anterior deixa de existir.

## Pôr online

Para usar o connector no telemóvel, o servidor tem de estar acessível por HTTPS. Uma forma simples é o Render:

1. Cria um Web Service a partir do teu repositório do GitHub.
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `python server.py`
4. Depois do deploy, o endereço do connector é o do serviço com `/mcp` no fim.

No plano gratuito o serviço adormece quando não é usado e a primeira resposta pode demorar cerca de um minuto.

## Ligar ao Claude

No claude.ai, em Settings, Connectors, adiciona um connector personalizado com o endereço `https://o-teu-servico.onrender.com/mcp`. O servidor não tem autenticação, por isso deixa esses campos em branco. Depois de adicionado na web, o connector aparece também na app do telemóvel. Os connectors personalizados podem depender do plano da tua conta.

## Usar e adaptar o projeto

Se quiseres pegar neste projeto e pô-lo a correr num serviço pago, por exemplo um plano pago do Render para não teres o problema de o servidor adormecer, podes fazê-lo à vontade. Só peço que dês crédito ao autor original, com uma menção e uma ligação para este repositório.

Crédito: Choks97 on github (https://github.com/Choks97/runescape_claude_api)

## Aviso

O servidor não tem qualquer proteção, por isso quem tiver o endereço pode usá-lo, e os pedidos às APIs saem com o User-Agent de quem o alojou. Se pores uma instância pública, lembra-te de que a Wiki se reserva o direito de bloquear quem faça demasiados pedidos. A cache incluída reduz o número de pedidos, mas não elimina o risco. Os preços são indicativos e podem estar desatualizados, sobretudo em itens com pouco volume.
