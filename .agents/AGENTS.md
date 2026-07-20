# Diretrizes do Projeto - IPED LXC Wrapper

## Padrão para Geração de Novas Versões (Releases e Branches)

Ao gerar novas versões neste projeto, deve-se seguir o seguinte procedimento padrão:

1. **Definição da Versão de Release na `main`**:
   - Os seguintes arquivos de configuração devem ter a chave `APP_VERSION` atualizada para a versão de release sem o sufixo `-SNAPSHOT` (ex: `1.0.0`):
     - [config.py](file:///media/dell/storage/projetos/iped-lxc/app/config.py) (atributo `APP_VERSION` na classe `Settings`)
     - [.env.example](file:///media/dell/storage/projetos/iped-lxc/.env.example) (`APP_VERSION`)
     - [.env](file:///media/dell/storage/projetos/iped-lxc/.env) (`APP_VERSION`)
   - Realizar o commit das alterações no branch `main` com a mensagem: `release: vX.Y.Z` (onde `X.Y.Z` é a versão).

2. **Criação de Tags**:
   - Criar uma tag git local no formato padrão `vX.Y.Z` apontando para o commit da release.
   - Sincronizar (push) o branch `main` e a tag correspondente com o repositório remoto (`origin`).

3. **Criação e Configuração da Versão de Desenvolvimento**:
   - Criar/mudar para o branch de desenvolvimento `develop` a partir da tag/commit da release na `main`.
   - Atualizar os mesmos arquivos de configuração (`app/config.py`, `.env.example`, `.env`) incrementando a versão e adicionando o sufixo `-SNAPSHOT` (ex: `1.1.0-SNAPSHOT`).
   - Realizar o commit das alterações no branch `develop` com a mensagem: `chore: bump version to X.Y.Z-SNAPSHOT`.
   - Sincronizar (push) o branch `develop` com a `origin` configurando o upstream.
