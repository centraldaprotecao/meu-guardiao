"""Conector Azos: Partners API (developers.azos.com.br/portal).

Fatos (documentação + chamadas reais em 2026-11-18; chave só no servidor, header `x-api-key`):
- base https://developers.azos.com.br/api (o gateway antigo api.gateway.azos.com.br dá 503);
- GET /quotation/v1/professions -> [{id, name}];
- POST /quotation/v1/available-coverages (perfil) -> coberturas com min/max/step/available;
- POST /quotation/v1/pricing (perfil + coverages[{code, coverage_chosen}]) -> monthly_premium
  por cobertura. O corpo do perfil exige birth_date, gender (male|female), weight (kg),
  height (m), is_smoker, monthly_income, profession_id.

NÃO confirmado pela Azos (por isso é configuração/aviso, nunca chute silencioso):
- se `monthly_premium` já inclui IOF -> AZOS_PRECO_INCLUI_IOF=sim|nao (obrigatório);
- temporalidade e reajuste de cada cobertura: a API não informa; valores em MAPA são
  premissa e a resposta traz um aviso;
- a equivalência 2013 -> IPTA (invalidez total por acidente) e DG -> 2025 (Doenças graves 30) é por nome comercial.

A cotação é simulação: não vira proposta. A contratação é no portal Azos.
"""

from __future__ import annotations

import json
import os
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date
from typing import Any, Dict, List

from motor_dor.comparador import CoberturaOfertada, Reajuste, Temporalidade

from .base import (
    CoberturaCotada, CoberturaSolicitada, Conector, ErroConector, PerfilCotacao,
    RespostaCotacao,
)

BASE_PADRAO = "https://developers.azos.com.br/api"
TIMEOUT = 3.0  # até 3 chamadas em sequência, dentro do prazo de 8s do registro
_CACHE_PROFISSOES: Dict[str, Any] = {}  # compartilhado entre instâncias; 6h
PROFISSAO_OUTRA = "6154a70ed46bee50b01c610c"  # id de "Outra" na API

# cobertura pedida (interna) -> (código Azos, cobertura interna entregue, temporalidade, reajuste)
# Invalidez: o produto só trabalha a invalidez por acidente (IFPD/ILP/IPT_LISTA estão inativas no
# comparador), e a 2013 da Azos é "Invalidez Permanente Total por Acidente" = IPTA, pelo nome.
# Temporalidade/reajuste: premissa, a API não informa.
MAPA: Dict[str, tuple] = {
    "MORTE_QC": ("2010", "MORTE_QC", Temporalidade.VITALICIO, Reajuste.PREMIO_NIVELADO),
    "IPTA": ("2013", "IPTA", Temporalidade.ATE_IDADE, Reajuste.PREMIO_NIVELADO),
    "DG": ("2025", "DG", Temporalidade.ATE_IDADE, Reajuste.PREMIO_NIVELADO),
    "DIH": ("2006", "DIH", Temporalidade.ATE_IDADE, Reajuste.PREMIO_NIVELADO),
    "CIRURGIA": ("2018", "CIRURGIA", Temporalidade.ATE_IDADE, Reajuste.PREMIO_NIVELADO),
    "FRATURA_RUPTURA": ("2029", "FRATURA_RUPTURA", Temporalidade.ATE_IDADE, Reajuste.PREMIO_NIVELADO),
}


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


def _nascimento(idade: int) -> str:
    hoje = date.today()
    try:
        return hoje.replace(year=hoje.year - idade).isoformat()
    except ValueError:  # 29/02
        return hoje.replace(year=hoje.year - idade, day=28).isoformat()


def _preco_inclui_iof() -> bool:
    v = os.environ.get("AZOS_PRECO_INCLUI_IOF", "").strip().lower()
    if v not in ("sim", "nao"):
        raise ErroConector("azos: defina AZOS_PRECO_INCLUI_IOF=sim ou nao (confirmar com a Azos)")
    return v == "sim"


