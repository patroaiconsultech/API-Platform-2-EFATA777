# ORKIO Backend Premium Auth R0.4.0

## Natureza do artefato

Este é um **overlay cumulativo root-ready**. Ele incorpora todos os arquivos
recuperados do R0.3.2 e adiciona o modo Premium de autenticação R0.4.0.

Baseline esperado para aplicação:

- backend R0.3.1 P0 Psycopg hotfix;
- overlay deste ZIP aplicado na raiz do repositório;
- revisão obrigatória do diff antes de commit.

O ZIP-base completo R0.3.1 não estava disponível no chat atual. Portanto,
este artefato não deve ser tratado como snapshot completo do repositório.

## Fluxo de produção

Browser:
OAuth2/OIDC Authorization Code + PKCE.

Backend:
introspecção RFC 7662 usando credenciais confidenciais somente no servidor.

Autoridade de identidade:

- `user_id` vem de claim verificada pelo provedor;
- `tenant_id` vem de claim verificada pelo provedor;
- `role` é resolvida no servidor a partir dos papéis verificados;
- headers `X-Tenant-ID`, `X-User-ID` e `X-Role` são rejeitados em modo OIDC.

Neste desenho, o provedor de identidade é a autoridade delegada de membership.
A promoção para produção exige confirmar que o emissor realmente governa os
claims de tenant e roles conforme a política ORKIO.

## Barreiras de segurança

- nenhum client secret é enviado ao browser;
- refresh token não é solicitado nem persistido por este pacote;
- access token não é registrado em logs;
- cache de introspecção é limitado e nunca ultrapassa a expiração do token;
- produção recusa headers demo e endpoints de identidade sem HTTPS;
- admin demo exige gate global e allowlist explícita de usuários;
- falha do provedor externo é fail-closed.

## Dependências e banco

- nenhuma dependência Python nova;
- nenhuma alteração de schema;
- nenhuma migration incluída ou executada.
