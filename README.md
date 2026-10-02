# Ponto Digital

Aplicação local de controle de horas. Esta pasta contém o banco de dados atual com seus lançamentos.

## Abrir rapidamente

Dê duplo clique em **Abrir Ponto Digital.bat**. O servidor roda em segundo plano com `pythonw.exe`; a janela do Prompt pode piscar durante a abertura, mas não fica aberta enquanto você usa o sistema.

Se Python ou as dependências ainda não estiverem prontos, o atalho usa `iniciar.bat`, que mostra o Prompt durante a instalação e inicialização. Para ver mensagens de erro, execute `iniciar.bat` diretamente.

## Transferir para outro computador Windows

1. Copie a pasta **ponto digital** inteira. Mantenha os arquivos e subpastas juntos.
2. Instale o Python 3.10 ou mais recente e marque **Add Python to PATH**.
3. Abra **Abrir Ponto Digital.bat**. Na primeira execução pode ser necessária internet para instalar Flask e holidays.

Se a porta padrão estiver ocupada, o sistema seleciona outra porta local automaticamente.

## Seus dados

Os lançamentos, configurações e descontos ficam em `banco_horas.db`, nesta mesma pasta. Para transferir alterações futuras ou fazer uma cópia de segurança, feche o app e copie a pasta inteira novamente.

## Atualizações desta versão

- Escolha mês pelos botões e ano pelo seletor; cada mês cria seus dias ao ser aberto.
- O resumo mensal e o botão de geração do ano foram removidos.
- O total “Extras após banco” mostra HE 50% + HE 100% − banco. Cada linha diária também exibe seu valor em reais.
- Descontos manuais passam a valer a partir do mês cadastrado e se repetem nos meses seguintes até serem removidos.
- INSS/IRRF de 2026 e os valores de previdência complementar e ajustes fiscais aparecem detalhados no holerite. Os dois ajustes fiscais são guardados por mês.
- A defasagem de pagamento é editada em **Regras** e aparece como informativo no holerite. Déficits do mês de pagamento são abatidos do banco recebido.

O módulo `regras/financeiro.py` contém `calcular_folha_2026(...)`, que retorna `ResultadoFolha2026` e `como_dict()` para reutilizar os resultados em interfaces, SQLite ou relatórios.
