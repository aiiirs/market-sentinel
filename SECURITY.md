# Security Policy

## Secrets

Feishu/Lark incoming Webhook URLs are secrets. Do not place them in source code, issue reports, screenshots, commits, or `config.toml`. Use `.env`, which is ignored by Git.

If a Webhook URL is exposed, delete or rotate the corresponding Feishu bot immediately, update your local `.env`, and review repository history before publishing.

## Reporting a vulnerability

Do not open a public issue for a suspected secret exposure or security vulnerability. Contact the repository maintainer privately through the contact method stated in the published repository.
