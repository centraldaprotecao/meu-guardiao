"""Aviso à EQUIPE (corretor) por WhatsApp e e-mail quando entra um pedido novo.

Sem isso, pedido de especialista e solicitação de contratação ficam parados na fila do
backoffice até alguém abrir o painel. Não leva dado de saúde nem CPF: só quem é, o que pediu
e o link do painel.

Variáveis de ambiente (cada canal só liga com as suas):
    EQUIPE_WHATSAPP   celulares da equipe com DDD, separados por vírgula. Exige o CRM
                      (DESKCOMM_URL e DESKCOMM_TOKEN, ver api/crm.py).
    EQUIPE_EMAIL      e-mails da equipe, separados por vírgula. Exige SMTP_HOST e EMAIL_REMETENTE
                      (ver api/envio.py).
    SITE_URL          endereço do site, para o link do painel.

Independe de NOTIFICACOES_ATIVAS, que governa as mensagens ao CLIENTE. Falha de envio vai para o
log e nunca para o cliente: o pedido já foi gravado.
"""

from __future__ import annotations

import logging
import os
import re
from typing import List

from .crm import crm_configurado, enviar_whatsapp
from .envio import email_configurado, enviar_email

log = logging.getLogger("aviso_equipe")


def _lista(nome: str) -> List[str]:
    return [x.strip() for x in os.environ.get(nome, "").split(",") if x.strip()]


def _celular(bruto: str) -> str:
    d = re.sub(r"\D", "", bruto)
    return d[2:] if len(d) in (12, 13) and d.startswith("55") else d


def link_painel() -> str:
    site = os.environ.get("SITE_URL", "").strip().rstrip("/")
    return f"{site}/backoffice" if site else ""


def avisar_equipe(titulo: str, linhas: List[str], chave: str) -> None:
    """Envia `titulo` + `linhas` à equipe. `chave` identifica o pedido (evita duplicar o WhatsApp)."""
    texto = "\n".join([titulo, *linhas, *([f"Painel: {link_painel()}"] if link_painel() else [])])
    if crm_configurado():
        for num in map(_celular, _lista("EQUIPE_WHATSAPP")):
            try:
                enviar_whatsapp(num, "Equipe", texto, 0, idempotencia=f"equipe-{chave}-{num}")
            except Exception as e:  # noqa: BLE001
                log.error("aviso à equipe por WhatsApp falhou: %s", type(e).__name__)
    if email_configurado():
        for dest in _lista("EQUIPE_EMAIL"):
            try:
                enviar_email(dest, titulo, texto)
            except Exception as e:  # noqa: BLE001
                log.error("aviso à equipe por e-mail falhou: %s", type(e).__name__)
