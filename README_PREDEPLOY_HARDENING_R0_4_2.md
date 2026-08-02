# ORKIO Backend Pre-deploy Hardening R0.4.2

## Correções

- elimina o drift de identidade em `/api/auth/status`;
- usa uma fonte canônica para `candidate` e `release_version`;
- alinha `/api/governance/status` à mesma identidade;
- expõe `release_sha` para rastreabilidade do runtime;
- exige que RC1/produção configurem `PLATFORM_RELEASE_SHA`.

Nenhuma migration ou alteração de schema foi adicionada.
