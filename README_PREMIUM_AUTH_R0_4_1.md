# ORKIO Backend Premium Auth R0.4.1

## Escopo

Snapshot cumulativo RC1 construído a partir do backend R0.3.2 e do overlay
Premium R0.4.0. Não exige implantação intermediária do R0.3.2.

## Correções R0.4.1

- corrige isolamento da suíte histórica quando o admin demo está habilitado;
- exige `PLATFORM_DEMO_ADMIN_USERS` sem enfraquecer o fail-closed;
- preserva OIDC/OAuth2 Authorization Code + PKCE;
- preserva introspecção RFC 7662 e identidade resolvida no servidor;
- mantém schema e migrations inalterados.

## Evidência local

- suíte backend integral: 61 testes aprovados;
- nenhuma migration criada ou executada;
- nenhuma dependência Python nova;
- produção continua recusando `demo_headers`.

## Limite de aplicação

Este snapshot corresponde à árvore RC1 compacta recebida no chat. Ele não deve
ser sobreposto ao `main` oficial sem branch isolada, diff completo e adaptação
à árvore efetivamente carregada pelo runtime.