class ConectorAzos(Conector):
    nome = "azos"

    def __init__(self, abrir=urllib.request.urlopen):
        self._abrir = abrir  # injetável nos testes
        self._profissoes: Dict[str, str] = {}
        self._nomes: Dict[str, str] = {}

    def configurado(self) -> bool:
        return bool(os.environ.get("AZOS_API_KEY"))

    def _chamar(self, metodo: str, caminho: str, corpo: Any = None) -> Any:
        base = os.environ.get("AZOS_BASE_URL", BASE_PADRAO).rstrip("/")
        req = urllib.request.Request(
            base + caminho, method=metodo,
            data=None if corpo is None else json.dumps(corpo).encode(),
            headers={"Content-Type": "application/json", "x-api-key": os.environ["AZOS_API_KEY"]})
        try:
            with self._abrir(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise ErroConector(f"azos: HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise ErroConector(f"azos: {type(e).__name__}") from e

    def listar_profissoes(self) -> List[str]:
        """Nomes das profissões que a Azos aceita (para o formulário). Falha = lista vazia."""
        try:
            self._carregar_profissoes()
        except ErroConector:
            return []
        return sorted((n for n in self._nomes.values() if _sem_acento(n) != "outra"), key=_sem_acento)

    def _carregar_profissoes(self) -> None:
        agora = time.monotonic()
        if not _CACHE_PROFISSOES or agora - _CACHE_PROFISSOES["em"] > 6 * 3600:
            lista = self._chamar("GET", "/quotation/v1/professions")
            _CACHE_PROFISSOES.update(em=agora, itens=lista)
        self._profissoes = {_sem_acento(p["name"]): p["id"] for p in _CACHE_PROFISSOES["itens"]}
        self._nomes = {_sem_acento(p["name"]): p["name"] for p in _CACHE_PROFISSOES["itens"]}

    def _id_profissao(self, nome, avisos: List[str]) -> str:
        if not nome:
            return PROFISSAO_OUTRA
        self._carregar_profissoes()
        achou = self._profissoes.get(_sem_acento(nome))
        if achou:
            return achou
        avisos.append(f"azos: profissão '{nome}' não consta na lista da Azos; cotado como 'Outra'.")
        return PROFISSAO_OUTRA

    def cotar(self, perfil: PerfilCotacao, solicitadas: List[CoberturaSolicitada]) -> RespostaCotacao:
        faltam = [n for n, v in (("peso_kg", perfil.peso_kg), ("altura_cm", perfil.altura_cm),
                                 ("renda_mensal", perfil.renda_mensal)) if not v]
        if faltam:
            raise ErroConector("azos: perfil sem " + ", ".join(faltam) + " (a Azos exige para precificar)")
        iof = _preco_inclui_iof()
        avisos: List[str] = [
            "azos: temporalidade e reajuste das coberturas são premissa (a API não informa)."]
        corpo = {
            "birth_date": _nascimento(perfil.idade),
            "gender": "male" if perfil.sexo == "M" else "female",
            "weight": perfil.peso_kg, "height": round(perfil.altura_cm / 100, 2),
            "is_smoker": perfil.fumante, "monthly_income": perfil.renda_mensal,
            "profession_id": self._id_profissao(perfil.profissao, avisos),
        }

        disp = {c["code"]: c for c in self._chamar(
            "POST", "/quotation/v1/available-coverages", corpo).get("coverages", [])}
        escolhidas: Dict[str, CoberturaSolicitada] = {}
        for s in solicitadas:
            if s.codigo not in MAPA:
                avisos.append(f"azos: sem {s.codigo} no mapa de coberturas.")
                continue
            codigo = MAPA[s.codigo][0]
            d = disp.get(codigo)
            if not d or not d.get("available"):
                avisos.append(f"azos: {s.codigo} recusada para este perfil.")
                continue
            passo = d.get("step") or 1
            capital = min(s.capital, d["max_capital"])
            capital = capital // passo * passo  # a Azos só aceita múltiplos do passo
            if capital < d["min_capital"]:
                avisos.append(f"azos: {s.codigo} abaixo do mínimo ({d['min_capital']:.0f}).")
                continue
            if capital < s.capital:
                avisos.append(f"azos: {s.codigo} limitada a {capital:.0f}.")
            escolhidas[codigo] = CoberturaSolicitada(s.codigo, float(capital))
        if not escolhidas:
            raise ErroConector("azos: nenhuma cobertura pedida está disponível para este perfil")

        dados = self._chamar("POST", "/quotation/v1/pricing", {**corpo, "coverages": [
            {"code": c, "coverage_chosen": s.capital} for c, s in escolhidas.items()]})
        cotadas: List[CoberturaCotada] = []
        for c in dados.get("coverages") or []:
            s = escolhidas.get(c.get("code"))
            if not s:
                continue
            if c.get("error") or c.get("monthly_premium") is None:
                avisos.append(f"azos: {s.codigo} sem preço ({c.get('error')}).")
                continue
            _, entregue, temp, reaj = MAPA[s.codigo]
            cotadas.append(CoberturaCotada(
                entregue, float(c.get("capital") or s.capital), float(c["monthly_premium"]),
                CoberturaOfertada(entregue, temp, reaj)))
        if not cotadas:
            raise ErroConector("azos: resposta sem coberturas cotadas")
        desc = (dados.get("discount") or {}).get("percentage")
        if desc:
            avisos.append(f"azos: preços SEM o desconto de {desc}% que a Azos aplica ao total.")
        return RespostaCotacao("Azos", "Azos Vida", cotadas, avisos=avisos, preco_inclui_iof=iof)
